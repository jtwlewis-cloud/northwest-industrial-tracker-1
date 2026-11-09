"""Indurent – www.indurent.com (landlord/developer, not an agency).

Its "Find your space" page loads every unit from a public JSON endpoint
(/wp-json/indurent/v1/get-units). That feed gives size, status, rent and
unit features; the unit page adds the published description. Indurent's own
status labels are mapped as: available -> Available Now, coming_soon ->
Available at a Future Date, under_development -> Under Construction (or
Proposed / D&B for build-to-suit plots), under_offer -> Under Offer."""
from __future__ import annotations

import html
import re

from .. import extract as ex
from .base import AgentScraper, cut_related

BASE = "https://www.indurent.com"
FEED = (BASE + "/wp-json/indurent/v1/get-units?lat=55.378051&lng=-3.435973&formatted_address=United+Kingdom"
        "&sqm=false&km=false&radius=400&min_space=0&max_space=99999999&min_price=0&max_price=99999999&include_vat=")
STATUS = {"available": "To Let (available)", "coming_soon": "To Let (coming soon)",
          "under_development": "To Let (under development)", "under_offer": "Under Offer"}


class Indurent(AgentScraper):
    name = "Indurent (landlord)"
    website = BASE + "/find-your-space/"
    method = "Public unit feed behind 'Find your space' (all UK units, NW kept) + unit pages"

    def discover(self):
        self.result.search_urls = [BASE + "/find-your-space/"]
        units = self.f.get(FEED).json().get("units", [])
        out = []
        for u in units:
            title = html.unescape(u.get("title") or "")
            estate = html.unescape(u.get("part_of_estate_name") or "")
            addr = ", ".join(x for x in [title, estate, html.unescape((u.get("address") or "").replace("\n", ", ")),
                                         u.get("city"), u.get("postcode")] if x)
            l = self.stub(u.get("link"), title=f"{title}, {estate}" if estate and estate not in title else title,
                          address=addr, postcode=(u.get("postcode") or "").upper().strip(), town=u.get("city") or "",
                          estate=estate, property_type="Industrial / warehouse (Indurent)",
                          unit_number=ex.unit_number(title))
            c = u.get("coordinates") or {}
            l.lat, l.lng = ex.to_float(c.get("lat")), ex.to_float(c.get("lng"))
            size = ex.to_float(u.get("size"))
            l.min_sqft = l.max_sqft = l.total_sqft = size
            st = u.get("availability_status") or ""
            l.marketing_status = STATUS.get(st, st)
            l.raw["indurent_status"] = st
            rent = ex.to_float(u.get("rent_pa"))
            if rent and not u.get("show_sale_price"):
                l.rent_text = f"£{rent:,.0f} pa"
                if size:
                    l.rent_psf = round(rent / size, 2)
                    l.notes.append("Rent £psf derived from Indurent's quoted annual rent ÷ published size")
            feats = " | ".join(f.get("name", "") for f in u.get("features") or [])
            l.description = feats
            l.agent_contacts = "Indurent (landlord) – enquiries@indurent.com; 0800 122 3330"
            if (u.get("region_name") or "") not in ("North West",) and not l.excluded_reason:
                pass  # postcode check in finalise decides; region is only a hint
            out.append(l)
        return out

    def enrich(self, l):
        soup = self.soup(l.url)
        text = cut_related(self.main_text(soup, "body"))
        start = text.find("Get Directions |")
        end = text.find("| Occupational costs")
        desc = text[start + len("Get Directions |"): end] if start >= 0 and end > start else ""
        l.description = ex.clean(" | ".join(x for x in [desc, l.description] if x))
        l.brochure_urls = [u for u in self.pdf_links(soup, l.url) if "vault.industrials.co.uk" in u]
        st = l.raw.get("indurent_status")
        t = (l.title + " " + l.description).lower()
        if st == "available":
            l.description += " | Available now (Indurent status: available)"
        elif st == "coming_soon":
            l.notes.append("Indurent status: coming soon (date not published)")
        elif st == "under_development":
            if re.search(r"build[\s-]to[\s-]suit|design (?:&|and) build|plot", t):
                l.build_status = "Design & Build"
            else:
                l.build_status = "New Build"
                l.description += " | Under construction (Indurent status: under development)"

    def finalise(self, l):
        super().finalise(l)
        if l.excluded_reason:
            return
        st = l.raw.get("indurent_status")
        if st == "coming_soon" and l.availability_status in ("Availability Unconfirmed", "Available Now"):
            l.availability_status = "Available at a Future Date"
        elif st == "under_development" and l.build_status == "New Build":
            l.availability_status = "Under Construction"
