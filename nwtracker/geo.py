"""Postcode -> local authority / county / submarket using postcodes.io
(open ONS data), cached in SQLite so repeat runs are fast and offline-safe."""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections import Counter

from . import config
from .extract import outcode, postcode_area
from .http import Fetcher

log = logging.getLogger(__name__)
API = "https://api.postcodes.io"


def is_candidate_nw(pc: str) -> bool:
    """Cheap pre-filter: could this postcode / outcode be in the North West?"""
    pc = (pc or "").upper().strip()
    if not pc:
        return False
    oc = outcode(pc)
    if oc in config.NW_EXTRA_DISTRICTS:
        return True
    return postcode_area(pc) in config.NW_POSTCODE_AREAS


class Geo:
    def __init__(self, fetcher: Fetcher, db_path=config.DB_PATH):
        self.f = fetcher
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.execute("CREATE TABLE IF NOT EXISTS geo_cache (key TEXT PRIMARY KEY, value TEXT)")
        self.conn.commit()

    # ------------------------------------------------------------- cache
    def _get(self, key):
        with self.lock:
            row = self.conn.execute("SELECT value FROM geo_cache WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def _put(self, key, value):
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO geo_cache VALUES (?,?)", (key, json.dumps(value)))
            self.conn.commit()

    def _api(self, path: str):
        try:
            r = self.f.get(API + path, check_robots=False, retries=2)
            return r.json().get("result")
        except Exception as e:  # 404 for unknown postcodes, network issues
            log.debug("postcodes.io %s failed: %s", path, e)
            return None

    # ------------------------------------------------------------- lookups
    def lookup_postcode(self, pc: str) -> dict | None:
        key = "pc:" + pc.replace(" ", "").upper()
        cached = self._get(key)
        if cached is not None:
            return cached or None
        res = self._api("/postcodes/" + pc.replace(" ", ""))
        if not res:
            res = self._api("/terminated_postcodes/" + pc.replace(" ", ""))
            if res:  # terminated postcodes only return coordinates
                res = self.reverse(res.get("latitude"), res.get("longitude")) or {}
        out = {}
        if res:
            out = {"admin_district": res.get("admin_district"), "region": res.get("region"),
                   "lat": res.get("latitude"), "lng": res.get("longitude"),
                   "admin_ward": res.get("admin_ward"), "postcode": res.get("postcode")}
        self._put(key, out)
        return out or None

    def lookup_outcode(self, oc: str) -> dict | None:
        key = "oc:" + oc.upper()
        cached = self._get(key)
        if cached is not None:
            return cached or None
        res = self._api("/outcodes/" + oc.upper())
        out = {}
        if res:
            out = {"admin_district": res.get("admin_district") or [], "lat": res.get("latitude"),
                   "lng": res.get("longitude")}
        self._put(key, out)
        return out or None

    def reverse(self, lat, lng) -> dict | None:
        if lat is None or lng is None:
            return None
        key = f"ll:{float(lat):.5f},{float(lng):.5f}"
        cached = self._get(key)
        if cached is not None:
            return cached or None
        res = self._api(f"/postcodes?lon={lng}&lat={lat}&limit=1&radius=2000")
        out = {}
        if res:
            r0 = res[0]
            out = {"admin_district": r0.get("admin_district"), "region": r0.get("region"),
                   "postcode": r0.get("postcode"), "lat": r0.get("latitude"), "lng": r0.get("longitude")}
        self._put(key, out)
        return out or None

    def place(self, name: str) -> dict | None:
        """Town / place name -> coordinates (Ordnance Survey open names)."""
        name = (name or "").strip()
        if not name:
            return None
        key = "pl:" + name.lower()
        cached = self._get(key)
        if cached is not None:
            return cached or None
        from urllib.parse import quote
        res = self._api(f"/places?q={quote(name)}&limit=5")
        out = {}
        for r0 in res or []:
            if (r0.get("region") or "") == "North West" or r0.get("country") == "England":
                out = {"lat": r0.get("latitude"), "lng": r0.get("longitude"), "name": r0.get("name_1"),
                       "region": r0.get("region")}
                if r0.get("region") == "North West":
                    break
        self._put(key, out)
        return out or None

    # ------------------------------------------------------------- resolve
    def resolve(self, postcode: str = "", lat=None, lng=None) -> dict:
        """Return {county, local_authority, submarket, method, note, lat, lng}."""
        pc = (postcode or "").upper().strip()
        info: dict = {"county": "", "local_authority": "", "submarket": "", "method": "", "note": ""}
        district = None
        if pc and " " in pc:
            r = self.lookup_postcode(pc)
            if r and r.get("admin_district"):
                district, info["method"] = r["admin_district"], "postcode"
                info["lat"], info["lng"] = r.get("lat"), r.get("lng")
        if district is None and lat is not None and lng is not None:
            r = self.reverse(lat, lng)
            if r and r.get("admin_district"):
                district, info["method"] = r["admin_district"], "coordinates"
                info["note"] = f"County derived from map coordinates (nearest postcode {r.get('postcode')})"
                if not pc:
                    info["derived_postcode_district"] = outcode(r.get("postcode", ""))
        if district is None and pc:
            r = self.lookup_outcode(outcode(pc))
            if r and r.get("admin_district"):
                ds = r["admin_district"]
                counties = Counter(config.DISTRICT_TO_COUNTY.get(d, "Outside North West") for d in ds)
                if len(counties) == 1:
                    district = ds[0] if len(ds) == 1 else None
                    info["county"] = next(iter(counties))
                    info["local_authority"] = " / ".join(ds)
                    info["method"] = "postcode district"
                else:
                    info["county"] = counties.most_common(1)[0][0]
                    info["local_authority"] = " / ".join(ds)
                    info["method"] = "postcode district (ambiguous)"
                    info["note"] = (f"Only partial postcode {outcode(pc)} published; district spans "
                                    f"{', '.join(ds)} – county to be checked")
        if district:
            info["local_authority"] = district
            info["county"] = config.DISTRICT_TO_COUNTY.get(district, "Outside North West")
        oc = outcode(pc) if pc else info.get("derived_postcode_district", "")
        if info["county"] in config.COUNTIES:
            info["submarket"] = config.SUBMARKET_OVERRIDES.get(oc) or info["local_authority"]
        return info
