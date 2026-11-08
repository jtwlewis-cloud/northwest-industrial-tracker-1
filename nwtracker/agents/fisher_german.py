"""Fisher German – www.fishergerman.co.uk (industrial to rent / for sale
searches, England & Wales, paginated; North West postcodes kept)."""
from __future__ import annotations

import re

from .. import extract as ex
from .base import AgentScraper, cut_related

BASE = "https://www.fishergerman.co.uk"
SEARCHES = [BASE + "/property-search/commercial-industrials-to-rent-in-england-and-wales",
            BASE + "/property-search/commercial-industrials-for-sale-in-england-and-wales"]
LINK = re.compile(r'href="(/commercial-property-(lettings|sales)/([^"]+)/(\d+))"')


class FisherGerman(AgentScraper):
    name = "Fisher German"
    website = BASE + "/properties/commercial"
    method = "Server-rendered industrial searches (to rent + for sale, all pages) + detail pages"

    def discover(self):
        out, seen = [], set()
        for base in SEARCHES:
            self.result.search_urls.append(base)
            for n in range(1, 80):
                html = self.f.get(base if n == 1 else f"{base}/page-{n}").text
                found = LINK.findall(html)
                new = [x for x in found if x[3] not in seen]
                if not new:
                    break
                for path, kind, slug, pid in new:
                    if pid in seen:
                        continue
                    seen.add(pid)
                    m = re.search(r"-([a-z]{1,2}\d[a-z\d]?)-(\d[a-z]{2})(?:-|$)", slug)
                    pc = f"{m.group(1)} {m.group(2)}".upper() if m else ""
                    l = self.stub(BASE + path, postcode=pc,
                                  marketing_status="To Let" if kind == "lettings" else "For Sale",
                                  property_type="Industrial")
                    if not pc:
                        l.title = slug.replace("-", " ")
                    out.append(l)
        return out

    def enrich(self, l):
        soup = self.soup(l.url)
        text = cut_related(self.main_text(soup, "body"))
        i = text.find("Back to search results")
        text = text[i:] if i >= 0 else text
        l.description = text
        parts = [p.strip() for p in text.split("|") if p.strip()]
        addr = next((p for p in parts if ex.find_postcode(p)), "")
        if addr:
            l.address = addr
            l.title = addr.split(",")[0]
            l.postcode = ex.find_postcode(addr)
        a, b = ex.parse_size_range(text.replace("sqft", "sq ft"))
        if b:
            l.min_sqft, l.max_sqft = a, b
        m = re.search(r"\|\s*(£[\d,.]+)\s*\|\s*(Per Sq Ft|Per Annum|PA|Guide Price|Offers[^|]*)", text, re.I)
        if m:
            if "sq ft" in m.group(2).lower():
                l.rent_psf = ex.to_float(m.group(1))
                l.rent_text = f"{m.group(1)} psf"
            elif "sale" in l.marketing_status.lower():
                l.price_text = f"{m.group(1)} {m.group(2)}"
            else:
                l.rent_text = f"{m.group(1)} {m.group(2)}"
        if re.search(r"\bunder offer\b", text[:500], re.I):
            l.marketing_status = "Under Offer"
        l.brochure_urls = self.pdf_links(soup, l.url)
        l.agent_contacts = self.contacts(soup.find("main") or soup) or "Fisher German"
