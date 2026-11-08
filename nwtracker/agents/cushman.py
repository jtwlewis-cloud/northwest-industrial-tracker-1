"""Cushman & Wakefield – www.cushmanwakefield.com (UK property search).

The UK lease and sale/investment search pages are server-rendered; property
URLs encode type/county/town, e.g.
/en/united-kingdom/properties/for-sale/industrial/<county>/<town>/<estate>/<slug>."""
from __future__ import annotations

import re

from .. import extract as ex
from .base import AgentScraper

BASE = "https://www.cushmanwakefield.com"
SEARCHES = [BASE + "/en/united-kingdom/properties/lease/search",
            BASE + "/en/united-kingdom/properties/invest/search"]
LINK_RX = re.compile(r'href="(/en/united-kingdom/properties/(for-lease|for-sale)/([^/"]+)/([^/"]+)/([^/"]+)/[^"]+)"')
NW_WORDS = re.compile(r"manchester|merseyside|liverpool|cheshire|lancashire|cumbria|warrington|wigan|bolton|"
                      r"stockport|salford|trafford|oldham|rochdale|bury|preston|blackburn|burnley|carlisle|"
                      r"crewe|chester|runcorn|widnes|st-helens|knowsley|wirral|halton|lancaster|blackpool|"
                      r"north-west|kendal|barrow|skelmersdale|haydock|ellesmere|northwich|macclesfield", re.I)


class Cushman(AgentScraper):
    name = "Cushman & Wakefield"
    website = "https://www.cushmanwakefield.com/en/united-kingdom/properties"
    method = "Server-rendered UK lease + sale search pages (paginated) and detail pages"

    def discover(self):
        out, seen = [], set()
        for base in SEARCHES:
            self.result.search_urls.append(base)
            for page in range(1, 40):
                html = self.f.get(f"{base}?page={page}").text
                m = re.search(r"Search ([\d,]+) properties", html)
                if page == 1 and m:
                    self.log.info("%s reports %s properties", base, m.group(1))
                links = LINK_RX.findall(html)
                new = [x for x in links if x[0] not in seen]
                if not new:
                    break
                for path, kind, ptype, county, town in new:
                    seen.add(path)
                    l = self.stub(BASE + path, property_type=ptype.replace("-", " "),
                                  marketing_status="To Let" if kind == "for-lease" else "For Sale")
                    l.raw["county_slug"], l.raw["town_slug"] = county, town
                    if not re.search(r"industrial|logistic|warehouse|distribution", ptype, re.I):
                        l.excluded_reason = f"Not industrial (type: {ptype})"
                    elif not NW_WORDS.search(county + " " + town):
                        l.excluded_reason = f"Outside North West coverage ({county.replace('-', ' ').title()})"
                    out.append(l)
        return out

    def enrich(self, l):
        soup = self.generic_enrich(l)
        h1 = soup.find("h1")
        l.title = ex.clean(h1.get_text(" ")) if h1 else l.url.rsplit("/", 1)[-1]
        l.address = l.title
