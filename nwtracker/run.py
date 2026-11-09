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
from .db import HistoryDB, export_history, import_history, unpack
from .dedupe import deduplicate, merge_group
from .excel import build_workbook, spec_summary
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


def ensure_db(db_path: str) -> None:
    """On a fresh checkout the SQLite file is absent: rebuild it from the exports."""
    from pathlib import Path
    p = Path(db_path)
    if p.exists() and p.stat().st_size > 0:
        import sqlite3
        try:
            if sqlite3.connect(str(p)).execute("SELECT COUNT(*) FROM runs").fetchone()[0]:
                return
        except sqlite3.Error:
            pass
    n = import_history(p, config.HISTORY_EXPORT_DIR)
    if n:
        log.info("Rebuilt history database from %d run exports in %s", n, config.HISTORY_EXPORT_DIR)


def rebuild(db_path: str, out_dir, run_id: int | None = None) -> int:
    """Regenerate the workbook and report for the latest completed run from
    the database only (no web requests)."""
    import json
    from types import SimpleNamespace

    db = HistoryDB(db_path)
    c = db.conn
    latest_id = c.execute("SELECT MAX(run_id) FROM runs WHERE finished_at IS NOT NULL").fetchone()[0]
    row = c.execute("SELECT run_id, started_at FROM runs WHERE finished_at IS NOT NULL AND run_id=?",
                    (run_id or latest_id,)).fetchone()
    if not row:
        log.error("No completed run in %s", db_path)
        return 1
    run_id, run_date = row["run_id"], row["started_at"][:10]
    prev = db.previous_run_id(run_id)
    records = [unpack(r["data"]) for r in c.execute("SELECT data FROM property_snapshots WHERE run_id=?", (run_id,))]
    flags = {r["property_id"]: r["change_type"] for r in c.execute("SELECT property_id, change_type FROM changes WHERE run_id=?", (run_id,))}
    first = {r["property_id"]: r["first_seen"] for r in c.execute("SELECT property_id, first_seen FROM properties")}
    for r in records:
        r["change_flag"] = "Baseline (first run)" if prev is None else flags.get(r["property_id"], "Unchanged")
        r["first_seen"] = first.get(r["property_id"], run_date)
    changes = []
    for r in c.execute("SELECT * FROM changes WHERE run_id=?", (run_id,)):
        ch = dict(r)
        if prev and ch["change_type"] in ("Removed", "Merged", "Not re-checked"):
            old = c.execute("SELECT data FROM property_snapshots WHERE run_id=? AND property_id=?", (prev, ch["property_id"])).fetchone()
            ch["record"] = unpack(old["data"]) if old else {}
        changes.append(ch)
    coverage = []
    for r in c.execute("SELECT * FROM agent_runs WHERE run_id=?", (run_id,)):
        coverage.append(SimpleNamespace(agent=r["agent"], website=r["website"], status=r["status"], method=r["method"],
                                        search_urls=json.loads(r["search_urls"] or "[]"), listings_scanned=r["scanned"],
                                        candidates=r["candidates"], included=[None] * r["included"],
                                        excluded=[None] * r["excluded"], brochures_read=r["brochures_read"],
                                        brochure_errors=r["brochure_errors"], duration_s=r["duration_s"],
                                        message=r["message"], errors=json.loads(r["errors"] or "[]")))
    order = {AGENTS[k].name: i for i, k in enumerate(AGENTS)}
    coverage.sort(key=lambda x: order.get(x.agent, 99))
    lst = {}
    for r in c.execute("SELECT url, data FROM listings WHERE run_id=?", (run_id,)):
        lst[r["url"]] = unpack(r["data"])
    pairs = []
    for r in c.execute("SELECT * FROM duplicate_reviews WHERE run_id=?", (run_id,)):
        a, b = lst.get(r["url_a"], {}), lst.get(r["url_b"], {})
        label = "Merged – same property" if r["decision"] == "merge" else "Possible duplicate – manual check"
        if r["decision"] == "merge" and "flagged" in (r["reason"] or ""):
            label = "Merged – check (sizes differ)"
        pairs.append({**dict(r), "decision_label": label, "agent_a": a.get("agent"), "name_a": a.get("title"),
                      "size_a": a.get("max_sqft"), "agent_b": b.get("agent"), "name_b": b.get("title"), "size_b": b.get("max_sqft")})
    pairs.sort(key=lambda p: (p["decision"] != "ambiguous", p["property_id_a"] or ""))
    excluded_counts: dict = {"_reasons": Counter()}
    for r in c.execute("SELECT agent, excluded_reason FROM listings WHERE run_id=? AND included=0", (run_id,)):
        excluded_counts[r["agent"]] = excluded_counts.get(r["agent"], 0) + 1
        excluded_counts["_reasons"][(r["agent"], (r["excluded_reason"] or "").split(" (")[0])] += 1
    n_listings = c.execute("SELECT COUNT(*) FROM listings WHERE run_id=? AND included=1", (run_id,)).fetchone()[0]
    latest = out_dir / config.WORKBOOK_NAME
    dated = out_dir / "history" / config.WORKBOOK_NAME.replace(".xlsx", f" {run_date} run{run_id}.xlsx")
    history = [h for h in db.history_summary() if h["run_id"] <= run_id]
    build_workbook(dated, records, changes, coverage, pairs, history, run_date, excluded_counts)
    if run_id == latest_id:
        shutil.copyfile(dated, latest)
    report = write_report(out_dir / "reports" / f"Run Report {run_date} run{run_id}.md", run_id, run_date, coverage,
                          records, changes, pairs, excluded_counts, [None] * n_listings)
    if run_id == latest_id:
        shutil.copyfile(report, out_dir / "Latest Run Report.md")
    log.info("Rebuilt workbook and report for run %s from the database: %s", run_id, dated)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="North West Industrial & Logistics availability tracker")
    ap.add_argument("--agents", help="comma-separated agent keys to run (default: all). Keys: " + ", ".join(AGENTS))
    ap.add_argument("--no-brochures", action="store_true", help="do not download/read PDF brochures")
    ap.add_argument("--delay", type=float, default=config.REQUEST_DELAY_SECONDS, help="seconds between requests per host")
    ap.add_argument("--db", default=str(config.DB_PATH))
    ap.add_argument("--output-dir", default=str(config.OUTPUT_DIR))
    ap.add_argument("--rebuild", nargs="?", const=0, type=int, metavar="RUN",
                    help="regenerate a run's workbook and report from the database, no web requests (default: latest run)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logfile = setup_logging(args.verbose)
    for d in (config.DATA_DIR, config.CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)
    from pathlib import Path
    out_dir = Path(args.output_dir)
    (out_dir / "history").mkdir(parents=True, exist_ok=True)
    (out_dir / "reports").mkdir(parents=True, exist_ok=True)

    ensure_db(args.db)
    if args.rebuild is not None:
        return rebuild(args.db, out_dir, args.rebuild or None)
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
        if not rec.get("specification"):
            rec["specification"] = spec_summary(rec)
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
    failed |= {AGENTS[k].name for k in AGENTS if k not in keys}  # agents not searched in a partial run
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
    export_history(db.conn, config.HISTORY_EXPORT_DIR, [run_id])
    log.info("Run %s complete: %d unique properties from %d listings. Workbook: %s", run_id, len(records),
             len(listings), latest)
    return 0
