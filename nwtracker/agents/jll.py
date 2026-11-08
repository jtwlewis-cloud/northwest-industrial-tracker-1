"""JLL – property.jll.co.uk.

robots.txt disallows the search pages (/search, any URL with '?'), so the
published property sitemap is used to enumerate industrial & logistics
listings; each detail page carries structured JSON (__NEXT_DATA__)."""
from __future__ import annotations

import html
import re

from bs4 import BeautifulSoup

from .. import extract as ex
from .base import AgentScraper, next_data

SITEMAP = "https://property.jll.co.uk/sitemap-properties.xml"
URL_RX = re.compile(r"/(rent|sale)-industrial-and-logistics/industrial-and-logistics-(?:rent|sale)-(.+)-([a-z]{1,2}\d[a-z\d]?)-(\d[a-z]{2})-(\d+)$")


class JLL(AgentScraper):
    name = "JLL"
    website = "https://property.jll.co.uk/"
    method = "Property sitemap (search pages disallowed by robots.txt) + structured detail-page JSON"

    def discover(self):
        self.result.search_urls = [SITEMAP]
        xml = self.f.get(SITEMAP).text
        urls = re.findall(r"<loc>([^<]+)</loc>", xml)
        out, seen = [], set()
        for u in urls:
            m = URL_RX.search(u)
            if not m:
                continue
            pid = m.group(5)
            key = (m.group(1), pid)
            if key in seen:
                continue
            seen.add(key)
            pc = f"{m.group(3).upper()} {m.group(4).upper()}"
            l = self.stub(u, postcode=pc, marketing_status="To Let" if m.group(1) == "rent" else "For Sale")
            l.raw["jll_id"] = pid
            out.append(l)
        return out

    def enrich(self, l):
        page = self.f.get(l.url).text
        nd = next_data(page)
        p = nd.get("props", {}).get("pageProps", {}).get("property") or {}
        if not p:
            raise ValueError("no property JSON on page")
        l.title = p.get("title") or ""
        l.address = ", ".join(x for x in [p.get("title"), p.get("address"), p.get("city"), p.get("postcode")] if x)
        l.postcode = (p.get("postcode") or l.postcode).upper()
        l.town = p.get("city") or ""
        l.property_type = ", ".join(p.get("propertyTypes") or [p.get("propertyType") or ""])
        sa = (p.get("surfaceArea") or {})
        if sa.get("unit") == "feet":
            v = sa.get("value")
            if isinstance(v, dict):
                l.min_sqft, l.max_sqft = ex.to_float(v.get("min")), ex.to_float(v.get("max"))
            else:
                l.min_sqft = l.max_sqft = ex.to_float(v)
        l.lat, l.lng = p.get("latitude"), p.get("longitude")
        er = p.get("energyRating") or {}
        ev = er.get("value")
        if isinstance(ev, list):
            ev = " / ".join(str(x) for x in ev if x)
        if ev:
            l.epc = str(ev)
        l.brochure_urls = [b for b in (p.get("brochures") or []) if isinstance(b, str)]
        brokers = p.get("brokers") or []
        l.agent_contacts = "; ".join(
            f"{b.get('name')} ({b.get('jobTitle') or 'JLL'}) {b.get('telephone') or ''} {b.get('email') or ''}".strip()
            for b in brokers)
        desc = " ".join(BeautifulSoup(html.unescape(s.get("content") or ""), "lxml").get_text(" | ")
                        for s in (p.get("descriptionSections") or []))
        l.description = ex.clean(desc + " | " + (p.get("locationDescription") or ""))
        labels = [str(x) for x in (p.get("labels") or [])] + [str(p.get("availabilityLabel") or "")]
        lab = " ".join(x for x in labels if x and x != "None")
        if lab:
            l.marketing_status = f"{l.marketing_status} ({lab})" if "offer" not in lab.lower() else "Under Offer"
        tt = p.get("tenureTypes") or []
        kinds = set(tt) | ({"sale"} if "/sale-" in l.url else {"rent"})
        l.tenure = "Leasehold / Freehold" if len(kinds) > 1 else ("Freehold" if "sale" in kinds else "Leasehold")
        for fld, attr in (("rentPrice", "rent_text"), ("salePrice", "price_text")):
            v = p.get(fld)
            if isinstance(v, dict) and v.get("amount"):
                setattr(l, attr, f"£{v.get('amount')} {v.get('unit') or v.get('period') or ''}".strip())
        if p.get("availabilitiesCount", 0) and p.get("availabilitiesCount", 0) > 1:
            l.notes.append(f"JLL lists {p['availabilitiesCount']} availabilities within this listing")
        l.raw["jll"] = {k: p.get(k) for k in ("id", "region", "submarket", "district")}
