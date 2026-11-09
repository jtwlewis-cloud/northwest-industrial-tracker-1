"""Cushman & Wakefield – cushwakeproperty.co.uk (C&W's UK agency listings site).

The site's search page loads results from its own JSON endpoint
(/api/map/search). Logistics & Industrial (type 2), to let and for sale,
all UK; North West locations are kept and detail pages read."""
from __future__ import annotations

import re

from .. import extract as ex
from .base import AgentScraper, cut_related

BASE = "https://cushwakeproperty.co.uk"
SEARCH_PAGE = (BASE + "/our-property/?sale=1&let=1&location=&lat=54.0&lon=-2.7&distance=9999&types=2"
               "&salestatuses=1%2C2%2C6&min=1&max=&unit=2&keywords=")
API = (BASE + "/api/map/search?sale=1&let=1&location=&lat=54.0&lon=-2.7&distance=9999&types=2"
       "&salestatuses=1%2C2%2C6&min=1&max=&unit=2&keywords=")


class Cushman(AgentScraper):
    name = "Cushman & Wakefield"
    website = BASE + "/"
    method = "cushwakeproperty.co.uk Logistics & Industrial search (site's JSON search endpoint) + detail pages"

    def discover(self):
        self.result.search_urls = [SEARCH_PAGE]
        props = self.f.get(API, headers={"Referer": SEARCH_PAGE, "X-Requested-With": "XMLHttpRequest"}).json().get("properties", [])
        out = []
        for p in props:
            addr = p.get("Address") or ""
            name = (p.get("Name") or "").strip()
            l = self.stub(f"{BASE}/our-property/{p.get('DetailsUrl')}", title=", ".join(x for x in [name, addr.split(",")[0]] if x),
                          address=", ".join(x for x in [name, addr] if x), postcode=ex.find_postcode(addr),
                          property_type=p.get("PropertyTypeName") or "Industrial")
            l.lat, l.lng = p.get("Latitude"), p.get("Longitude")
            l.min_sqft, l.max_sqft = ex.parse_size_range(p.get("Size") or "")
            st = p.get("SaleStatus") or ""
            l.marketing_status = "Under Offer" if "offer" in st.lower() else (p.get("SaleType") or "")
            price = p.get("GuidePrice") or ""
            if price and "application" not in price.lower():
                if "sale" in (p.get("SaleType") or "").lower() and "let" not in (p.get("SaleType") or "").lower():
                    l.price_text = price
                else:
                    l.rent_text = price
            elif price:
                l.rent_text = "On application"
            if re.search(r"\blet\b|\bsold\b", st, re.I) and "offer" not in st.lower():
                l.excluded_reason = f"Completed transaction (status '{st}')"
            out.append(l)
        return out

    def enrich(self, l):
        soup = self.soup(l.url)
        text = cut_related(self.main_text(soup, "body"))
        start = text.find("| Property type:")
        end = text.find("| Important notice")
        l.description = text[max(0, start): end if end > 0 else None]
        m = re.search(r"Size:\s*\|\s*([^|]+)", text)
        if m:
            a, b = ex.parse_size_range(m.group(1))
            if b:
                l.min_sqft, l.max_sqft = a, b
        m = re.search(r"Status:\s*\|\s*([^|]+)", text)
        if m and "offer" in m.group(1).lower():
            l.marketing_status = "Under Offer"
        emails = []
        for a in soup.find_all("a", href=True):
            h = a["href"]
            if h.lower().startswith("mailto:"):
                mm = re.match(r"mailto:([\w.+-]+@[\w.-]+)", h)
                if mm and mm.group(1) not in emails and "servicedesk" not in mm.group(1).lower():
                    emails.append(mm.group(1))
        phones = list(dict.fromkeys(a["href"][4:].strip() for a in soup.find_all("a", href=True)
                                    if a["href"].startswith("tel:") and "0203 296 2000" not in a["href"]))
        l.agent_contacts = "; ".join(emails + phones) or "Cushman & Wakefield – 0203 296 2000"
        l.brochure_urls = self.pdf_links(soup, l.url)
