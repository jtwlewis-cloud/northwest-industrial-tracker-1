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
        r = self.f.get(API, headers={"Referer": SEARCH_PAGE, "X-Requested-With": "XMLHttpRequest"})
        try:
            props = r.json().get("properties", [])
        except ValueError:
            # the site's own search is returning an error page – re-check last run's listings directly
            if not self.known_urls:
                raise RuntimeError("cushwakeproperty.co.uk search returned an error page (site fault) and no "
                                   "previously known listings to re-check")
            self.result.errors.append("Search endpoint returned the site's error page (site fault); re-checked "
                                      f"{len(self.known_urls)} listings found last run instead – new C&W listings "
                                      "cannot be discovered until the site's search works again")
            out = []
            for u in self.known_urls:
                l = self.stub(u)
                l.raw["recheck_only"] = True
                out.append(l)
            return out
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
        resp = self.f.get(l.url)
        if "/error/" in resp.url:
            raise RuntimeError("cushwakeproperty.co.uk returned its error page (site fault)")
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "lxml")
        text = cut_related(self.main_text(soup, "body"))
        start = text.find("| Property type:")
        end = text.find("| Important notice")
        l.description = text[max(0, start): end if end > 0 else None]
        if l.raw.get("recheck_only"):
            if "Property type:" not in text:
                l.excluded_reason = "Listing page no longer available (withdrawn, let or sold)"
                return
            h1 = soup.find("h1")
            m = re.search(r"\|\s*([^|]+?)\s*\|\s*Property type:", text)
            head = text[:text.find("| Property type:")].split("|")
            parts = [x.strip() for x in head if x.strip()]
            if len(parts) >= 2:
                l.title, l.address = parts[-2], ", ".join(parts[-2:])
                l.postcode = ex.find_postcode(parts[-1])
            m = re.search(r"Property type:\s*\|\s*([^|]+)", text)
            l.property_type = m.group(1).strip() if m else "Industrial"
            m = re.search(r"\|\s*(To Let|For Sale|For Sale and To Let)\s*\|", text)
            l.marketing_status = m.group(1) if m else "To Let"
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
