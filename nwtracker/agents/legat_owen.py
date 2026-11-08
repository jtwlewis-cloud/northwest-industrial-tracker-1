"""Legat Owen – legatowen.co.uk (industrial property type filter, paginated)."""
from __future__ import annotations

from bs4 import BeautifulSoup

from .. import extract as ex
from .base import AgentScraper, cut_related

LIST = "https://legatowen.co.uk/properties/{page}?property_taxonomy%5Bproperty_type%5D%5B%5D=industrial"


class LegatOwen(AgentScraper):
    name = "Legat Owen"
    website = "https://legatowen.co.uk/"
    method = "Server-rendered property search filtered to Industrial (paginated) + detail pages"

    def discover(self):
        out, seen = [], set()
        self.result.search_urls = [LIST.format(page="")]
        for n in range(1, 80):
            soup = self.soup(LIST.format(page="" if n == 1 else f"page/{n}/"))
            new = 0
            for card in soup.select("div.property-list"):
                a = card.find_parent("a", href=True) or card.select_one("a[href*='/property/']")
                if a is None:
                    par = card.parent
                    a = par.select_one("a[href*='/property/']") if par else None
                if not a or a["href"] in seen:
                    continue
                seen.add(a["href"])
                new += 1
                g = lambda sel: ex.clean(card.select_one(sel).get_text(" ")) if card.select_one(sel) else ""
                loc = g("p.location")
                pc = loc.rsplit(",", 1)[-1].strip() if "," in loc else ""
                l = self.stub(a["href"].strip(), title=g("h3"), postcode=pc.upper(),
                              town=loc.rsplit(",", 1)[0].strip(), marketing_status=g(".property-cat"),
                              property_type="Industrial")
                l.address = f"{l.title}, {loc}"
                l.min_sqft, l.max_sqft = ex.parse_size_range(g("p.footage") + " sq ft")
                out.append(l)
            if not new:
                break
        return out

    def enrich(self, l):
        soup = self.soup(l.url)
        body = BeautifulSoup(str(soup.body), "lxml")
        text = cut_related(self.main_text(body, "body"))
        i = text.find("| Overview")
        l.description = text[i:] if i >= 0 else text
        head = text[:600]
        if "Under Offer" in head:
            l.marketing_status = "Under Offer"
        rest = text.split("Download Brochure")
        if len(rest) > 2:
            l.agent_contacts = ex.clean(rest[-2].split("Request Call Back")[0].replace("|", " "))
        l.brochure_urls = [u.strip() for u in self.pdf_links(soup, l.url) if "agencypilot" in u or "uploads" in u]
        pc = ex.find_postcode(head)
        if pc:
            l.postcode = pc
