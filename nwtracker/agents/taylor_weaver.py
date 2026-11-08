"""Taylor Weaver – www.taylorweaver.co.uk (all listings on one search page;
use is encoded in the listing URL)."""
from __future__ import annotations

import re

from .. import extract as ex
from .base import AgentScraper, cut_related

BASE = "https://www.taylorweaver.co.uk"
SEARCH = BASE + "/property-search/"
LINK = re.compile(r'href="(/property/details/(\d+)/([^"]+))"')


class TaylorWeaver(AgentScraper):
    name = "Taylor Weaver"
    website = BASE + "/"
    method = "Server-rendered property search page (all listings) + detail pages"

    def discover(self):
        self.result.search_urls = [SEARCH]
        html = self.f.get(SEARCH).text
        out, seen = [], set()
        for path, pid, slug in LINK.findall(html):
            if pid in seen:
                continue
            seen.add(pid)
            use = slug.rsplit("-", 1)[-1]
            m = re.search(r"-([a-z]{1,2}\d[a-z\d]?)-(\d[a-z]{2})-", slug + "-")
            pc = f"{m.group(1)} {m.group(2)}".upper() if m else ""
            l = self.stub(BASE + path, postcode=pc, property_type=use.title())
            if use in ("office", "retail", "leisure", "residential", "land", "investment"):
                l.excluded_reason = f"Not industrial (type: {use})"
            out.append(l)
        return out

    def enrich(self, l):
        soup = self.soup(l.url)
        text = cut_related(self.main_text(soup, "body"))
        i = text.find("| Make an enquiry |")
        text = text[i:] if i >= 0 else text
        parts = [p.strip() for p in text.split("|") if p.strip()]
        if len(parts) > 2:
            l.title = parts[1]
            l.address = f"{parts[1]}, {parts[2]}"
            l.postcode = ex.find_postcode(parts[2]) or l.postcode
            l.town = parts[2].split(",")[0]
        l.description = text.split("| Request a Viewing | Make an enquiry")[0]
        m = re.search(r"Size:\s*\|\s*([^|]+)", text)
        if m:
            l.min_sqft, l.max_sqft = ex.parse_size_range(m.group(1))
        m = re.search(r"Use:\s*\|\s*([^|]+)", text)
        if m:
            l.property_type = m.group(1).strip()
        m = re.search(r"(Rent|Price):\s*\|\s*([^|]+)", text)
        if m:
            if m.group(1) == "Rent":
                l.rent_text = m.group(2).strip()
                l.marketing_status = l.marketing_status or "To Let"
            else:
                l.price_text = m.group(2).strip()
                l.marketing_status = l.marketing_status or "For Sale"
        if re.search(r"\bunder offer\b", text[:600], re.I):
            l.marketing_status = "Under Offer"
        l.brochure_urls = [re.sub(r".*?url=", "", u).replace("%3A", ":").replace("%2F", "/")
                           for u in re.findall(r'href="([^"]*ViewFile[^"]*)"', str(soup))]
        l.agent_contacts = self.contacts(soup.find("main") or soup) or "Taylor Weaver – 01254 699030"
