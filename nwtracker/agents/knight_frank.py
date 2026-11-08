"""Knight Frank – www.knightfrank.co.uk.
Listings load from Knight Frank's search API inside the page; Playwright
opens the public UK industrial search pages (to let and for sale, stepping
through ';offset=' pages) and reads the data the page itself requests.
North West postcodes are kept."""
from __future__ import annotations

import html
import re

from bs4 import BeautifulSoup

from .. import config
from .. import extract as ex
from .base import AgentScraper

BASE = "https://www.knightfrank.co.uk"
SEARCH = BASE + "/properties/commercial/{kind}/united-kingdom/industrial/all-floor"


class KnightFrank(AgentScraper):
    name = "Knight Frank"
    website = "https://www.knightfrank.co.uk/commercial"
    method = "Playwright render of UK industrial search (to let + for sale, all pages); API data captured from the page"

    def fetch(self) -> list[tuple[str, dict]]:
        from playwright.sync_api import sync_playwright

        rows = []
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(user_agent=config.USER_AGENT)
                got = []
                page.on("response", lambda r: got.append(r) if "/properties/search" in r.url else None)
                for kind in ("to-let", "for-sale"):
                    url0 = SEARCH.format(kind=kind)
                    self.f.check_robots(url0)
                    self.result.search_urls.append(url0)
                    got.clear()
                    page.goto(url0, wait_until="networkidle", timeout=90_000)
                    page.wait_for_timeout(1000)
                    if not got:
                        raise RuntimeError(f"search data not received for {url0}")
                    seen_offsets = set()
                    for _ in range(200):
                        for resp in list(got):
                            d = resp.json()
                            if d.get("Offset") in seen_offsets:
                                continue
                            seen_offsets.add(d.get("Offset"))
                            rows += [(kind, x) for x in d.get("Properties") or []]
                            total = d.get("Total") or 0
                        got.clear()
                        if max(seen_offsets) + 48 >= total:
                            break
                        btn = page.locator('[data-selenium-id="propertySearch-pager-nextClick"]').first
                        if btn.count() == 0 or btn.get_attribute("data-disabled") == "true":
                            break
                        btn.scroll_into_view_if_needed()
                        btn.click()
                        page.wait_for_load_state("networkidle")
                        page.wait_for_timeout(int(max(self.f.delay, 1.0) * 1000))
                        if not got:  # page change served from cache – try once more
                            page.wait_for_timeout(2000)
                            if not got:
                                self.log.warning("no data after paging at offset %s", max(seen_offsets))
                                break
            finally:
                browser.close()
        return rows

    def discover(self):
        out, seen = [], set()
        for kind, p in self.fetch():
            num = p.get("Number")
            if not num or num in seen:
                continue
            seen.add(num)
            url = f"{BASE}/properties/commercial/{kind}/{p.get('Slug')}/{num}"
            addr = html.unescape(p.get("Address") or "")
            l = self.stub(url, title=addr.split(",")[0], address=addr, postcode=(p.get("Postcode") or "").upper(),
                          property_type=", ".join(t.get("Name", "") for t in p.get("PropertyTypes") or []),
                          marketing_status="To Let" if kind == "to-let" else "For Sale")
            l.lat, l.lng = p.get("Latitude"), p.get("Longitude")
            lo, hi = p.get("FloorAreaMin") or 0, p.get("FloorAreaMax") or 0
            if hi:
                l.min_sqft, l.max_sqft = float(lo or hi), float(hi)
            pr = p.get("Price") or {}
            ptxt = " ".join(x for x in [pr.get("PricePrefix"), pr.get("PriceMinFormatted"),
                                        "-" if pr.get("IsRange") else "", pr.get("PriceMaxFormatted") if pr.get("IsRange") else "",
                                        pr.get("Term"), pr.get("PriceSuffix")] if x)
            if kind == "for-sale":
                l.price_text = ex.clean(ptxt)
            else:
                l.rent_text = ex.clean(ptxt)
            feats = " | ".join(f.get("Name", "") for f in p.get("Features") or [])
            desc = BeautifulSoup(html.unescape(p.get("DetailedDescription") or ""), "lxml").get_text(" | ")
            l.description = ex.clean(" | ".join([p.get("ShortDescription") or "", feats, desc]))
            l.brochure_urls = [u for u in (p.get("BrochuresUrls") or []) if isinstance(u, str)]
            if p.get("SoldRented"):
                l.excluded_reason = f"Completed transaction ({p.get('SoldRentedLabel') or 'let/sold'})"
            if re.search(r"under offer", (p.get("SoldRentedLabel") or "") + " " + (p.get("ShortDescription") or ""), re.I):
                l.marketing_status = "Under Offer"
            if not l.postcode and not (l.lat and 52.9 < float(l.lat) < 55.3 and -3.7 < float(l.lng) < -1.8):
                l.excluded_reason = l.excluded_reason or "Outside North West coverage (map location)"
            out.append(l)
        return out

    def enrich(self, l):
        if not l.agent_contacts:
            l.agent_contacts = "Knight Frank (contact details shown on listing page)"
