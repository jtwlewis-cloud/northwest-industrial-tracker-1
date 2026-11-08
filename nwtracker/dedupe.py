"""Cross-agent de-duplication.

Rules (conservative – when in doubt, do not merge, flag instead):
* Listings must share a location: same full postcode, or same postcode
  district with similar names, or (no postcode) same local authority with
  strongly similar names.
* Different unit numbers are never merged.
* Floor areas must agree (within 5%, or 20% with strong name/unit agreement).
* Same location + similar name but materially different size, or a unit-level
  vs estate-level listing, is recorded as an ambiguous pair for manual review.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from . import config
from .extract import outcode
from .models import Listing

STOP = set("""unit units the and of at to a plot plots building road rd lane ln way street st avenue ave drive dr close
industrial estate park business trading trade centre center court place point hub works distribution logistics warehouse
north south east west greater manchester merseyside cheshire lancashire cumbria uk england liverpool warrington
wigan bolton stockport salford trafford preston kirkby huyton speke runcorn widnes crewe for lease sale let to new
nr near off phase site land""".split())

KEY_FIELDS = ["max_sqft", "availability_status", "marketing_status", "rent_psf", "eaves_m", "epc", "price_text"]


def norm_pc(pc: str) -> str:
    pc = (pc or "").upper().strip()
    return pc.replace(" ", "") if re.match(r"^[A-Z]{1,2}\d[A-Z\d]?\s+\d[A-Z]{2}$", pc) else ""


def unit_tokens(u: str) -> frozenset:
    u = (u or "").upper().replace(" ", "")
    if not u:
        return frozenset()
    if re.search(r"[A-Z]?\d+[A-Z]?[-–](?:[A-Z]?\d+[A-Z]?)", u) and "&" not in u and "," not in u:
        return frozenset([u.replace("–", "-")])
    return frozenset(x for x in re.split(r"[&,/]|AND", u) if x)


def name_tokens(l: Listing) -> set:
    text = f"{l.property_name or l.title} {l.estate}".lower()
    text = re.sub(r"\b[a-z]{1,2}\d[a-z\d]?\s*\d[a-z]{2}\b", " ", text)
    toks = set(re.findall(r"[a-z][a-z0-9']+|\d{2,}", text))
    return {t for t in toks if t not in STOP and not t.isdigit() or (t.isdigit() and len(t) >= 3)}


def name_sim(a: Listing, b: Listing) -> float:
    ta, tb = name_tokens(a), name_tokens(b)
    jac = len(ta & tb) / len(ta | tb) if ta and tb else 0.0
    sa = (a.estate or a.property_name or a.title).lower()
    sb = (b.estate or b.property_name or b.title).lower()
    seq = SequenceMatcher(None, sa, sb).ratio() if sa and sb else 0.0
    return max(jac, seq * 0.9)


def size_rel(a: Listing, b: Listing) -> float | None:
    x, y = a.max_sqft, b.max_sqft
    if not x or not y:
        return None
    return abs(x - y) / max(x, y)


@dataclass
class PairResult:
    a: int
    b: int
    decision: str      # merge / ambiguous / distinct
    score: float
    reason: str


def compare(a: Listing, b: Listing) -> tuple[str, float, str]:
    pa, pb = norm_pc(a.postcode), norm_pc(b.postcode)
    ns = name_sim(a, b)
    if pa and pb:
        if pa == pb:
            loc = "same postcode"
        elif outcode(a.postcode) == outcode(b.postcode) and ns >= 0.5:
            loc = "same postcode district + similar name"
        else:
            return "distinct", 0, "different postcode"
    else:
        oa, ob = outcode(a.postcode), outcode(b.postcode)
        if oa and ob and oa == ob and ns >= 0.55:
            loc = "same postcode district + similar name"
        elif (not oa or not ob) and a.local_authority and a.local_authority == b.local_authority and ns >= 0.65:
            loc = "same local authority + strongly similar name (postcode missing)"
        else:
            return "distinct", 0, "no shared location"
    ua, ub = unit_tokens(a.unit_number), unit_tokens(b.unit_number)
    sr = size_rel(a, b)
    same_agent = a.agent == b.agent
    score = ns * 4 + (3 if pa and pa == pb else 1)
    if ua and ub and ua != ub:
        return "distinct", score, f"{loc}; different units ({a.unit_number} vs {b.unit_number})"
    units_equal = bool(ua and ub and ua == ub)
    if units_equal:
        score += 3
    if sr is not None:
        score += 3 if sr <= 0.05 else (1 if sr <= 0.2 else -2)
    desc = f"{loc}; name similarity {ns:.2f}; " + (f"size difference {sr:.0%}" if sr is not None else "size not comparable") + \
        ("; same unit no." if units_equal else "")
    if same_agent:
        if sr is not None and sr <= 0.02 and (units_equal or ns >= 0.8):
            return "merge", score, desc + "; same agent lists it more than once"
        return "distinct", score, desc + "; same agent, treated as separate units"
    if sr is None:
        if units_equal or ns >= 0.75:
            return "merge", score, desc
        return ("ambiguous" if ns >= 0.4 else "distinct"), score, desc
    if sr <= 0.05 and (units_equal or ns >= 0.3 or (pa and pa == pb and not ua and not ub)):
        return "merge", score, desc
    if sr <= 0.2 and (units_equal or ns >= 0.6):
        return "merge", score, desc + "; sizes differ – flagged"
    if ns >= 0.4 or units_equal or (ua or ub) and ns >= 0.3:
        return "ambiguous", score, desc + "; possibly different unit/phase or estate-level vs unit-level listing"
    return "distinct", score, desc


@dataclass
class Group:
    members: list[int] = field(default_factory=list)


def deduplicate(listings: list[Listing]) -> tuple[list[list[Listing]], list[PairResult]]:
    n = len(listings)
    parent = list(range(n))
    units: dict[int, set] = {i: {unit_tokens(listings[i].unit_number)} - {frozenset()} for i in range(n)}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    pairs: list[PairResult] = []
    # block by postcode district (or local authority when postcode missing)
    blocks: dict[str, list[int]] = {}
    for i, l in enumerate(listings):
        keys = {outcode(l.postcode) or "", "LA:" + (l.local_authority or "")}
        for k in keys:
            if k and k != "LA:":
                blocks.setdefault(k, []).append(i)
    seen = set()
    for idx in blocks.values():
        for x in range(len(idx)):
            for y in range(x + 1, len(idx)):
                i, j = idx[x], idx[y]
                if (i, j) in seen:
                    continue
                seen.add((i, j))
                if listings[i].url == listings[j].url:
                    decision, score, why = "merge", 10, "identical URL"
                else:
                    decision, score, why = compare(listings[i], listings[j])
                if decision == "distinct":
                    continue
                if decision == "merge":
                    ri, rj = find(i), find(j)
                    if ri != rj:
                        if units[ri] and units[rj] and units[ri] != units[rj]:
                            pairs.append(PairResult(i, j, "ambiguous", score, why + "; not merged – would join different unit numbers"))
                            continue
                        parent[rj] = ri
                        units[ri] = units[ri] | units[rj]
                pairs.append(PairResult(i, j, decision, score, why))
    groups: dict[int, list[Listing]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(listings[i])
    # ambiguous pairs that ended up in the same group are no longer ambiguous
    pairs = [p for p in pairs if not (p.decision == "ambiguous" and find(p.a) == find(p.b))]
    return list(groups.values()), pairs


def completeness(l: Listing) -> int:
    return sum(1 for k, v in l.to_dict().items() if v not in (None, "", []) and k not in ("notes", "conflicts"))


STATUS_RANK = {"Under Offer": 0, "Available Now": 1, "Under Construction": 2, "Available at a Future Date": 3,
               "Proposed / Design and Build": 4, "Availability Unconfirmed": 9}


def merge_group(group: list[Listing]) -> dict:
    """Combine listings for one property into a master record dict."""
    g = sorted(group, key=completeness, reverse=True)
    primary = g[0]
    rec = primary.to_dict()
    for l in g[1:]:
        for k, v in l.to_dict().items():
            if rec.get(k) in (None, "", []) and v not in (None, "", []):
                rec[k] = v
    agents = list(dict.fromkeys(l.agent for l in g))
    rec["agents"] = agents
    rec["listing_urls"] = [l.url for l in g]
    rec["agent_urls"] = {}
    for l in g:
        rec["agent_urls"].setdefault(l.agent, l.url)
    rec["brochure_urls"] = list(dict.fromkeys(u for l in g for u in l.brochure_urls))
    rec["agent_contacts"] = " || ".join(f"{l.agent}: {l.agent_contacts}" for l in g if l.agent_contacts)
    rec["notes"] = list(dict.fromkeys(n for l in g for n in l.notes))
    rec["conflicts"] = list(dict.fromkeys(c for l in g for c in l.conflicts))
    rec["sources"] = list(dict.fromkeys(s for l in g for s in l.sources))
    rec["same_agent_repeats"] = len(g) - len(agents)
    if len(g) > 1:
        # conflicting values between agents
        sizes = {l.agent: l.max_sqft for l in g if l.max_sqft}
        if sizes and (max(sizes.values()) - min(sizes.values())) / max(sizes.values()) > 0.05:
            rec["conflicts"].append("Size differs between listings: " + ", ".join(f"{a} {v:,.0f} sq ft" for a, v in sizes.items()))
        statuses = {l.agent: l.availability_status for l in g if l.availability_status}
        if len(set(statuses.values())) > 1:
            rec["conflicts"].append("Availability differs: " + ", ".join(f"{a}: {s}" for a, s in statuses.items()))
            if "Under Offer" in statuses.values():
                rec["availability_status"] = "Under Offer"
            else:
                rec["availability_status"] = min(statuses.values(), key=lambda s: STATUS_RANK.get(s, 5))
        rents = {l.agent: l.rent_psf for l in g if l.rent_psf}
        if len(set(rents.values())) > 1:
            rec["conflicts"].append("Quoted rent differs: " + ", ".join(f"{a}: £{v:.2f}" for a, v in rents.items()))
        eaves = {l.agent: l.eaves_m for l in g if l.eaves_m}
        if eaves and max(eaves.values()) - min(eaves.values()) > 0.5:
            rec["conflicts"].append("Eaves height differs: " + ", ".join(f"{a}: {v}m" for a, v in eaves.items()))
        epcs = {l.agent: l.epc for l in g if l.epc}
        if len(set(epcs.values())) > 1:
            rec["conflicts"].append("EPC differs: " + ", ".join(f"{a}: {v}" for a, v in epcs.items()))
        ms = {l.agent: l.marketing_status for l in g if l.marketing_status}
        if any("offer" in v.lower() for v in ms.values()) and not all("offer" in v.lower() for v in ms.values()):
            rec["conflicts"].append("Marketing status differs: " + ", ".join(f"{a}: {v}" for a, v in ms.items()))
        tens = {l.tenure for l in g if l.tenure}
        if len(tens) > 1:
            rec["tenure"] = "Leasehold / Freehold" if any("Free" in t for t in tens) and any("Lease" in t for t in tens) else rec["tenure"]
        for l in g:
            if l.availability_date and rec.get("availability_date") and l.availability_date != rec["availability_date"]:
                rec["conflicts"].append(f"Availability date differs: {l.agent} '{l.availability_date}' vs '{rec['availability_date']}'")
    rec["conflicts"] = list(dict.fromkeys(rec["conflicts"]))
    rec["size_band"] = config.size_band(rec.get("max_sqft"))
    return rec
