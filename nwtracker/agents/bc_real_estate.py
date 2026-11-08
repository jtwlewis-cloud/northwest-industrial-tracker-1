"""BC Real Estate – bcrealestate.co.uk ('North West' property-city archive, paginated)."""
from __future__ import annotations

from .. import extract as ex
from .base import AgentScraper

LIST = "https://bcrealestate.co.uk/property-city/north-west/{page}"


class BCRealEstate(AgentScraper):
    name = "BC Real Estate"
    website = "https://bcrealestate.co.uk/"
    method = "Server-rendered North West property archive (paginated) + detail pages"

    def discover(self):
        out, seen = [], set()
        self.result.search_urls = [LIST.format(page="")]
        for n in range(1, 60):
            try:
                soup = self.soup(LIST.format(page="" if n == 1 else f"page/{n}/"))
            except Exception:
                if n > 1:
                    break
                raise
            new = 0
            for art in soup.select("article"):
                a = art.select_one("h3.entry-title a, h2.entry-title a")
                if not a or a["href"] in seen:
                    continue
                seen.add(a["href"])
                new += 1
                vals = {}
                for mi in art.select(".meta-item"):
                    lab = mi.select_one(".meta-item-label")
                    val = mi.select_one(".meta-item-value")
                    if lab and val:
                        vals[ex.clean(lab.get_text())] = ex.clean(val.get_text(" "))
                title = ex.clean(a.get_text(" "))
                price = art.select_one(".price")
                l = self.stub(a["href"], title=title, address=title, postcode=ex.find_postcode(title),
                              property_type=vals.get("Type", ""), marketing_status=vals.get("Status", ""))
                area = vals.get("Area", "")
                l.min_sqft, l.max_sqft = ex.parse_size_range(area if "sq" in area else area + " sq ft")
                ptxt = ex.clean(price.get_text(" ")) if price else ""
                if ptxt and "call" not in ptxt.lower():
                    l.rent_text = ptxt
                desc = art.select_one(".property-description, .entry-summary, p")
                l.description = ex.clean(art.get_text(" | "))
                out.append(l)
            if not new:
                break
        return out

    def enrich(self, l):
        soup = self.generic_enrich(l, contact_exclude=("info@bcrealestate",))
        if not l.agent_contacts:
            l.agent_contacts = "BC Real Estate – 0161 636 9202; info@bcrealestate.co.uk (no individual agent named on listing)"
