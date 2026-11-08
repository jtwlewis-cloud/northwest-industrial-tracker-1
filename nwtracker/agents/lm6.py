"""LM6 Property Solutions – lm6.co.uk (paginated property search + detail pages)."""
from __future__ import annotations

import re

from .. import extract as ex
from .base import AgentScraper, cut_related

BASE = "https://lm6.co.uk"
SEARCH = BASE + "/property-search/{page}"


class LM6(AgentScraper):
    name = "LM6"
    website = BASE + "/"
    method = "Server-rendered property search (all pages) + detail pages"

    def discover(self):
        self.result.search_urls = [SEARCH.format(page="")]
        out, seen = [], set()
        for n in range(1, 60):
            try:
                html = self.f.get(SEARCH.format(page="" if n == 1 else f"page/{n}/")).text
            except Exception:
                if n > 1:
                    break
                raise
            links = [u for u in dict.fromkeys(re.findall(r'href="(https://lm6\.co\.uk/property/[^"]+/\d+/)"', html))]
            new = [u for u in links if u not in seen]
            if not new:
                break
            for u in new:
                seen.add(u)
                slug = u.rstrip("/").split("/")[-2]
                m = re.search(r"-([a-z]{1,2}\d[a-z\d]?)$", slug)
                out.append(self.stub(u, postcode=m.group(1).upper() if m else ""))
        return out

    def enrich(self, l):
        soup = self.soup(l.url)
        text = cut_related(self.main_text(soup, "body"))
        l.description = text
        m = re.search(r"\|\s*(To let|For sale|Under offer|To let / For sale|For sale / To let|Let agreed|Sold|Let)\s*\|", text, re.I)
        if m:
            l.marketing_status = m.group(1).strip().title().replace("Let Agreed", "Let agreed")
        h1 = soup.find("h1")
        l.title = ex.clean(h1.get_text(" ")) if h1 else ""
        m = re.search(re.escape(l.title) + r"\s*\|\s*([^|]+)", text) if l.title else None
        loc = m.group(1).strip() if m else ""
        l.address = ", ".join(x for x in [l.title, loc] if x)
        l.postcode = ex.find_postcode(loc) or l.postcode
        for lab, attr in (("Type", "property_type"), ("Tenure", "tenure")):
            m = re.search(rf"\|\s*{lab}\s*\|\s*([^|]+)", text)
            if m:
                setattr(l, attr, m.group(1).strip())
        m = re.search(r"\|\s*Size\s*\|\s*([^|]+)", text)
        if m:
            l.min_sqft, l.max_sqft = ex.parse_size_range(m.group(1) + (" sq ft" if "sq" not in m.group(1) else ""))
        m = re.search(r"\|\s*Rent\s*\|\s*([^|]+)", text)
        if m:
            l.rent_text = m.group(1).strip()
        m = re.search(r"\|\s*Price\s*\|\s*([^|]+)", text)
        if m:
            l.price_text = m.group(1).strip()
        m = re.search(r"Rated\s+([A-G]\+?)\b", text)
        if m:
            l.epc = m.group(1)
        l.brochure_urls = self.pdf_links(soup, l.url)
        l.agent_contacts = self.contacts(soup.find("main") or soup) or "LM6 – 0151 236 2800"
