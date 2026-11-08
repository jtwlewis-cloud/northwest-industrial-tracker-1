"""DTRE – dtre.com (server-rendered UK search, ~9 cards per page)."""
from __future__ import annotations

import re

from .. import extract as ex
from .base import AgentScraper, cut_related

SEARCH = "https://dtre.com/search/properties"


class DTRE(AgentScraper):
    name = "DTRE"
    website = "https://dtre.com/"
    method = "Server-rendered property search (all pages, NW postcodes kept) + detail pages"

    def discover(self):
        self.result.search_urls = [SEARCH]
        out, seen = [], set()
        last = 1
        n = 1
        while n <= last and n < 150:
            soup = self.soup(SEARCH + (f"?page={n}" if n > 1 else ""))
            pages = [int(x) for x in re.findall(r"\?page=(\d+)", str(soup))]
            if pages:
                last = max(last, max(pages))
            new = 0
            for c in soup.select("div.card"):
                a = c.select_one("a.card__link")
                if not a or a["href"] in seen:
                    continue
                seen.add(a["href"])
                new += 1
                g = lambda sel: ex.clean(c.select_one(sel).get_text(" ")) if c.select_one(sel) else ""
                town_pc = g(".card-body__town")
                pc = town_pc.rsplit(",", 1)[-1].strip() if "," in town_pc else ""
                tt = g(".card-body__type_tenure")
                typ = g(".card-body__type_tenure span")
                l = self.stub(a["href"], title=g(".card-body__title"), postcode=pc.upper(),
                              town=town_pc.rsplit(",", 1)[0].strip(), property_type=typ,
                              marketing_status=ex.clean(tt.replace(typ, "", 1)))
                l.min_sqft, l.max_sqft = ex.parse_size_range(g(".card-body__size"))
                price = ex.clean(" ".join(x.get_text(" ") for x in c.select("[class*=propText__price]")))
                if price and "POA" not in price:
                    l.rent_text = price if "sale" not in l.marketing_status.lower() else ""
                    l.price_text = price if "sale" in l.marketing_status.lower() else ""
                flag = ex.clean(c.get_text(" | "))
                if "Under Offer" in flag:
                    l.marketing_status = "Under Offer"
                if "Coming Soon" in flag:
                    l.notes.append("DTRE card tagged 'Coming Soon'")
                out.append(l)
            if not new and n > 1:
                break
            n += 1
        return out

    def enrich(self, l):
        soup = self.soup(l.url)
        text = cut_related(self.main_text(soup))
        i = text.find("| The Space")
        l.description = text[i:] if i >= 0 else text
        m = re.search(r"\|\s*([^|]*\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\s*\|\s*The Space", text)
        if m:
            l.postcode = ex.find_postcode(m.group(1)) or l.postcode
            l.address = ex.clean(f"{l.title}, {m.group(1)}")
        else:
            l.address = f"{l.title}, {l.town}, {l.postcode}"
        if "Coming Soon" in " ".join(l.notes) and "under construction" not in text.lower():
            l.description += " | Coming soon"
        ag = re.search(r"please contact our agents:\s*\|(.{0,500}?)(?:\|\s*Featured|$)", text, re.I)
        if ag:
            l.agent_contacts = ex.clean(ag.group(1).replace("| Contact agent", ";").replace("|", " "))
        l.brochure_urls = self.pdf_links(soup, l.url)
        m = re.search(r"Energy Performance Rating\s*\|([^|]*\|){0,3}", text)
        if m and "exempt" in m.group(0).lower():
            l.epc = "Exempt"
