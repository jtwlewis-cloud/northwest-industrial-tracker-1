"""Daily new-listings digest for the morning briefing.

    python3 -m nwtracker.daily            # latest sweep vs the sweep ~1 day earlier
    python3 -m nwtracker.daily --days 3   # Mondays: since Friday's sweep

Writes output/daily/Latest New Listings.md (human-readable, for the briefing),
output/daily/latest_new_listings.json (structured) and a dated copy of each.
Uses the same rules as the weekly report: only new advertisements from sources
already being searched count as new to market."""
from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from . import config
from .db import HistoryDB
from .weekly import IMMEDIATE, PIPELINE, analyse

log = logging.getLogger("nwtracker.daily")


def pick_runs(db: HistoryDB, days: int):
    runs = [dict(r) for r in db.conn.execute(
        "SELECT run_id, started_at FROM runs WHERE finished_at IS NOT NULL ORDER BY run_id")]
    if len(runs) < 2:
        raise SystemExit("Need at least two completed sweeps")
    cur = runs[-1]
    cutoff = datetime.fromisoformat(cur["started_at"]) - timedelta(hours=days * 24 - 6)
    earlier = [r for r in runs[:-1] if datetime.fromisoformat(r["started_at"]) <= cutoff]
    return cur, (earlier[-1] if earlier else runs[-2])


def _item(r: dict) -> dict:
    url = (list((r.get("agent_urls") or {}).values()) or r.get("listing_urls") or [""])[0]
    return {"property_id": r.get("property_id"), "name": r.get("property_name"), "postcode": r.get("postcode"),
            "town": r.get("town"), "county": r.get("county"), "submarket": r.get("submarket"),
            "max_sqft": r.get("max_sqft"), "size_band": r.get("size_band"),
            "availability": r.get("availability_status"), "build": r.get("build_status"),
            "tenure": r.get("tenure"), "terms": r.get("rent_text") or r.get("price_text") or "",
            "agents": r.get("agents") or [], "url": url}


def build(db: HistoryDB, days: int) -> dict:
    cur, base = pick_runs(db, days)
    a = analyse(db, cur, base)
    supply = a["new"] + a["relisted"]
    sources = [dict(r) for r in db.conn.execute(
        "SELECT agent, status, message FROM agent_runs WHERE run_id=?", (cur["run_id"],))]
    s = lambda rs: sum((r.get("max_sqft") or 0) for r in rs)
    return {
        "sweep_date": cur["started_at"][:10], "sweep_time": cur["started_at"][11:16],
        "compared_with": base["started_at"][:16].replace("T", " "), "run_id": cur["run_id"],
        "baseline_run_id": base["run_id"],
        "new_count": len(a["new"]), "new_sqft": s(a["new"]),
        "returned_count": len(a["relisted"]), "removed_count": len(a["removed"]), "removed_sqft": s(a["removed"]),
        "new_existing_sqft": s([r for r in supply if r.get("availability_status") in IMMEDIATE]),
        "new_pipeline_sqft": s([r for r in supply if r.get("availability_status") in PIPELINE]),
        "new": [_item(r) for r in sorted(a["new"], key=lambda x: -(x.get("max_sqft") or 0))],
        "returned": [_item(r) for r in a["relisted"]],
        "removed": [_item(r) for r in sorted(a["removed"], key=lambda x: -(x.get("max_sqft") or 0))],
        "new_joint_agents": [{**_item(r), "added_agents": r.get("added_agents", [])} for r in a["new_joint"]],
        "by_county": Counter(r.get("county") or "Unknown" for r in supply),
        "by_agent": Counter(ag for r in supply for ag in (r.get("agents") or [])),
        "newly_covered_sources": a["newly_added_agents"],
        "sources_not_ok": [x for x in sources if x["status"] not in ("Success",)],
        "total_available": a["total_available"], "total_available_sqft": a["total_available_sqft"],
    }


def markdown(d: dict) -> str:
    def fmt(n):
        return f"{n:,.0f}" if n else "size n/d"
    L = [f"## New North West industrial listings – sweep {d['sweep_date']} {d['sweep_time']} UTC",
         f"Compared with the sweep of {d['compared_with']} UTC.", "",
         f"- **New to market:** {d['new_count']} properties, {d['new_sqft']:,.0f} sq ft "
         f"(existing {d['new_existing_sqft']:,.0f} / pipeline {d['new_pipeline_sqft']:,.0f})",
         f"- **Returned to market:** {d['returned_count']}",
         f"- **Removed (let, sold or withdrawn):** {d['removed_count']} properties, {d['removed_sqft']:,.0f} sq ft",
         f"- **Advertised available now:** {d['total_available']:,} properties, {d['total_available_sqft']:,.0f} sq ft", ""]
    if d["new"]:
        L += ["| Property | Location | sq ft | Status | Agents |", "|---|---|---:|---|---|"]
        for r in d["new"]:
            L.append(f"| [{(r['name'] or '')[:55]}]({r['url']}) | {r['submarket']}, {r['county']} | {fmt(r['max_sqft'])} | "
                     f"{r['availability']} | {', '.join(r['agents'])} |")
        L.append("")
    else:
        L += ["No new industrial listings since the previous sweep.", ""]
    if d["returned"]:
        L.append("**Returned to market:** " + "; ".join(f"{r['name']} ({fmt(r['max_sqft'])} sq ft, {', '.join(r['agents'])})"
                                                      for r in d["returned"]))
    if d["removed"]:
        L.append("**Removed:** " + "; ".join(f"{r['name']} ({fmt(r['max_sqft'])} sq ft, {', '.join(r['agents'])})"
                                             for r in d["removed"][:10])
                 + (f" … and {len(d['removed']) - 10} more" if len(d["removed"]) > 10 else ""))
    if d["new_joint_agents"]:
        L.append("**New joint agents:** " + "; ".join(f"{r['name']} (+{', '.join(r['added_agents'])})"
                                                     for r in d["new_joint_agents"]))
    bad = [x for x in d["sources_not_ok"] if x["agent"] not in ("CBRE", "Colliers")]
    if bad:
        L.append("**Sources not fully checked:** " + "; ".join(f"{x['agent']} – {x['status']}" for x in bad))
    L.append("")
    L.append("Full schedule: North West Industrial & Logistics Availability.xlsx (tracker branch claude/magical-ride-4nijqh).")
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Daily new-listings digest")
    ap.add_argument("--days", type=int, default=1, help="compare with the sweep about this many days earlier")
    ap.add_argument("--db", default=str(config.DB_PATH))
    ap.add_argument("--output-dir", default=str(config.OUTPUT_DIR / "daily"))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    from .run import ensure_db
    ensure_db(args.db)
    d = build(HistoryDB(args.db), args.days)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    md = markdown(d)
    (out / f"New Listings {d['sweep_date']}.md").write_text(md, encoding="utf-8")
    (out / "Latest New Listings.md").write_text(md, encoding="utf-8")
    js = json.dumps(d, indent=1, default=str)
    (out / f"new_listings_{d['sweep_date']}.json").write_text(js, encoding="utf-8")
    (out / "latest_new_listings.json").write_text(js, encoding="utf-8")
    log.info("Daily digest (run %s vs %s): %d new, %d removed", d["run_id"], d["baseline_run_id"],
             d["new_count"], d["removed_count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
