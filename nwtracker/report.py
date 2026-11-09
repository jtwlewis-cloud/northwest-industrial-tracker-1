"""Markdown run report: coverage, totals, duplicates, missing data, limitations."""
from __future__ import annotations

from collections import Counter

from . import config

FIELDS = [("postcode", "Full postcode"), ("max_sqft", "Floor area"), ("eaves_m", "Eaves height"),
          ("dock_doors", "Dock-level doors"), ("level_doors", "Level-access doors"), ("yard_depth_m", "Yard depth"),
          ("site_acres", "Site area"), ("power", "Power supply"), ("epc", "EPC rating"), ("breeam", "BREEAM rating"),
          ("sprinklers", "Sprinklers"), ("availability_date", "Availability date"), ("rent_psf", "Rent £psf"),
          ("price_text", "Freehold price"), ("warehouse_sqft", "Warehouse area"), ("office_sqft", "Office area"),
          ("brochure_urls", "PDF brochure link"), ("agent_contacts", "Agent contacts")]


def _fmt(n):
    return f"{n:,.0f}" if n else "0"


def write_report(path, run_id, run_date, results, records, changes, pairs, excluded_counts, listings):
    L = []
    w = L.append
    w(f"# North West Industrial & Logistics Availability – Run Report\n")
    w(f"Run {run_id} · {run_date}\n")
    ok = [r for r in results if r.status in ("Success", "Partial")]
    w("## 1. Website coverage\n")
    w(f"{len(ok)} of {len(results)} agent websites were searched successfully.\n")
    w("| Agent | Status | Listings scanned | NW industrial listings kept | Brochures read | Notes |")
    w("|---|---|---:|---:|---:|---|")
    for r in results:
        w(f"| {r.agent} | {r.status} | {r.listings_scanned:,} | {len(r.included):,} | {r.brochures_read} | "
          f"{r.message.replace('|', '/')[:220]} |")
    w("")
    blocked = [r for r in results if r.status not in ("Success", "Partial")]
    if blocked:
        w("**Agents that could not be checked:**\n")
        for r in blocked:
            w(f"- **{r.agent}** – {r.message}")
        w("")
    avail = [r for r in records if r.get("availability_status") != "Under Offer"]
    tot = [r for r in avail if r.get("count_in_totals", True)]
    w("## 2. Property totals\n")
    w(f"- Agent listings collected (NW industrial, after exclusions): **{len(listings):,}**")
    w(f"- Unique properties after de-duplication: **{len(records):,}**")
    w(f"- Advertised available (excluding under offer): **{len(avail):,}** properties, "
      f"**{_fmt(sum(r.get('max_sqft') or 0 for r in tot))} sq ft** (max available area per property, no double counting)")
    w("")
    w("| Availability status | Properties | sq ft |")
    w("|---|---:|---:|")
    for st in config.AVAILABILITY_STATUSES:
        rs = [r for r in records if r.get("availability_status") == st]
        w(f"| {st} | {len(rs)} | {_fmt(sum(r.get('max_sqft') or 0 for r in rs if r.get('count_in_totals', True)))} |")
    w("")
    w("| County | Properties | Available sq ft |")
    w("|---|---:|---:|")
    for c in config.COUNTIES:
        rs = [r for r in tot if r.get("county") == c]
        w(f"| {c} | {len([r for r in records if r.get('county') == c])} | {_fmt(sum(r.get('max_sqft') or 0 for r in rs))} |")
    w("")
    w("## 3. Duplicate records\n")
    multi = [r for r in records if len(r.get("agents", [])) > 1]
    merged = [p for p in pairs if p["decision"] == "merge"]
    amb = [p for p in pairs if p["decision"] == "ambiguous"]
    w(f"- Properties marketed by more than one of the {len(results)} agents searched (merged into one row): **{len(multi)}**")
    w(f"- Listing pairs merged: {len(merged)} (of which flagged because sizes differ: "
      f"{sum(1 for p in merged if 'flagged' in p['reason'])})")
    w(f"- Ambiguous pairs left separate and flagged for manual checking: **{len(amb)}**")
    w(f"- Records excluded from floor-space totals to avoid double counting: "
      f"{sum(1 for r in records if not r.get('count_in_totals', True))}")
    w(f"- Records with conflicting information between agents (flagged): "
      f"{sum(1 for r in records if r.get('conflicts'))}")
    combos = Counter(" + ".join(sorted(r["agents"])) for r in multi)
    if combos:
        w("\nMost common joint instructions:\n")
        for k, v in combos.most_common(10):
            w(f"- {k}: {v}")
    w("\n## 4. Missing information (share of unique properties where not disclosed)\n")
    w("| Field | Not disclosed | % |")
    w("|---|---:|---:|")
    n = max(len(records), 1)
    for key, label in FIELDS:
        miss = sum(1 for r in records if r.get(key) in (None, "", [], 0))
        if key == "postcode":
            miss = sum(1 for r in records if " " not in (r.get("postcode") or ""))
        w(f"| {label} | {miss} | {miss / n:.0%} |")
    w("\n## 5. Changes since previous search\n")
    cnt = Counter(c["change_type"] for c in changes)
    if not changes and any(r.get("change_flag") == "Baseline (first run)" for r in records):
        w("This is the first (baseline) run – no previous search to compare against.")
    elif not changes:
        w("No new, changed or removed advertisements since the previous search.")
    for k, v in cnt.items():
        w(f"- {k}: {v}")
    w("\n## 6. Exclusions applied\n")
    w("| Agent | Reason | Listings |")
    w("|---|---|---:|")
    for (a, reason), v in sorted(excluded_counts.get("_reasons", {}).items(), key=lambda x: (x[0][0], -x[1])):
        w(f"| {a} | {reason} | {v} |")
    w("\n## 7. Known limitations\n")
    for line in LIMITATIONS:
        w(f"- {line}")
    path.write_text("\n".join(L), encoding="utf-8")
    return path


LIMITATIONS = [
    "CBRE (cbre.co.uk) and Colliers (colliers.com) present a Cloudflare bot challenge to automated clients. It was "
    "not bypassed, so their instructions appear only where another searched agent markets the same property jointly.",
    "Knight Frank and Fisher German publish UK-wide industrial searches; all pages are read and only North West "
    "locations kept. Knight Frank's specification detail is limited to what its search data provides "
    "(its property pages are rendered by script).",
    "Indurent is a landlord, not an agency: its units are listed under 'Indurent (landlord)' and merged with the "
    "letting agents' listings where the same unit is marketed by both. Its brochures (vault.industrials.co.uk) are "
    "linked but not read.",
    "Novaloca and LoopNet are not searched: their terms of use prohibit commercial re-use/storage (Novaloca, "
    "without written permission) or automated access (LoopNet).",
    "Cushman & Wakefield is searched on cushwakeproperty.co.uk (its UK agency site); its brochures are hosted on "
    "Novaloca's file server and are linked but not read.",
    "CPP (Commercial Property Partners) markets property across the North West, Yorkshire and the Midlands; all its "
    "industrial and trade-counter listings were checked and only North West locations kept.",
    "Brochures hosted on cdn.sharplaunch.com (Avison Young) and AgencyPilot (Legat Owen, LSH, Taylor Weaver, LM6) are linked in the "
    "schedule but not read, because those hosts' robots.txt files disallow automated access. Brochures over 20 MB "
    "are also skipped.",
    "JLL's robots.txt disallows its search pages, so JLL listings are enumerated from its published property sitemap. "
    "Multi-unit JLL schemes load their unit-by-unit accommodation table with JavaScript; the scheme-level size range "
    "is recorded and the number of availabilities is noted.",
    "Davies Harrison listings do not publish postcodes; their location is taken from the address/town name and "
    "flagged '(check)'. LSH sometimes publishes only a postcode district.",
    "Specifications (eaves, doors, power, EPC, BREEAM, yard depth, rents) are extracted only where explicitly stated on "
    "the listing page or the first PDF brochure. Image-only brochures cannot be read. Blank = not disclosed.",
    "Availability status is evidence-based: 'Available Now' requires an explicit statement (e.g. 'available now', "
    "'immediate occupation'). Advertised properties with no availability statement are classed 'Availability "
    "Unconfirmed'. Online advertisements do not guarantee present-day availability.",
    "Duplicate matching is deliberately conservative: different unit numbers are never merged, and uncertain matches "
    "are listed in 'Duplicate Review' rather than merged.",
    "Size bands use the maximum available area; divisible options are not added together.",
]
