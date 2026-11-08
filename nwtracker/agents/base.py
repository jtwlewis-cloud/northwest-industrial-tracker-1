"""Shared scraper framework. Each agent module subclasses AgentScraper and
implements discover(); everything else (location filtering, classification,
brochure enrichment, error capture) is common so one failing site never stops
the others."""
from __future__ import annotations

import json
import logging
import re
import time
import traceback
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .. import config
from .. import extract as ex
from ..geo import Geo, is_candidate_nw
from ..http import AccessBlocked, Fetcher, RobotsDisallowed
from ..models import Listing
from ..pdf import brochure_text

INDUSTRIAL_RX = re.compile(
    r"industrial|warehous|logistic|distribution|manufactur|production|trade[\s-]?counter|workshop|"
    r"\bb2\b|\bb8\b|storage|depot|factory|light industrial|design (?:&|and) build|hybrid|"
    r"business unit|trade unit|industrial/warehouse|mill", re.I)
NON_INDUSTRIAL_TYPES = re.compile(
    r"^(?:office|offices|serviced office|retail|leisure|restaurant|residential|hotel|pub|bar|"
    r"land|development land|investment|medical|healthcare|education|student|shop|showroom only)$", re.I)
DOC_EXCLUDE = re.compile(r"complaint|privacy|cookie|terms|policy|aml|money-laundering|modern-slavery|"
                         r"gdpr|accessib|fee|tariff|client-money|cmp|disclaimer|misdescription", re.I)


@dataclass
class AgentResult:
    agent: str
    website: str
    status: str = "Not run"           # Success / Partial / Failed / Blocked
    method: str = ""
    search_urls: list[str] = field(default_factory=list)
    listings_scanned: int = 0
    candidates: int = 0
    included: list[Listing] = field(default_factory=list)
    excluded: list[Listing] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    brochures_read: int = 0
    brochure_errors: int = 0
    duration_s: float = 0.0
    message: str = ""


class AgentScraper:
    name = "Agent"
    website = ""
    method = ""
    max_detail_errors = 25

    def __init__(self, fetcher: Fetcher, geo: Geo, read_brochures: bool = True, log=None):
        self.f = fetcher
        self.geo = geo
        self.read_brochures = read_brochures
        self.log = log or logging.getLogger(f"agent.{self.name}")
        self.result = AgentResult(self.name, self.website, method=self.method)

    # -------------------------------------------------------------- helpers
    def soup(self, url: str, **kw) -> BeautifulSoup:
        return BeautifulSoup(self.f.get(url, **kw).text, "lxml")

    @staticmethod
    def main_text(soup: BeautifulSoup, selector: str | None = None) -> str:
        root = soup.select_one(selector) if selector else None
        root = root or soup.find("main") or soup.body or soup
        root = BeautifulSoup(str(root), "lxml")
        for t in root(["script", "style", "noscript", "nav", "header", "footer", "form", "svg", "iframe"]):
            t.decompose()
        return ex.clean(root.get_text(" | ", strip=True))

    @staticmethod
    def pdf_links(soup: BeautifulSoup, base: str) -> list[str]:
        out = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if ".pdf" not in href.lower() and "brochure" not in (a.get_text() or "").lower():
                continue
            if ".pdf" not in href.lower():
                continue
            full = urljoin(base, href)
            if DOC_EXCLUDE.search(full) or DOC_EXCLUDE.search(a.get_text() or ""):
                continue
            if full not in out:
                out.append(full)
        return out

    @staticmethod
    def decode_cfemail(enc: str) -> str:
        try:
            key = int(enc[:2], 16)
            return "".join(chr(int(enc[i:i + 2], 16) ^ key) for i in range(2, len(enc), 2))
        except ValueError:
            return ""

    def contacts(self, soup: BeautifulSoup, extra_exclude: tuple = ()) -> str:
        emails, phones = [], []
        for a in soup.find_all("a", href=True):
            h = a["href"]
            if h.startswith("mailto:"):
                e = h[7:].split("?")[0].strip()
            elif "/cdn-cgi/l/email-protection#" in h:
                e = self.decode_cfemail(h.split("#", 1)[1])
            else:
                e = ""
            if e and e.lower() not in emails and not any(x in e.lower() for x in extra_exclude):
                emails.append(e.lower())
            if h.startswith("tel:"):
                p = re.sub(r"\s+", " ", h[4:]).strip()
                if p and p not in phones:
                    phones.append(p)
        for sp in soup.select("[data-cfemail]"):
            e = self.decode_cfemail(sp["data-cfemail"]).lower()
            if e and e not in emails:
                emails.append(e)
        return "; ".join(emails + phones)

    # ----------------------------------------------------------- pipeline
    def discover(self) -> list[Listing]:
        """Return listing stubs (agent-specific). Must be implemented."""
        raise NotImplementedError

    def enrich(self, listing: Listing) -> None:
        """Fetch the detail page and fill fields (agent-specific; optional)."""

    def generic_enrich(self, l: Listing, selector: str | None = None, contact_exclude: tuple = ()) -> BeautifulSoup:
        """Fetch a static detail page and fill description, brochures, contacts,
        postcode and size where the listing card did not provide them."""
        soup = self.soup(l.url)
        text = cut_related(self.main_text(soup, selector))
        l.description = (l.description + " | " + text).strip(" |") if l.description else text
        for u in self.pdf_links(soup, l.url):
            if u not in l.brochure_urls:
                l.brochure_urls.append(u)
        if not l.agent_contacts:
            l.agent_contacts = self.contacts(BeautifulSoup(str((soup.select_one(selector) if selector else None) or soup.find("main") or soup.body), "lxml"), contact_exclude)
        if not l.postcode or " " not in l.postcode:
            pc = ex.find_postcode(l.address) or ex.find_postcode(text[:3000])
            if pc:
                l.postcode = pc
        if not l.max_sqft:
            l.min_sqft, l.max_sqft = ex.parse_size_range(text)
        return soup

    def is_industrial(self, listing: Listing) -> tuple[bool, str]:
        types = [t.strip() for t in re.split(r"[,/|;]", listing.property_type or "") if t.strip()]
        text = " ".join([listing.property_type, listing.title, listing.description[:600]])
        if types and all(NON_INDUSTRIAL_TYPES.match(t) for t in types):
            if not INDUSTRIAL_RX.search(listing.title + " " + listing.description[:300]):
                return False, f"Not industrial (type: {listing.property_type})"
        if not INDUSTRIAL_RX.search(text):
            return False, f"Not industrial (type: {listing.property_type or 'not stated'})"
        return True, ""

    def is_land_only(self, listing: Listing) -> bool:
        t = (listing.property_type + " " + listing.title).lower()
        land = re.search(r"\bland\b|open storage|\byard\b|plot|site", t)
        building = re.search(r"warehouse|unit|building|industrial premises|factory|workshop|depot|design (?:&|and) build|logistics|distribution centre", t + " " + listing.description[:400].lower())
        return bool(land) and not building and not listing.max_sqft

    def finalise(self, l: Listing) -> None:
        """Location, classification and status for one listing (in place)."""
        town_located = False
        if not l.postcode and l.lat is None:
            segs = [x.strip() for x in l.address.split(",")][1:] + [l.town]
            for cand in segs:
                cand = re.sub(r"\b(?:road|lane|way|street|avenue|drive|close|crescent)\b.*", "", cand or "", flags=re.I).strip()
                pl = self.geo.place(cand) if cand and len(cand) > 2 else None
                if pl and pl.get("lat"):
                    l.lat, l.lng = pl["lat"], pl["lng"]
                    l.notes.append(f"No postcode published – located from town name '{cand}' (check)")
                    l.town = l.town or pl.get("name") or cand
                    town_located = True
                    break
        geo = self.geo.resolve(l.postcode, l.lat, l.lng)
        if "ambiguous" in geo.get("method", ""):
            town = l.town or (l.address.split(",")[-2] if l.address.count(",") >= 1 else "")
            pl = self.geo.place(re.sub(r"\d.*", "", town).strip()) if town else None
            if pl and pl.get("lat"):
                g2 = self.geo.resolve("", pl["lat"], pl["lng"])
                if g2.get("local_authority") and g2["local_authority"] in geo.get("local_authority", ""):
                    geo.update(county=g2["county"], local_authority=g2["local_authority"],
                               note=f"Partial postcode {l.postcode}; local authority taken from town '{town.strip()}'")
                    from .. import config as _c
                    geo["submarket"] = _c.SUBMARKET_OVERRIDES.get(ex.outcode(l.postcode)) or g2["local_authority"]
        l.county = geo.get("county", "")
        l.local_authority = geo.get("local_authority", "")
        l.submarket = geo.get("submarket", "")
        if geo.get("note") and not town_located:
            l.notes.append(geo["note"])
        if not l.postcode and geo.get("derived_postcode_district") and not town_located:
            l.notes.append(f"No postcode published; nearest postcode district {geo['derived_postcode_district']}")
        if l.county not in config.COUNTIES:
            l.excluded_reason = f"Outside North West coverage ({l.local_authority or l.county or 'location not identified'})"
            return
        ok, why = self.is_industrial(l)
        if not ok:
            l.excluded_reason = why
            return
        if self.is_land_only(l):
            l.excluded_reason = "Land / open storage without a building or design-and-build proposal"
            return
        full = " ".join([l.title, l.description, l.specification, l.marketing_status])
        ex.apply_text(l, full, "web")
        flags = ex.marketing_flags(full)
        ms = l.marketing_status.lower()
        if re.search(r"\b(?:let|sold|completed|withdrawn)\b", ms) and "let agreed" not in ms and "to let" not in ms and "for sale" not in ms and "/" not in ms:
            l.excluded_reason = f"Completed transaction (marketing status '{l.marketing_status}')"
            return
        if flags["investment"] and not re.search(r"to let|vacant|available|owner[\s-]occupi|for occupation", (ms + " " + full).lower()):
            l.excluded_reason = "Investment sale without occupier availability"
            return
        if not l.build_status:
            l.build_status = ex.build_status(full)
        l.availability_status, conf = ex.classify_availability(l.marketing_status, full, l.availability_date, l.build_status)
        l.conflicts.extend(conf)
        if not l.unit_number:
            l.unit_number = ex.unit_number(l.title) or ex.unit_number(l.address.split(",")[0])
        if not l.estate:
            l.estate = ex.estate_name(l.address or l.title)
        if not l.property_name:
            l.property_name = l.title
        if l.min_sqft and l.max_sqft and l.min_sqft > l.max_sqft:
            l.min_sqft, l.max_sqft = l.max_sqft, l.min_sqft
        if l.max_sqft and not l.total_sqft:
            l.total_sqft = l.max_sqft
        if l.total_sqft and not l.max_sqft:
            l.max_sqft = l.total_sqft
        if l.max_sqft and not l.min_sqft:
            l.min_sqft = l.max_sqft
        if "web" not in l.sources:
            l.sources.insert(0, "web")

    def read_brochure(self, l: Listing) -> None:
        for url in l.brochure_urls[:2]:
            try:
                text = brochure_text(self.f, url)
            except (RobotsDisallowed, AccessBlocked) as e:
                l.notes.append(f"Brochure not read: {e}")
                return
            except Exception as e:
                self.result.brochure_errors += 1
                self.log.info("brochure failed %s: %s", url, e)
                continue
            if text.strip():
                self.result.brochures_read += 1
                before = l.availability_status
                ex.apply_text(l, text, "brochure")
                bflags = ex.marketing_flags(text)
                if bflags["under_offer"] and before != "Under Offer":
                    l.conflicts.append("Brochure text mentions under offer / let agreed – check")
                if l.availability_status == "Availability Unconfirmed":
                    full = " ".join([l.title, l.description, text])
                    if not l.build_status or l.build_status == "Existing":
                        l.build_status = ex.build_status(" ".join([l.title, l.description, text[:4000]]))
                    st, _ = ex.classify_availability(l.marketing_status, full, l.availability_date, l.build_status)
                    if st != "Under Offer" and st != before:
                        l.availability_status = st
                        l.notes.append(f"Availability status from brochure: {st}")
                return
            l.notes.append("Brochure PDF contains no extractable text (image-only)")

    def run(self) -> AgentResult:
        t0 = time.time()
        r = self.result
        try:
            stubs = self.discover()
            r.listings_scanned = len(stubs)
            cands = [s for s in stubs if not s.excluded_reason]
            for s in stubs:
                if s.excluded_reason:
                    r.excluded.append(s)
            r.candidates = len(cands)
            detail_errors = 0
            for l in cands:
                try:
                    self.enrich(l)
                    self.finalise(l)
                except (AccessBlocked, RobotsDisallowed):
                    raise
                except Exception as e:
                    detail_errors += 1
                    r.errors.append(f"{l.url}: {type(e).__name__}: {e}")
                    self.log.warning("detail failed %s: %s", l.url, e)
                    l.excluded_reason = l.excluded_reason or f"Detail page could not be processed ({type(e).__name__})"
                    if detail_errors > self.max_detail_errors:
                        raise RuntimeError("too many detail-page failures") from e
                (r.excluded if l.excluded_reason else r.included).append(l)
            if self.read_brochures:
                for l in r.included:
                    try:
                        self.read_brochure(l)
                    except Exception as e:  # never fail the agent on a brochure
                        r.brochure_errors += 1
                        self.log.info("brochure error %s", e)
            for l in r.included:
                l.raw.setdefault("verified", date.today().isoformat())
            r.status = "Partial" if r.errors else "Success"
            r.message = (f"{len(r.included)} NW industrial listings from {r.listings_scanned} scanned"
                         + (f"; {len(r.errors)} page errors" if r.errors else ""))
        except AccessBlocked as e:
            r.status = "Blocked"
            r.message = f"Website blocked automated access – not bypassed: {e}"
            r.errors.append(str(e))
        except RobotsDisallowed as e:
            r.status = "Blocked"
            r.message = f"robots.txt disallows the required pages: {e}"
            r.errors.append(str(e))
        except Exception as e:
            r.status = "Failed" if not r.included else "Partial"
            r.message = f"{type(e).__name__}: {e}"
            r.errors.append(traceback.format_exc(limit=3))
            self.log.exception("agent failed")
        r.duration_s = round(time.time() - t0, 1)
        return r

    # convenience for subclasses
    def stub(self, url: str, **kw) -> Listing:
        l = Listing(agent=self.name, url=url, **kw)
        if l.postcode and not is_candidate_nw(l.postcode):
            l.excluded_reason = f"Outside North West coverage (postcode {l.postcode})"
        return l


RELATED_MARKERS = re.compile(
    r"\|\s*(?:featured properties|other properties you may be interested in|similar properties|"
    r"you may also (?:be interested|like)|related properties|recently viewed|more properties|"
    r"latest properties|nearby properties)\b", re.I)


def cut_related(text: str) -> str:
    """Drop 'other properties' panels so their specs are never attributed here."""
    m = RELATED_MARKERS.search(text)
    return text[: m.start()] if m else text


def next_data(html: str) -> dict:
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(m.group(1)) if m else {}
