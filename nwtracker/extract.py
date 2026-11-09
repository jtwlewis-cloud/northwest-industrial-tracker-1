"""Rule-based extraction of building specification and marketing terms from
listing / brochure text.

Every rule only fires on an explicit statement in the source text; nothing is
estimated. Where a value is not stated the field is left blank (shown as
"Not Disclosed" in the workbook)."""
from __future__ import annotations

import re

from .models import Listing

WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
           "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "a single": 1, "single": 1}
NUM = r"(\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|a single|single)"
MONTHS = r"(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
SQFT = r"(?:sq\.?\s?ft\.?|sqft|ft²|ft2|square feet|sf\b)"

POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b", re.I)
OUTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\b")


def _n(s: str) -> int:
    s = s.lower().strip()
    return WORDNUM.get(s) or int(s)


def to_float(s) -> float | None:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s) if s else None
    m = re.search(r"\d[\d,]*(?:\.\d+)?", str(s))
    if not m:
        return None
    try:
        v = float(m.group(0).replace(",", ""))
        return v or None
    except ValueError:
        return None


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def find_postcode(text: str) -> str:
    """Return the last full UK postcode in text (addresses end with it)."""
    found = POSTCODE_RE.findall(text or "")
    if not found:
        return ""
    out, inc = found[-1]
    return f"{out.upper()} {inc.upper()}"


def postcode_area(pc: str) -> str:
    m = re.match(r"([A-Z]{1,2})", (pc or "").upper().strip())
    return m.group(1) if m else ""


def outcode(pc: str) -> str:
    pc = (pc or "").upper().strip()
    if " " in pc:
        return pc.split()[0]
    m = re.match(r"^([A-Z]{1,2}\d[A-Z\d]?)(\d[A-Z]{2})?$", pc.replace(" ", ""))
    if m and m.group(2):
        return m.group(1)
    return pc


# ---------------------------------------------------------------- sizes
def parse_size_range(text: str) -> tuple[float | None, float | None]:
    """'2,924 - 4,769 sq ft' -> (2924, 4769); '45,351 sq ft' -> (45351, 45351)."""
    t = clean(text)
    m = re.search(r"([\d,]{3,}(?:\.\d+)?)\s*(?:" + SQFT + r")?\s*(?:-|–|—|to)\s*([\d,]{3,}(?:\.\d+)?)\s*" + SQFT, t, re.I)
    if m:
        a, b = to_float(m.group(1)), to_float(m.group(2))
        if a and b:
            return (min(a, b), max(a, b))
    m = re.search(r"([\d,]{3,}(?:\.\d+)?)\s*" + SQFT, t, re.I)
    if m:
        v = to_float(m.group(1))
        return (v, v)
    return (None, None)


# ---------------------------------------------------------------- specs
def eaves(text: str) -> float | None:
    t = clean(text)
    pats = [
        r"eaves(?:\s+height)?s?\s*(?:of|to|:|-|–|up to|rising to|is|are)?\s*(?:a\s+)?(?:minimum\s+(?:of\s+)?|min\.?\s*|approx\.?\s*|approximately\s+|c\.?\s*|circa\s+|up to\s+)?(\d{1,2}(?:\.\d{1,2})?)\s*(m\b|metres?|meters?|mtrs?|ft\b|feet|')",
        r"(\d{1,2}(?:\.\d{1,2})?)\s*(m\b|metres?|meters?|mtrs?|ft\b|feet|')\s*(?:\([^)]{0,20}\)\s*)?(?:minimum\s+|min\.?\s*|clear\s+|internal\s+|to\s+)?(?:eaves|haunch|clear (?:internal )?height|underside of haunch)",
        r"(\d{1,2}(?:\.\d{1,2})?)\s*(m\b|metres?|meters?)\s*(?:to\s+)?(?:the\s+)?underside of (?:the\s+)?(?:haunch|portal frame|steel)",
        r"(?:clear internal height|clear height|height to haunch|haunch height|working height)\s*(?:of|:)?\s*(\d{1,2}(?:\.\d{1,2})?)\s*(m\b|metres?|meters?|ft\b|feet)",
    ]
    for p in pats:
        m = re.search(p, t, re.I)
        if m:
            v = float(m.group(1))
            unit = m.group(2).lower()
            if unit.startswith("f") or unit == "'":
                v = round(v * 0.3048, 1)
            if 2.5 <= v <= 45:
                return v
    return None


def dock_doors(text: str) -> int | None:
    t = clean(text)
    m = re.search(NUM + r"\s*(?:x\s*|no\.?\s*)?(?:dock(?:[\s-]*level(?:ler)?)?|loading dock)s?\b(?:\s+(?:loading|access|leveller|level))*\s*(?:doors?|bays?|levell?ers?|loading|and\b|,|\()?", t, re.I)
    if m:
        return _n(m.group(1))
    m = re.search(r"dock(?:[\s-]*level(?:l?ers?)?)?\s*(?:loading\s*)?(?:doors?)?\s*[:x(\-–]\s*(\d{1,3})\b", t, re.I)
    if m:
        return int(m.group(1))
    return None


def level_doors(text: str) -> int | None:
    t = clean(text)
    m = re.search(NUM + r"\s*(?:x\s*|no\.?\s*)?(?:(?:electric(?:ally|al)?|electronic(?:ally)?|manual(?:ly)?|operated|roller|shutter|full[\s-]height|large|new)\s+)*(?:level[\s-]*access|ground[\s-]*level|surface[\s-]*level|drive[\s-]*in|level)\s+(?:electric(?:ally operated)?\s+|electronic\s+|roller\s+shutter\s+|loading\s+|access\s+)*(?:doors?|shutters?|loading)", t, re.I)
    if m:
        return _n(m.group(1))
    m = re.search(r"level[\s-]*access\s*(?:loading\s*)?(?:doors?)?\s*[:x(\-–]\s*(\d{1,3})\b", t, re.I)
    if m:
        return int(m.group(1))
    return None


def yard_depth(text: str) -> float | None:
    t = clean(text)
    for p in (r"yard depths?\s*(?:of|:|up to|-|–)?\s*(?:up to)?\s*(?:approx\.?\s*|c\.?\s*|circa\s*)?(\d{1,3}(?:\.\d)?)\s*m",
              r"(\d{1,3}(?:\.\d)?)\s*m(?:etres?|eters?)?\s*(?:deep\s+)?(?:service\s+|secure\s+|loading\s+|shared\s+)?yard(?:\s+depth)?\b(?!\s*area)",
              r"yards?\s+(?:of\s+)?(?:up to\s+)?(\d{1,3}(?:\.\d)?)\s*m(?:etres?)?\s*(?:deep|depth)"):
        m = re.search(p, t, re.I)
        if m:
            v = float(m.group(1))
            if 5 <= v <= 150:
                return v
    return None


def site_acres(text: str) -> float | None:
    t = clean(text)
    pats = [
        (r"(\d{1,4}(?:\.\d{1,3})?)\s*(?:hectares|ha)\s*\((?:approx\.?\s*|c\.?\s*)?(\d{1,4}(?:\.\d{1,3})?)\s*acres?\)", None),
        (r"site(?:\s+area)?\s*(?:of|extending to|extends to|totalling|totals|comprising|measuring|:)?\s*(?:approximately|approx\.?|circa|c\.?|about)?\s*(\d{1,4}(?:\.\d{1,3})?)\s*acres?", 1.0),
        (r"(\d{1,4}(?:\.\d{1,3})?)\s*acres?\s*(?:\([^)]{0,30}\)\s*)?(?:self[\s-]contained\s+|secure\s+|level\s+|development\s+)?site", 1.0),
        (r"site(?:\s+area)?\s*(?:of|extending to|extends to|:)?\s*(?:approximately|approx\.?|circa|c\.?)?\s*(\d{1,4}(?:\.\d{1,3})?)\s*(?:hectares|ha)\b", 2.47105),
        (r"(\d{1,4}(?:\.\d{1,3})?)\s*(?:hectares|ha)\s*\((\d{1,4}(?:\.\d{1,3})?)\s*acres?\)", None),
    ]
    for p, factor in pats:
        m = re.search(p, t, re.I)
        if m:
            if factor is None:
                return float(m.group(2))
            v = round(float(m.group(1)) * factor, 2)
            if 0.01 <= v <= 1000:
                return v
    return None


def power(text: str) -> str:
    t = clean(text)
    m = re.search(r"(\d[\d,.]*\s*(?:kva|mva|kw|mw))\b(?:[^.]{0,40}?(?:power|supply|electric|capacity|substation))?", t, re.I)
    if m:
        ctx = t[max(0, m.start() - 60): m.end() + 60].lower()
        if any(w in ctx for w in ("power", "supply", "electric", "capacity", "substation", "kva", "mva")):
            val = re.sub(r"\s+", " ", m.group(1))
            val = re.sub(r"(?i)kva", "kVA", val)
            val = re.sub(r"(?i)mva", "MVA", val)
            return val
    m = re.search(r"(three|3)[\s-]phase", t, re.I)
    if m:
        return "Three-phase (capacity not stated)"
    return ""


def epc(text: str) -> str:
    t = clean(text)
    m = re.search(r"\bEPC\b[^A-Za-z0-9]{0,3}(?:rating|band)?\s*(?:of|is|:|-|–)?\s*(?:target(?:ing|ed)?\s*)?\b([A-G]\+?)(?:\s*[-–(]?\s*\d{1,3}\)?)?(?![A-Za-z])", t)
    if m:
        return m.group(1)
    m = re.search(r"(?:energy performance (?:certificate|asset) rating|energy rating|EPC rating|EPC)\s*(?:of|is|:|-|–)?\s*(?:an?\s+)?([A-G]\+?)(?:[\s-]*\d{1,3})?\b", t, re.I)
    if m and m.group(1).upper() == m.group(1):
        return m.group(1)
    if re.search(r"EPC[^.]{0,20}exempt|exempt from[^.]{0,20}EPC", t, re.I):
        return "Exempt"
    m = re.search(r"target(?:ing)?\s+(?:an?\s+)?EPC\s+(?:rating\s+)?(?:of\s+)?([A-G]\+?)", t, re.I)
    if m:
        return m.group(1).upper() + " (target)"
    return ""


def breeam(text: str) -> str:
    t = clean(text)
    m = re.search(r"BREEAM[^.]{0,40}?\b(Outstanding|Excellent|Very Good|Good|Pass)\b", t, re.I)
    if m:
        target = re.search(r"target|aim|seek", t[max(0, m.start() - 25): m.end()], re.I)
        return m.group(1).title() + (" (target)" if target else "")
    return ""


def sprinklers(text: str) -> str:
    t = clean(text).lower()
    if "sprinkler" not in t:
        return ""
    if re.search(r"(no|not|without|un)[\s-]*sprinkler", t) or "not sprinklered" in t:
        return "No"
    if re.search(r"sprinkler[^.]{0,40}(capable|ready|provision for|potential|could be|can be)", t):
        return "Sprinkler-ready / provision (stated)"
    return "Yes (stated)"


def build_status(text: str) -> str:
    t = clean(text).lower()
    if re.search(r"design (?:&|and) build|\bd ?& ?b\b|build[\s-]to[\s-]suit|bespoke (?:units?|buildings?) (?:can|could) be|plots? available for|pre-let opportunit", t):
        return "Design & Build"
    if re.search(r"under construction|on site now|now on site|speculative(?:ly)? (?:build|development|unit)|new[\s-]build|newly (?:built|constructed)|brand new|practical completion|completion (?:due|expected|in) (?:q[1-4]|" + MONTHS + r")|new (?:speculative|grade a|warehouse|industrial|logistics) ", t):
        return "New Build"
    if re.search(r"refurbish|refurb\b|comprehensively upgraded|newly upgraded", t):
        return "Existing – Refurbished"
    return "Existing"


def availability_date(text: str) -> str:
    t = clean(text)
    pats = [
        r"available\s+(?:from|in|by|for occupation (?:from|in))?\s*((?:early|mid|late|end of)?\s*Q[1-4]\s*\d{4}|(?:early|mid|late|end of)?\s*(?:spring|summer|autumn|winter)\s*\d{4}|" + MONTHS + r"\.?\s+\d{4}|(?:early|mid|late|end of)\s+\d{4})",
        r"(?:practical completion|pc|completion|complete|delivery|ready for occupation)\s*(?:is\s*)?(?:due|expected|anticipated|targeted|scheduled|programmed)?\s*(?:to complete\s*)?(?:in|by|for|from|:)?\s*((?:early|mid|late|end of)?\s*Q[1-4]\s*\d{4}|(?:spring|summer|autumn|winter)\s*\d{4}|" + MONTHS + r"\.?\s+\d{4})",
        r"due to complete\s*(?:in|by)?\s*(Q[1-4]\s*\d{4}|" + MONTHS + r"\.?\s+\d{4})",
        r"(Q[1-4]\s*\d{4})\s*(?:completion|delivery|availability)",
    ]
    for p in pats:
        m = re.search(p, t, re.I)
        if m:
            return clean(m.group(1)).title().replace("Q", "Q")
    if re.search(r"available (?:now|immediately)|immediate(?:ly)? available|immediate occupation|vacant possession", t, re.I):
        return "Now"
    return ""


def rent(text: str) -> tuple[float | None, str]:
    """Return (rent £ psf pa if explicitly quoted, rent text as quoted)."""
    t = clean(text)
    psf = re.findall(r"£\s?(\d{1,3}(?:\.\d{1,2})?)\s*(?:-|–|to)?\s*(?:£\s?(\d{1,3}(?:\.\d{1,2})?))?\s*(?:per\s+sq\.?\s?ft|psf|p\.s\.f\.?|/\s?sq\.?\s?ft|per square foot|sq\.?\s?ft)\b", t, re.I)
    vals = []
    for a, b in psf:
        for x in (a, b):
            if x:
                v = float(x)
                if 1 <= v <= 60:
                    vals.append(v)
    if vals:
        lo, hi = min(vals), max(vals)
        txt = f"£{lo:.2f} psf" if lo == hi else f"£{lo:.2f}–£{hi:.2f} psf"
        return lo, txt
    m = re.search(r"(?:rent(?:al)?|quoting|asking)[^£.]{0,30}£\s?([\d,]{4,})\s*(?:per annum|p\.?a\.?x?|pax|per year|a year)\b", t, re.I) or \
        re.search(r"£\s?([\d,]{4,})\s*(?:per annum|p\.a\.x?|pax|pa)\b", t, re.I)
    if m:
        return None, f"£{m.group(1)} pa"
    if re.search(r"(?:rent|rental|terms|price)[^.]{0,30}(?:on application|upon application|poa|p\.o\.a)", t, re.I):
        return None, "On application"
    return None, ""


def price(text: str) -> str:
    t = clean(text)
    m = re.search(r"(?:offers?\s+(?:in excess of|over|in the region of|around|based on)|guide price|asking price|price|oieo|oiro|for sale at|freehold(?: price)?)\s*(?:of|:)?\s*£\s?([\d,.]+\s*(?:m\b|million)?)", t, re.I)
    if m:
        q = m.group(0)
        return clean(q[:80])
    m = re.search(r"£\s?([\d,]{5,}(?:\.\d+)?|\d+(?:\.\d+)?\s*(?:m\b|million))\s*(OIEO|OIRO|offers|\+ VAT)?", t, re.I)
    if m and re.search(r"sale|freehold|purchase", t, re.I) and not re.search(r"per annum|pa\b|pax", t[m.end(): m.end() + 12], re.I):
        return clean(m.group(0))
    return ""


def tenure(text: str) -> str:
    t = clean(text).lower()
    fh = bool(re.search(r"\bfreehold\b|for sale|to buy|may sell|purchase", t))
    lh = bool(re.search(r"\bleasehold\b|to let|to rent|for rent|lease|letting", t))
    if fh and lh:
        return "Leasehold / Freehold"
    if fh:
        return "Freehold"
    if lh:
        return "Leasehold"
    return ""


def accommodation_areas(text: str) -> tuple[float | None, float | None]:
    t = clean(text)
    wh = re.search(r"\b(?:warehouse|production|workshop|industrial)(?:\s+(?:area|accommodation|space|floor))?\s*[:\-–]?\s*([\d,]{3,})\s*(?:" + SQFT + r")", t, re.I)
    of = re.search(r"\b(?:offices?|office accommodation|first floor offices?|ground floor offices?|two[\s-]storey offices?)(?:\s+(?:area|accommodation|space))?\s*[:\-–]?\s*([\d,]{3,})\s*(?:" + SQFT + r")", t, re.I)
    w = to_float(wh.group(1)) if wh else None
    o = to_float(of.group(1)) if of else None
    if w is None and o is None:
        # accommodation schedule rows: "| Ground Warehouse | 16,345 | 1,518.50 |"
        rows = re.findall(r"\|\s*((?:ground|first|1st|2nd|second|mezzanine)?\s*(?:floor\s*)?"
                          r"(?:warehouse|production|workshop|industrial|offices?|office/welfare))\s*\|\s*([\d,]{3,})\s*\|", t, re.I)
        ws = [to_float(v) for k, v in rows if not re.search(r"office", k, re.I)]
        os_ = [to_float(v) for k, v in rows if re.search(r"office", k, re.I)]
        w = sum(x for x in ws if x) or None
        o = sum(x for x in os_ if x) or None
    return w, o


def unit_number(text: str) -> str:
    t = clean(text)
    m = re.search(r"\b(?:units?|plots?|buildings?|bldg\.?|warehouse|dc|hall|phase)\s*((?:[A-Z]{0,2}\d{1,4}[A-Z]?|[A-Z]\b)(?:\s*(?:-|–|&|and|,|/|to)\s*(?:[A-Z]{0,2}\d{1,4}[A-Z]?|[A-Z]\b))*)", t, re.I)
    if m:
        u = m.group(1).upper().replace("AND", "&")
        return re.sub(r"\s+", "", u)
    return ""


ESTATE_WORDS = r"(?:industrial estate|trading estate|business park|industrial park|trade park|distribution park|logistics park|enterprise park|retail park|estate|park|centre|center|point|hub|gateway|works|quays?|village|interchange|employment area|campus|court|place|yard|mill|terminal)"


def estate_name(address: str) -> str:
    for seg in [s.strip() for s in re.split(r",|\|", address or "") if s.strip()]:
        if re.search(r"\b(?:road|rd|lane|drive|street|avenue|close|way|crescent)$", seg, re.I) and not re.search(
                r"industrial estate|trading estate|business park|industrial park|trade park|distribution park|logistics park", seg, re.I):
            continue
        if re.search(r"\b" + ESTATE_WORDS + r"\b", seg, re.I) and not re.match(r"^(?:units?|plot)\s*\S+$", seg, re.I):
            seg = re.sub(r"^(?i:units?|plots?|building)\s*[A-Z0-9&\-– ,]+?\s+(?=[A-Z][a-z])", "", seg)
            seg = re.sub(r"\s*[-–(]\s*units?\s*[A-Z0-9&\-– ]+\)?$", "", seg, flags=re.I)
            return seg.strip()
    return ""


# ---------------------------------------------------------------- status
def marketing_flags(text: str) -> dict:
    t = clean(text).lower()
    return {
        "under_offer": bool(re.search(r"under offer|let agreed|sold subject to contract|sold stc|\bsstc\b|\bstc\b|under negotiation", t)),
        "let_or_sold": bool(re.search(r"\b(?:now let|has been let|let to\s|been sold|now sold|sold to\s|letting completed|deal completed)\b", t)),
        "investment": bool(re.search(r"investment (?:opportunity|sale)|fully let|let to .{0,40}(?:until|expiring|lease expiry)|net initial yield|\bniy\b|reversionary yield|passing rent|income producing|sale and leaseback", t)),
        "vacant": bool(re.search(r"vacant possession|available (?:now|immediately)|immediately available|ready for (?:immediate )?occupation|immediate occupation", t)),
        "under_construction": bool(re.search(r"under construction|on site now|now on site|construction (?:has )?(?:started|commenced|underway|under way)|works (?:have )?commenced|due to complete|completion (?:due|expected|in|q[1-4])|practical completion (?:due|expected|in|q[1-4]|" + MONTHS + r")", t)),
        "proposed": bool(re.search(r"design (?:&|and) build|\bd ?& ?b\b|build[\s-]to[\s-]suit|proposed (?:development|scheme|unit|building)|planning (?:application|consent|permission)[^.]{0,40}(?:for|submitted|granted)|pre-let|bespoke (?:requirements|units?|buildings?)|units? (?:can be|will be) (?:built|constructed|delivered)", t)),
    }


MONTH_NUM = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def date_end(text: str):
    """Latest calendar month implied by an availability phrase -> (year, month) or None."""
    t = (text or "").lower()
    y = re.search(r"(20\d\d)", t)
    if not y:
        return None
    year = int(y.group(1))
    q = re.search(r"q([1-4])", t)
    if q:
        return year, int(q.group(1)) * 3
    for k, v in MONTH_NUM.items():
        if re.search(r"\b" + k, t):
            return year, v
    for k, v in (("spring", 5), ("summer", 8), ("autumn", 11), ("winter", 12), ("early", 4), ("mid", 8), ("late", 12), ("end", 12)):
        if k in t:
            return year, v
    return year, 12


def classify_availability(marketing_status: str, text: str, avail_date: str, build: str) -> tuple[str, list[str]]:
    """Return (availability status, conflict notes)."""
    flags = marketing_flags(text)
    ms = (marketing_status or "").lower()
    conflicts: list[str] = []
    if "under offer" in ms or "let agreed" in ms or "sstc" in ms or "subject to contract" in ms:
        return "Under Offer", conflicts
    if flags["under_offer"] and ms and "under offer" not in ms:
        conflicts.append(f"Listing labelled '{marketing_status}' but text mentions under offer / let agreed")
    if flags["under_offer"] and not ms:
        return "Under Offer", conflicts
    if build == "Design & Build" or (flags["proposed"] and not flags["vacant"] and build != "Existing – Refurbished"
                                     and not flags["under_construction"] and not avail_date):
        if flags["vacant"]:
            conflicts.append("Text mentions both design & build and immediate availability")
        return "Proposed / Design and Build", conflicts
    if flags["under_construction"] and build == "New Build":
        return "Under Construction", conflicts
    if avail_date and avail_date != "Now":
        import datetime as _dt
        end = date_end(avail_date)
        today = _dt.date.today()
        if end and end < (today.year, today.month):
            conflicts.append(f"Stated availability date '{avail_date}' has passed – current availability not confirmed")
            return ("Available Now" if flags["vacant"] else "Availability Unconfirmed"), conflicts
        if flags["under_construction"] and build == "New Build":
            return "Under Construction", conflicts
        return "Available at a Future Date", conflicts
    if avail_date == "Now" or flags["vacant"]:
        return "Available Now", conflicts
    return "Availability Unconfirmed", conflicts


def apply_text(listing: Listing, text: str, source: str = "web") -> None:
    """Fill blank listing fields from free text. Never overwrites structured data."""
    if not text:
        return
    t = clean(text)
    filled = []

    def setv(attr, val):
        if val not in (None, "", []) and getattr(listing, attr) in (None, "", []):
            setattr(listing, attr, val)
            filled.append(attr)

    setv("eaves_m", eaves(t))
    setv("dock_doors", dock_doors(t))
    setv("level_doors", level_doors(t))
    setv("yard_depth_m", yard_depth(t))
    setv("site_acres", site_acres(t))
    setv("power", power(t))
    setv("epc", epc(t))
    setv("breeam", breeam(t))
    setv("sprinklers", sprinklers(t))
    setv("availability_date", availability_date(t))
    r_psf, r_txt = rent(t)
    setv("rent_psf", r_psf)
    setv("rent_text", r_txt)
    setv("price_text", price(t))
    w, o = accommodation_areas(t)
    setv("warehouse_sqft", w)
    setv("office_sqft", o)
    if source == "web":
        setv("tenure", tenure(t))
        setv("build_status", build_status(t))
    if filled and source not in listing.sources:
        listing.sources.append(source)
