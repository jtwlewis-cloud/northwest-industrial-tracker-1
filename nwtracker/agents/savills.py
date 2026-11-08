"""Savills – search.savills.com. The server-rendered search pages for the
North West region embed the full listing data (Next.js page state)."""
from __future__ import annotations

import html
import re

from bs4 import BeautifulSoup

from .. import extract as ex
from .base import AgentScraper, next_data

BASE = "https://search.savills.com"
LISTS = [BASE + "/list/commercial/property-to-let/industrial/england/north-west",
         BASE + "/list/commercial/property-for-sale/industrial/england/north-west"]


class Savills(AgentScraper):
    name = "Savills"
    website = "https://search.savills.com/"
    method = "Server-rendered North West industrial search (to let + for sale, all pages); data embedded in page"

    def discover(self):
        out, seen = [], set()
        for base in LISTS:
            self.result.search_urls.append(base)
            last = 1
            n = 1
            while n <= last and n < 60:
                url = base if n == 1 else f"{base}/page/{n}"
                st = next_data(self.f.get(url).text).get("props", {}).get("initialReduxState", {})
                pm = (st.get("listPage") or {}).get("pageMap") or {}
                for v in pm.values():
                    last = max(last, ((v.get("paging") or {}).get("last") or 1))
                for p in (st.get("properties") or {}).values():
                    pid = p.get("ExternalPropertyIDFormatted")
                    if not pid or pid in seen:
                        continue
                    seen.add(pid)
                    out.append(self.to_listing(p, "for-sale" in base))
                n += 1
        return out

    def to_listing(self, p, sale: bool):
        addr = ", ".join(x for x in [p.get("AddressLine1"), p.get("AddressLine2")] if x)
        l = self.stub(f"{BASE}/property-detail/{p['ExternalPropertyIDFormatted']}",
                      title=p.get("AddressLine1") or addr, address=addr, postcode=ex.find_postcode(addr),
                      property_type=", ".join(t.get("Caption", "") for t in p.get("PropertyTypes") or []))
        l.lat, l.lng = p.get("Latitude"), p.get("Longitude")
        units = p.get("ByUnit") or []
        sizes = [ex.to_float(u.get("sq ft")) for u in units if ex.to_float(u.get("sq ft"))]
        avail_units = [u for u in units if (u.get("Availability") or "").lower() == "available"]
        avail_sizes = [ex.to_float(u.get("sq ft")) for u in avail_units if ex.to_float(u.get("sq ft"))]
        if sizes:
            use = avail_sizes or sizes
            l.min_sqft, l.max_sqft = min(use), sum(use)
            l.total_sqft = sum(sizes)
            if len(sizes) > 1:
                l.notes.append(f"Savills lists {len(units)} units ({len(avail_units)} shown as available)")
        if not l.max_sqft:
            l.min_sqft, l.max_sqft = ex.parse_size_range(p.get("SizeFormatted") or p.get("SizeDescription") or "")
        state = ((p.get("Tracking") or {}).get("propertySoldState") or "")
        if p.get("IsLet") or p.get("IsSold"):
            l.marketing_status = "Let" if p.get("IsLet") else "Sold"
        elif "offer" in state.lower():
            l.marketing_status = "Under Offer"
        else:
            l.marketing_status = "For Sale" if sale else "To Let"
        if units and not avail_units and any("offer" in (u.get("Availability") or "").lower() for u in units):
            l.marketing_status = "Under Offer"
        price = p.get("DisplayPriceText") or p.get("GuidePriceText") or ""
        if sale:
            l.price_text = price
        else:
            l.rent_text = price if price else ""
        if p.get("ClearHeight", {}).get("Meters"):
            l.eaves_m = ex.to_float(p["ClearHeight"]["Meters"])
        body = " | ".join(BeautifulSoup(html.unescape(d.get("Body") or ""), "lxml").get_text(" | ")
                          for d in p.get("LongDescription") or [])
        feats = " | ".join(p.get("WebFeatureList") or [])
        l.description = ex.clean(" | ".join([p.get("Description") or "", feats, body, " ".join(p.get("Location") or [])]))
        ag = [p.get("PrimaryAgent"), p.get("SecondaryAgent")]
        l.agent_contacts = "; ".join(f"{a.get('AgentName')} ({(a.get('Office') or {}).get('OfficeName', 'Savills')}) {a.get('AgentPhoneNumber') or ''}".strip()
                                     for a in ag if a and a.get("AgentName"))
        l.brochure_urls = [b.get("ImageUrl") for b in p.get("BrochureGallery") or [] if (b.get("ImageUrl") or "").lower().endswith(".pdf")]
        if l.marketing_status in ("Let", "Sold"):
            l.excluded_reason = f"Completed transaction (marketing status '{l.marketing_status}')"
        return l
