"""Davies Harrison – www.daviesharrison.com (listing tiles on the home page + detail pages)."""
from __future__ import annotations

import re

from .. import extract as ex
from .base import AgentScraper

BASE = "https://www.daviesharrison.com"


class DaviesHarrison(AgentScraper):
    name = "Davies Harrison"
    website = "https://www.daviesharrison.com/"
    method = "Property tiles on home page (the site's full availability list) + detail pages"

    def discover(self):
        self.result.search_urls = [BASE + "/"]
        html = self.f.get(BASE + "/").text
        ids = list(dict.fromkeys(re.findall(r'href="/property/(\d+)"', html)))
        return [self.stub(f"{BASE}/property/{i}") for i in ids]

    def enrich(self, l):
        soup = self.soup(l.url)
        text = self.main_text(soup)
        text = text.split("| Interested in this property?")[0]
        parts = [p.strip() for p in text.split("|")]
        l.title = parts[0] if parts else ""
        l.address = ", ".join(parts[:2])
        l.town = ""  # located from the most specific address part (see base.finalise)
        m = re.search(r"Size:\s*([^|]+)", text)
        if m:
            l.min_sqft, l.max_sqft = ex.parse_size_range(m.group(1).replace("SQ.FT.", "sq ft"))
        l.description = text
        l.property_type = "Office" if re.search(r"\boffice (suite|building|accommodation to let)\b", l.title, re.I) \
            else "Industrial / warehouse"
        l.brochure_urls = [re.sub(r"^https?://daviesharrison\.com", BASE, u) for u in self.pdf_links(soup, l.url)]
        l.agent_contacts = self.contacts(soup.find("main") or soup)
        names = re.findall(r"\|\s*([A-Z][a-z]+ [A-Z][a-z]+)\s*\|\s*0\d{3,4} \d{3} \d{4}", text)
        if names:
            l.agent_contacts = ", ".join(dict.fromkeys(names)) + "; " + l.agent_contacts
        hint = " ".join(parts[:3])
        pc = ex.find_postcode(text)
        if pc:
            l.postcode = pc
        else:
            l.raw["geocode_hint"] = hint
        if re.search(r"\bunder offer\b", text, re.I):
            l.marketing_status = "Under Offer"
