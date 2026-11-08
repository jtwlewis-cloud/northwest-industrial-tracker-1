"""Williams Sillitoe – www.willsill.co.uk (Property Hive search, industrial type 111)."""
from __future__ import annotations

import re

from .. import extract as ex
from .base import AgentScraper

SEARCH = ("https://www.willsill.co.uk/property-search/{page}?address_keyword=&commercial_for_sale_to_rent="
          "to_rent_for_sale&commercial_property_type=111&department=commercial")


class WilliamsSillitoe(AgentScraper):
    name = "Williams Sillitoe"
    website = "https://www.willsill.co.uk/"
    method = "Server-rendered property search filtered to Industrial (paginated) + detail pages"

    def discover(self):
        out, seen = [], set()
        for n in range(1, 30):
            url = SEARCH.format(page="" if n == 1 else f"page/{n}/")
            self.result.search_urls.append(url) if n == 1 else None
            try:
                soup = self.soup(url)
            except Exception:
                if n > 1:
                    break
                raise
            cards = soup.select("li.property")
            new = 0
            for c in cards:
                a = c.select_one("h3.propertyTitle a") or c.select_one("a[href*='/property/']")
                if not a or a["href"] in seen:
                    continue
                seen.add(a["href"])
                new += 1
                title = ex.clean(a.get_text(" "))
                info = [ex.clean(li.get_text(" ")) for li in c.select("ul.propertyInfo li")]
                avail = ex.clean((c.select_one(".pavailab-planding") or c).get_text(" ")) if c.select_one(".pavailab-planding") else ""
                card_text = ex.clean(c.get_text(" | "))
                l = self.stub(a["href"], title=title, address=title, postcode=ex.find_postcode(title),
                              marketing_status=("Under Offer" if card_text.lower().startswith("under offer") else avail),
                              property_type=info[0] if info else "")
                l.min_sqft, l.max_sqft = ex.parse_size_range(" ".join(info))
                intro = c.select_one("p.intro")
                l.description = ex.clean(intro.get_text(" ")) if intro else ""
                money = info[-1] if len(info) > 2 else ""
                if money and money != "POA":
                    m = re.search(r"(\d+(?:\.\d+)?)\s*per sq\.? ?ft", money, re.I)
                    if m:
                        l.rent_psf, l.rent_text = float(m.group(1)), f"£{float(m.group(1)):.2f} psf"
                    elif re.search(r"per annum|pa\b|pcm", money, re.I):
                        l.rent_text = money
                    elif "sale" in avail.lower():
                        l.price_text = "£" + money.lstrip("£")
                    else:
                        l.rent_text = money
                out.append(l)
            if not new:
                break
        return out

    def enrich(self, l):
        self.generic_enrich(l, selector="body", contact_exclude=("info@willsill",))
        l.description = l.description.split("| Request a viewing")[0]
        m = re.search(r"arrange a viewing \|(.{0,300}?)\|\s*\"", l.raw.get("page_text", "") or "")
        soup_text = self.main_text(self.soup(l.url), "body") if not m else ""
        m = m or re.search(r"arrange a viewing \|(.{0,300}?)\|\s*\"", soup_text)
        if m:
            l.agent_contacts = ex.clean(m.group(1).replace("|", " "))
