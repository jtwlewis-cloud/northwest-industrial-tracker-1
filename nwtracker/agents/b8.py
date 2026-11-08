"""B8 Real Estate – www.b8re.com (paginated search results + detail pages)."""
from __future__ import annotations

import re

from .. import extract as ex
from .base import AgentScraper, cut_related

BASE = "https://www.b8re.com"
RESULTS = BASE + "/property-search-results/?results_page={n}"


class B8RealEstate(AgentScraper):
    name = "B8 Real Estate"
    website = "https://www.b8re.com/"
    method = "Server-rendered property search results (all pages) + detail pages"

    def discover(self):
        out, seen = [], set()
        last = 1
        n = 1
        self.result.search_urls = [BASE + "/property-search-results/"]
        while n <= last and n < 200:
            soup = self.soup(RESULTS.format(n=n))
            for a in soup.select("a[title='Last']"):
                m = re.search(r"results_page=(\d+)", a.get("href", ""))
                if m:
                    last = max(last, int(m.group(1)))
            new = 0
            for a in soup.select("a[href*='/properties/']"):
                href = a["href"].split("?")[0]
                if not href.startswith("http"):
                    href = BASE + href
                if href in seen or href.rstrip("/").endswith("/properties"):
                    continue
                tile = a.parent
                txt = ex.clean(tile.get_text(" | ")) if tile is not None else ""
                if not txt:
                    continue
                seen.add(href)
                new += 1
                parts = [p.strip() for p in txt.split("|") if p.strip()]
                pc = next((p for p in parts if re.fullmatch(r"[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}", p, re.I)), "")
                title = a.get("title") or (parts[-2] if len(parts) >= 2 else txt)
                l = self.stub(href, postcode=pc.upper(), title=title, address=title,
                              town=parts[0] if parts else "")
                l.min_sqft, l.max_sqft = ex.parse_size_range(txt)
                l.property_type = ", ".join(p for p in parts if p.lower() in (
                    "industrial", "warehouse", "logistics", "industrial/logistics", "land", "open storage",
                    "distribution", "trade counter", "manufacturing", "offices", "office", "retail", "design & build"))
                out.append(l)
            if not new and n > 1:
                break
            n += 1
        return out

    def enrich(self, l):
        soup = self.soup(l.url)
        text = cut_related(self.main_text(soup))
        l.description = text
        m = re.search(r"\|\s*Tenancy\s*\|\s*([^|]+)", text)
        if m:
            l.tenure = m.group(1).strip()
        m = re.search(r"\|\s*Type\s*\|\s*([^|]+)", text)
        if m:
            l.property_type = m.group(1).strip()
        m = re.search(r"\|\s*Unit Size\s*\|\s*([^|]+)", text)
        if m:
            a, b = ex.parse_size_range(m.group(1))
            if b:
                l.min_sqft, l.max_sqft = a, b
        h1 = soup.find("h1")
        if h1:
            l.address = ex.clean(h1.get_text(" "))
            l.postcode = ex.find_postcode(l.address) or l.postcode
        head = text[:400].upper()
        desc = re.search(r"Property description \|(.{0,200})", text, re.I)
        lead = (desc.group(1) if desc else "").upper()
        if "UNDER OFFER" in head or "UNDER OFFER" in lead:
            l.marketing_status = "Under Offer"
        elif "FOR SALE" in lead and "TO LET" in lead:
            l.marketing_status = "To Let / For Sale"
        elif "FOR SALE" in lead:
            l.marketing_status = "For Sale"
        elif "TO LET" in lead:
            l.marketing_status = "To Let"
        ag = re.search(r"\|\s*Agent\s*\|(.{0,300}?)(?:\|\s*Other properties|$)", text)
        if ag:
            l.agent_contacts = ex.clean(ag.group(1).replace("|", " "))
        l.brochure_urls = self.pdf_links(soup, l.url)
