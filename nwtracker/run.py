"""Command-line entry point: python -m nwtracker [options]"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import logging
import shutil
from collections import Counter
from datetime import date, datetime

from . import config
from .agents import AGENTS
from .db import HistoryDB
from .dedupe import deduplicate, merge_group
from .excel import build_workbook
from .geo import Geo
from .http import Fetcher
from .report import write_report

log = logging.getLogger("nwtracker")


def setup_logging(verbose: bool) -> str:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = config.LOG_DIR / f"run-{datetime.now():%Y%m%d-%H%M%S}.log"
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[logging.FileHandler(path, encoding="utf-8"), logging.StreamHandler()],
    )
    for noisy in ("urllib3", "charset_normalizer", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return str(path)


def flag_overlaps(records: list[dict], listings, pairs, rec_of_listing) -> list[dict]:
    """Build Duplicate Review rows and flag estate-level / unit-level overlaps
    so their floor space is not counted twice."""
    rows = []
    for p in pairs:
        a, b = listings[p.a], listings[p.b]
        ra, rb = rec_of_listing[id(a)], rec_of_listing[id(b)]
        label = "Merged – same property" if p.decision == "merge" else "Possible duplicate – manual check"
        if p.decision == "merge" and "flagged" in p.reason:
            label = "Merged – check (sizes differ)"
        rows.append({"decision": p.decision, "decision_label": label, "score": p.score, "reason": p.reason,
                     "property_id_a": ra["property_id"], "agent_a": a.agent, "name_a": a.title, "size_a": a.max_sqft,
                     "url_a": a.url, "property_id_b": rb["property_id"], "agent_b": b.agent, "name_b": b.title,
                     "size_b": b.max_sqft, "url_b": b.url})
        if p.decision != "ambiguous" or ra is rb:
            continue
        for rec, other in ((ra, rb), (rb, ra)):
            msg = f"Possible duplicate of {other['property_id']} ({', '.join(other.get('agents', []))}) – check"
            if msg not in rec.get("dup_flag", ""):
                rec["dup_flag"] = (rec.get("dup_flag", "") + "\n" + msg).strip()
        # unit-level listing inside an estate-level range -> exclude the unit from totals
        lo_a, hi_a = ra.get("min_sqft") or 0, ra.get("max_sqft") or 0
        lo_b, hi_b = rb.get("min_sqft") or 0, rb.get("max_sqft") or 0
        if hi_a and hi_b:
            if lo_a < hi_a and hi_b <= hi_a and hi_b >= lo_a * 0.95 and ra is not rb and (lo_b == hi_b):
                rb["count_in_totals"] = False
                rb["notes"].append(f"Floor space excluded from totals – may be part of {ra['property_id']} (estate-level listing)")
            elif lo_b < hi_b and hi_a <= hi_b and hi_a >= lo_b * 0.95 and (lo_a == hi_a):
                ra["count_in_totals"] = False
                ra["notes"].append(f"Floor space excluded from totals – may be part of {rb['property_id']} (estate-level listing)")
    rows.sort(key=lambda r: (r["decision"] != "ambiguous", r["property_id_a"]))
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="North West Industrial & Logistics availability tracker")
    ap.add_argument("--agents", help="comma-separated agent keys to run (default: all). Keys: " + ", ".join(AGENTS))
    ap.add_argument("--no-brochures", action="store_true", help="do not download/read PDF brochures")
    ap.add_argument("--delay", type=float, default=config.REQUEST_DELAY_SECONDS, help="seconds between requests per host")
    ap.add_argument("--db", default=str(config.DB_PATH))
    ap.add_argument("--output-dir", default=str(config.OUTPUT_DIR))
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logfile = setup_logging(args.verbose)
    for d in (config.DATA_DIR, config.CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)
    from pathlib import Path
    out_dir = Path(args.output_dir)
    (out_dir / "history").mkdir(parents=True, exist_ok=True)
    (out_dir / "reports").mkdir(parents=True, exist_ok=True)

    keys = [k.strip() for k in args.agents.split(",")] if args.agents else list(AGENTS)
    fetcher = Fetcher(delay=args.delay)
    geo = Geo(fetcher, args.db)
    db = HistoryDB(args.db)
    run_id = db.start_run(not args.no_brochures)
    run_date = date.today().isoformat()
    log.info("Run %s started – agents: %s", run_id, ", ".join(keys))

    results = []
    with cf.ThreadPoolExecutor(max_workers=len(keys)) as pool:
        futs = {pool.submit(AGENTS[k](fetcher, geo, not args.no_brochures).run): k for k in keys}
        for fut in cf.as_completed(futs):
            r = fut.result()
            log.info("%-26s %-8s %s (%.0fs)", r.agent, r.status, r.message, r.duration_s)
            results.append(r)
    order = {AGENTS[k].name: i for i, k in enumerate(AGENTS)}
    results.sort(key=lambda r: order.get(r.agent, 99))
    for r in results:
        db.save_agent_result(run_id, r)

    listings = [l for r in results for l in r.included]
    for l in listings:
        l.raw["verified"] = run_date
    groups, pairs = deduplicate(listings)
    records, rec_of_listing = [], {}
    for g in groups:
        rec = merge_group(g)
        rec["last_verified"] = run_date
        rec["count_in_totals"] = True
        rec["dup_flag"] = ""
        if rec.get("same_agent_repeats"):
            rec["notes"].append("Agent advertises this property on more than one page")
        if len(rec["agents"]) > 1:
            rec["dup_flag"] = f"Jointly marketed – {len(g)} listings merged"
        records.append(rec)
        for l in g:
            rec_of_listing[id(l)] = rec
    db.assign_ids(records)
    pair_rows = flag_overlaps(records, listings, pairs, rec_of_listing)
    failed = {r.agent for r in results if r.status in ("Failed", "Blocked")}
    changes = db.record(run_id, records, failed)
    db.save_pairs(run_id, pair_rows)

    excluded_counts: dict = {"_reasons": Counter()}
    for r in results:
        excluded_counts[r.agent] = len(r.excluded)
        for l in r.excluded:
            reason = l.excluded_reason.split(" (")[0]
            excluded_counts["_reasons"][(r.agent, reason)] += 1

    latest = out_dir / config.WORKBOOK_NAME
    dated = out_dir / "history" / config.WORKBOOK_NAME.replace(".xlsx", f" {run_date} run{run_id}.xlsx")
    history = db.history_summary() + [{"run_id": run_id, "started_at": datetime.now().isoformat(timespec="seconds"),
                                       "properties": len(records)}]
    build_workbook(dated, records, changes, results, pair_rows, history, run_date, excluded_counts)
    shutil.copyfile(dated, latest)
    report = write_report(out_dir / "reports" / f"Run Report {run_date} run{run_id}.md", run_id, run_date, results,
                          records, changes, pair_rows, excluded_counts, listings)
    shutil.copyfile(report, out_dir / "Latest Run Report.md")
    db.finish_run(run_id, str(latest), str(dated), notes=f"log: {logfile}")
    log.info("Run %s complete: %d unique properties from %d listings. Workbook: %s", run_id, len(records),
             len(listings), latest)
    return 0
