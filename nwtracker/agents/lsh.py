"""Lambert Smith Hampton – www.lsh.co.uk.
Uses the public search endpoint behind /find/properties with a radius
centred on the North West, then reads detail pages."""
from __future__ import annotations

import html as htmlmod
import re

from .. import extract as ex
from .base import AgentScraper, cut_related

BASE = "https://www.lsh.co.uk"
API = BASE + "/api/lsh/propertyclientsearch/results"
CARD_RX = re.compile(r'href="(/find/properties/[^"]+)".*?<p class="bold caps">([^<]+)</p>\s*<p>([^<]+)</p>', re.S)


class LSH(AgentScraper):
    name = "Lambert Smith Hampton"
    website = "https://www.lsh.co.uk/find/properties"
    method = "Site search endpoint (180 km radius around the North West, paginated) + detail pages"

    def discover(self):
        self.result.search_urls = [BASE + "/find/properties"]
        self.f.get(BASE + "/find/properties")
        out, seen = [], set()
        for page in range(1, 80):
            data = {"PropertyListTotalResultCount": 0, "MarkerCacheKey": "", "MarkerCacheKeyClear": "false",
                    "MarkerSkip": 0, "MarkerTake": 0, "Term": "", "Places": "false", "Zoom": 8,
                    "Longitude": -2.70, "Latitude": 54.05, "Radius": 180, "MaxMarkerCount": 4000,
                    "PropertyResultsPerPage": 48, "PropertyPage": page, "IsDefaultCircle": "false",
                    "PriceSymbol": "", "PriceStart": 0, "PriceEnd": 0}
            r = self.f.post(API, data=data, headers={"X-Requested-With": "XMLHttpRequest",
                                                     "Referer": BASE + "/find/properties"})
            d = r.json()
            cards = CARD_RX.findall(d.get("ResultsHtml", ""))
            for path, label, addr in cards:
                if path in seen:
                    continue
                seen.add(path)
                label, addr = htmlmod.unescape(label).strip(), htmlmod.unescape(addr).strip()
                m = re.match(r"(.*?)\s+(For Sale or For Rent|For Rent|For Sale|Under Offer|Let|Sold)$", label)
                types, status = (m.group(1), m.group(2)) if m else (label, "")
                pc = ex.find_postcode(addr)
                if not pc:
                    oc = re.findall(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*$", addr.strip())
                    pc = oc[0] if oc else ""
                l = self.stub(BASE + path, title=addr, address=addr, postcode=pc, property_type=types,
                              marketing_status=status.replace("For Rent", "To Let"))
                if "industrial" not in types.lower():
                    l.excluded_reason = l.excluded_reason or f"Not industrial (type: {types})"
                out.append(l)
            if not d.get("HasMoreResults"):
                break
        return out

    def enrich(self, l):
        soup = self.soup(l.url)
        text = cut_related(self.main_text(soup))
        l.description = text
        title = soup.title.get_text() if soup.title else ""
        pc = ex.find_postcode(title) or ex.find_postcode(text[:1500])
        if pc:
            l.postcode = pc
        m = re.search(r"\|\s*Tenure:\s*\|\s*([^|]+)", text)
        if m:
            l.tenure = m.group(1).strip()
        m = re.search(r"\|\s*Types:\s*\|\s*([^|]+)", text)
        if m:
            l.property_type = m.group(1).strip()
        m = re.search(r"\|\s*Size:\s*\|\s*([^|]+)", text)
        if m:
            a, b = ex.parse_size_range(m.group(1))
            if b:
                l.min_sqft, l.max_sqft = a, b
        m = re.search(r"\|\s*EPC:\s*\|\s*([A-G]\+?|Exempt)\b", text, re.I)
        if m:
            l.epc = m.group(1)
        m = re.search(r"Get in touch \|(.{0,500}?)\| Email me direct \| To:", text)
        if m:
            l.agent_contacts = ex.clean(m.group(1).replace("| Email me direct", ";").replace("|", " "))
        emails = sorted(set(re.findall(r"[\w.]+@lsh\.co\.uk", str(soup))) - {"marketing@lsh.co.uk"})
        if emails:
            l.agent_contacts = (l.agent_contacts + "; " if l.agent_contacts else "") + ", ".join(emails)
        l.brochure_urls = [u for u in self.pdf_links(soup, l.url) if "agencypilot" in u or "lsh" in u]
