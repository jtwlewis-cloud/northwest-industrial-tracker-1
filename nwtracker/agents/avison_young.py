"""Avison Young – www.avisonyoung.co.uk.

Listings are rendered client-side by the SharpLaunch widget. Playwright loads
the public industrial listings page and reads the JSON feed the page itself
requests (no headers are forged); detail pages are static HTML."""
from __future__ import annotations

import re

from .. import config
from .. import extract as ex
from .base import AgentScraper

PAGE = "https://www.avisonyoung.co.uk/industrial-properties"
FEED = "pse-api.sharplaunch.com/data"
EXCLUDE_TYPES = re.compile(r"^(Industrial\.(Industrial Land|Open Storage|Yard)|Land and Development\..*|Investment\..*)$")


class AvisonYoung(AgentScraper):
    name = "Avison Young"
    website = "https://www.avisonyoung.co.uk/properties"
    method = "Playwright render of listings page; JSON feed captured from the page's own request; static detail pages"

    def fetch_feed(self) -> list[dict]:
        from playwright.sync_api import sync_playwright

        self.f.check_robots(PAGE)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(user_agent=config.USER_AGENT)
                with page.expect_response(lambda r: FEED in r.url, timeout=90_000) as resp:
                    page.goto(PAGE, timeout=90_000)
                return resp.value.json().get("items", [])
            finally:
                browser.close()

    def discover(self):
        self.result.search_urls = [PAGE]
        items = self.fetch_feed()
        out = []
        for it in items:
            types = it.get("type") or []
            url = it.get("external_url") or f"https://www.avisonyoung.co.uk/properties/{it.get('slug')}"
            l = self.stub(url, postcode=(it.get("zip") or "").upper().strip(),
                          title=it.get("meta_title") or it.get("name") or "",
                          address=", ".join(x for x in [it.get("name"), it.get("zip")] if x),
                          town=it.get("city") or "",
                          property_type=", ".join(t.split(".", 1)[-1] for t in types))
            loc = it.get("location") or {}
            l.lat, l.lng = loc.get("lat"), loc.get("lng")
            l.total_sqft = ex.to_float(it.get("total_surface_sqft"))
            l.min_sqft = ex.to_float(it.get("availabilities_min_surface_sqft"))
            l.max_sqft = ex.to_float(it.get("availabilities_max_surface_sqft")) or l.total_sqft
            tr = it.get("transaction") or []
            l.marketing_status = " / ".join({"lease": "To Let", "sale": "For Sale", "sublease": "Sublease"}.get(t, t) for t in tr)
            if it.get("status") == "escrow":
                l.marketing_status = "Under Offer"
            lo, hi = it.get("availabilities_min_rent"), it.get("availabilities_max_rent")
            if lo or hi:
                lo = lo or hi
                l.rent_psf = float(lo)
                l.rent_text = f"£{float(lo):.2f} psf" if not hi or hi == lo else f"£{float(lo):.2f}–£{float(hi):.2f} psf"
            if it.get("sale_price"):
                l.price_text = f"£{int(float(it['sale_price'])):,}"
            l.description = ex.clean(it.get("meta_description") or it.get("description") or "")
            l.raw["ay_id"] = it.get("id")
            if not any(t.startswith("Industrial") for t in types):
                l.excluded_reason = l.excluded_reason or f"Not industrial (type: {l.property_type})"
            elif all(EXCLUDE_TYPES.match(t) for t in types):
                l.excluded_reason = l.excluded_reason or f"Land / open storage only (type: {l.property_type})"
            if not l.postcode and l.lat is None:
                l.excluded_reason = l.excluded_reason or "No location published"
            elif not l.postcode and not (52.9 < float(l.lat) < 55.3 and -3.7 < float(l.lng) < -1.8):
                l.excluded_reason = l.excluded_reason or "Outside North West coverage (map location)"
            out.append(l)
        return out

    def enrich(self, l):
        soup = self.generic_enrich(l, contact_exclude=("avisonyoung.com/privacy",))
        team = soup.find(id=re.compile("team", re.I)) or soup.find(string=re.compile(r"^\s*Team\s*$"))
        text = self.main_text(soup)
        m = re.search(r"\|\s*Team\s*\|(.{0,400}?)\|\s*your name", text, re.I)
        if m:
            l.agent_contacts = ex.clean(m.group(1).replace("[email protected]", "").replace("|", " ")) + \
                ("; " + l.agent_contacts if l.agent_contacts else "")
        l.brochure_urls = [u for u in l.brochure_urls if "sharplaunch" in u or "avisonyoung" in u]
