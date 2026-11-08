"""Commercial Property Partners – www.commercialpropertypartners.co.uk.
Searches Industrial (5) and Trade Counter (9) types; keeps NW postcodes."""
from __future__ import annotations

import re

from .. import extract as ex
from .base import AgentScraper

BASE = "https://www.commercialpropertypartners.co.uk"
NON_NW = re.compile(r"yorkshire|sheffield|rotherham|doncaster|barnsley|nottingham|derby|chesterfield|alfreton|"
                    r"mansfield|leicester|lincoln|worksop|ripley|ilkeston|newark|leeds|wakefield|bradford", re.I)
FIRST = BASE + "/property-search?property_type_id={t}&location="
PAGE = BASE + "/ev_property_residential_properties/search/page:{n}?property_type_id={t}&location="


class CPP(AgentScraper):
    name = "CPP (Commercial Property Partners)"
    website = "https://www.commercialpropertypartners.co.uk/"
    method = "Server-rendered search filtered to Industrial and Trade Counter (paginated) + detail pages"

    def discover(self):
        out, seen = [], set()
        for t, label in (("5", "Industrial"), ("9", "Trade Counter")):
            self.result.search_urls.append(FIRST.format(t=t))
            for n in range(1, 60):
                try:
                    soup = self.soup(FIRST.format(t=t) if n == 1 else PAGE.format(n=n, t=t))
                except Exception as e:
                    if n > 1 and "404" in str(e):
                        break
                    raise
                new = 0
                for a in soup.select("a[href^='/properties/']"):
                    href = BASE + a["href"]
                    if href in seen:
                        continue
                    card = a
                    for _ in range(6):
                        if card.parent is None:
                            break
                        card = card.parent
                        if "Size" in card.get_text() and "View Property" in card.get_text():
                            break
                    txt = ex.clean(card.get_text(" | "))
                    seen.add(href)
                    new += 1
                    pc = ex.find_postcode(txt)
                    parts = [p.strip() for p in txt.split("|") if p.strip()]
                    status = parts[0] if parts and parts[0] in ("To Let", "For Sale", "Under Offer", "To Let / For Sale", "For Sale / To Let") else ""
                    addr = next((p for p in parts if pc and pc.replace(" ", "") in p.replace(" ", "")), "")
                    l = self.stub(href, postcode=pc, title=addr or a.get_text(" ").strip(), address=addr,
                                  marketing_status=status, property_type=label)
                    m = re.search(r"Size:\s*\|?\s*([^|]+(?:\|\s*-\s*[^|]+)?)", txt)
                    if m:
                        l.min_sqft, l.max_sqft = ex.parse_size_range(m.group(1).replace("|", ""))
                    l.description = txt
                    if not pc and NON_NW.search(txt):
                        l.excluded_reason = "Outside North West coverage (location in listing text)"
                    if not l.address:
                        l.address = l.title
                    out.append(l)
                if not new:
                    break
        return out

    def enrich(self, l):
        self.generic_enrich(l)
