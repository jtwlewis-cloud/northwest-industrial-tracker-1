"""ONS time series API (MM23 dataset) for UK CPI, CPIH and core CPI."""
from __future__ import annotations

from datetime import date, datetime

from ..config import SERIES
from ..http import get
from ..models import FetchResult, Observation
from . import now_iso

JSON = "https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/{cdid}/mm23/data"
PAGE = "https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/{cdid}/mm23"
MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)}


def _month(label: str) -> date:
    y, m = label.split()
    return date(int(y), MONTHS[m.upper()[:3]], 1)


def parse(sid: str, cdid: str, js: dict, retrieved: str) -> tuple[list[Observation], dict]:
    desc = js.get("description", {})
    rel = desc.get("releaseDate", "")
    pub = datetime.fromisoformat(rel.replace("Z", "+00:00")).date() if rel else None
    # releaseDate is stored as 23:00Z the evening before the 07:00 UK release
    if rel and rel.endswith("23:00:00.000Z") and pub:
        pub = date.fromordinal(pub.toordinal() + 1)
    obs = []
    months = js.get("months", [])
    for i, m in enumerate(months):
        if m.get("value") in (None, ""):
            continue
        is_latest = i == len(months) - 1
        obs.append(Observation(sid, _month(m["date"]), float(m["value"]), "ONS MM23", PAGE.format(cdid=cdid),
                               "official", pub if is_latest else None, retrieved, desc.get("title", "")))
    meta = {"next_release": desc.get("nextRelease", ""), "release_date": pub.isoformat() if pub else ""}
    return obs, meta


def fetch(as_of: date) -> FetchResult:
    res = FetchResult("ONS")
    for sid, m in SERIES.items():
        if "ons" not in m:
            continue
        try:
            obs, meta = parse(sid, m["ons"], get(JSON.format(cdid=m["ons"])).json(), now_iso())
            res.observations += obs
            res.meta[sid] = meta
        except Exception as e:  # noqa: BLE001
            res.errors.append(f"ONS {m['ons']}: {e}")
    return res
