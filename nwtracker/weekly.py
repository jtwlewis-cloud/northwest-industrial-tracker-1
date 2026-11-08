"""Weekly new-stock report: what came to the market since last week's search,
by size, location and agent.

    python -m nwtracker.weekly            # latest run vs the run ~7 days earlier
    python -m nwtracker.weekly --days 7

A property counts as NEW TO MARKET only if it was advertised by an agent that
was already being searched successfully at the baseline run, through a listing
that did not exist then. Properties that appear only because a newly added
agent is now being searched are reported separately ("newly covered source")
so the weekly figures are not inflated by changes in coverage.
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from . import config
from .db import HistoryDB, export_history, unpack
from .excel import HEAD_FILL, HEAD_FONT, NEW_FILL, SUB_FONT, TITLE_FONT, _write_table

log = logging.getLogger("nwtracker.weekly")

WEEKLY_SCHEMA = """
CREATE TABLE IF NOT EXISTS weekly_reports (
  run_id INTEGER PRIMARY KEY, baseline_run_id INTEGER, week_ending TEXT, baseline_date TEXT,
  new_count INTEGER, new_sqft REAL, new_immediate_sqft REAL, new_pipeline_sqft REAL,
  removed_count INTEGER, removed_sqft REAL, relisted_count INTEGER, new_joint_agents INTEGER,
  newly_covered_count INTEGER, total_available INTEGER, total_available_sqft REAL, workbook TEXT);
"""
IMMEDIATE = ("Available Now", "Availability Unconfirmed")
PIPELINE = ("Available at a Future Date", "Under Construction", "Proposed / Design and Build")


def _sqft(r):
    return r.get("max_sqft") or 0


def find_runs(db: HistoryDB, days: int, run_id: int | None = None):
    c = db.conn
    runs = [dict(r) for r in c.execute("SELECT run_id, started_at FROM runs WHERE finished_at IS NOT NULL ORDER BY run_id")]
    if not runs:
        raise SystemExit("No completed runs in the database")
    cur = next((r for r in runs if r["run_id"] == run_id), runs[-1]) if run_id else runs[-1]
    t_cur = datetime.fromisoformat(cur["started_at"])
    earlier = [r for r in runs if r["run_id"] < cur["run_id"]]
    if not earlier:
        raise SystemExit("Need at least two completed runs to produce a weekly report")
    old_enough = [r for r in earlier if (t_cur - datetime.fromisoformat(r["started_at"])).days >= days - 1]
    base = old_enough[-1] if old_enough else earlier[0]
    return cur, base


def analyse(db: HistoryDB, cur: dict, base: dict) -> dict:
    c = db.conn
    snap = lambda rid: {r["property_id"]: unpack(r["data"]) for r in
                        c.execute("SELECT property_id, data FROM property_snapshots WHERE run_id=?", (rid,))}
    now, before = snap(cur["run_id"]), snap(base["run_id"])
    base_urls = {r[0] for r in c.execute("SELECT url FROM listings WHERE run_id=?", (base["run_id"],))}
    url_agent = {r[0]: r[1] for r in c.execute("SELECT url, agent FROM listings WHERE run_id=?", (cur["run_id"],))}
    covered = {r[0] for r in c.execute("SELECT agent FROM agent_runs WHERE run_id=? AND status IN ('Success','Partial')",
                                       (base["run_id"],))}
    covered_now = {r[0] for r in c.execute("SELECT agent FROM agent_runs WHERE run_id=? AND status IN ('Success','Partial')",
                                           (cur["run_id"],))}
    ever = {r[0]: r[1] for r in c.execute("SELECT property_id, first_seen_run FROM properties")}
    base_url_pid = {}
    for pid, rec in before.items():
        for u in rec.get("listing_urls", []):
            base_url_pid[u] = pid

    new, relisted, newly_covered, new_joint = [], [], [], []
    for pid, rec in now.items():
        urls = rec.get("listing_urls", [])
        if pid in before:
            added = sorted(set(rec.get("agents", [])) - set(before[pid].get("agents", [])))
            added_market = [a for a in added if a in covered]
            if added_market:
                new_joint.append({**rec, "added_agents": added_market})
            continue
        if any(u in base_urls for u in urls):
            continue  # same advertisement, only the record ID changed (merge)
        fresh_from_covered = [u for u in urls if url_agent.get(u) in covered and u not in base_urls]
        if not fresh_from_covered:
            newly_covered.append(rec)
        elif ever.get(pid) is not None and ever[pid] <= base["run_id"]:
            relisted.append(rec)
        else:
            new.append(rec)

    removed = []
    url_now = {u for rec in now.values() for u in rec.get("listing_urls", [])}
    for pid, rec in before.items():
        if pid in now or any(u in url_now for u in rec.get("listing_urls", [])):
            continue
        if not set(rec.get("agents", [])) & covered_now:
            continue  # its agents could not be checked this week
        removed.append(rec)
    avail = [r for r in now.values() if r.get("availability_status") != "Under Offer"]
    return {"cur": cur, "base": base, "new": new, "relisted": relisted, "newly_covered": newly_covered,
            "new_joint": new_joint, "removed": removed, "now": now, "covered": covered,
            "newly_added_agents": sorted(covered_now - covered),
            "total_available": len(avail), "total_available_sqft": sum(_sqft(r) for r in avail if r.get("count_in_totals", True))}


# ---------------------------------------------------------------- output
def _title(ws, text, sub):
    ws.sheet_view.showGridLines = False
    ws["A1"] = text
    ws["A1"].font = TITLE_FONT
    ws["A2"] = sub
    ws["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells("A2:H2")
    ws.row_dimensions[2].height = 48


def _group(rows, keyf):
    g = defaultdict(list)
    for r in rows:
        for k in (keyf(r) if isinstance(keyf(r), list) else [keyf(r)]):
            g[k].append(r)
    return g


def _prop_rows(rs, extra=None):
    out = []
    for r in sorted(rs, key=lambda x: (x.get("county") or "", -(x.get("max_sqft") or 0))):
        url = (list((r.get("agent_urls") or {}).values()) or r.get("listing_urls") or [""])[0]
        row = [r.get("property_id"), r.get("property_name"), r.get("town") or "", r.get("postcode"), r.get("county"),
               r.get("submarket"), r.get("max_sqft"), r.get("size_band"), r.get("build_status"),
               r.get("availability_status"), r.get("tenure"), r.get("rent_text") or r.get("price_text") or "",
               ", ".join(r.get("agents") or []), url]
        if extra:
            row.insert(-1, extra(r))
        out.append(row)
    return out


PROP_HEADS = ["Property ID", "Property", "Town", "Postcode", "County", "Submarket", "Max sq ft", "Size band",
              "Existing / New Build", "Availability", "Tenure", "Quoted terms", "Agents", "Listing"]
PROP_FMT = [None, None, None, None, None, None, "#,##0", None, None, None, None, None, None, None]
PROP_W = [11, 40, 14, 10, 17, 26, 11, 18, 16, 20, 16, 20, 34, 40]


def _links(ws, col, start, n):
    for rr in range(start, start + n):
        cell = ws.cell(row=rr, column=col)
        if cell.value and str(cell.value).startswith("http"):
            cell.hyperlink = cell.value
            cell.value = "Open listing"
            cell.font = Font(color="0563C1", underline="single")


def build(a: dict, path: Path, trend: list[dict]):
    wb = Workbook()
    new, rel, rem, cov, joint = a["new"], a["relisted"], a["removed"], a["newly_covered"], a["new_joint"]
    supply = new + rel
    week_end = a["cur"]["started_at"][:10]
    base_d = a["base"]["started_at"][:10]
    s = lambda rs: sum(_sqft(r) for r in rs)

    ws = wb.active
    ws.title = "Summary"
    _title(ws, f"North West Industrial – New Stock to Market, week ending {week_end}",
           f"Search on {week_end} compared with the search on {base_d}. 'New to market' = a new advertisement by an agent "
           "already being tracked. Floor space = maximum available area per property. Listings from agents added to the "
           "tracker this week are excluded from the new-stock figures (see 'Newly Covered Sources').")
    head = [
        ["New properties to market", len(new), s(new)],
        ["Returned to market (previously advertised, then withdrawn)", len(rel), s(rel)],
        ["Total new supply this week", len(supply), s(supply)],
        ["  – of which existing buildings (available now / date not stated)",
         sum(1 for r in supply if r.get("availability_status") in IMMEDIATE),
         s([r for r in supply if r.get("availability_status") in IMMEDIATE])],
        ["  – of which pipeline (future date, under construction, D&B)",
         sum(1 for r in supply if r.get("availability_status") in PIPELINE),
         s([r for r in supply if r.get("availability_status") in PIPELINE])],
        ["  – of which already under offer", sum(1 for r in supply if r.get("availability_status") == "Under Offer"),
         s([r for r in supply if r.get("availability_status") == "Under Offer"])],
        ["Removed from the market (let, sold or withdrawn)", len(rem), s(rem)],
        ["Net change in advertised stock", len(supply) - len(rem), s(supply) - s(rem)],
        ["Existing properties that gained an additional agent", len(joint), None],
        ["Newly covered sources (not counted as new stock)", len(cov), s(cov)],
        ["Total advertised available properties now (excl. under offer)", a["total_available"], a["total_available_sqft"]],
    ]
    ws.cell(row=4, column=1, value="Headline").font = SUB_FONT
    row = _write_table(ws, 5, ["Measure", "Properties", "sq ft"], head, "WkHeadline",
                       widths=[64, 12, 14], formats=[None, "#,##0", "#,##0"]) + 2
    if a["newly_added_agents"]:
        ws.cell(row=row, column=1, value="Agents first searched this week (their listings are not counted as new stock): "
                + ", ".join(a["newly_added_agents"])).font = Font(italic=True)
        row += 2

    def breakdown(title, keyf, name, order=None, label="Group"):
        nonlocal row
        ws.cell(row=row, column=1, value=title).font = SUB_FONT
        g_new, g_rem = _group(supply, keyf), _group(rem, keyf)
        keys = order or sorted(set(g_new) | set(g_rem), key=lambda k: (-len(g_new.get(k, [])), str(k)))
        rows = []
        for k in keys:
            n, r_ = g_new.get(k, []), g_rem.get(k, [])
            if not n and not r_ and order is None:
                continue
            rows.append([k, len(n), s(n), len(r_), s(r_), s(n) - s(r_)])
        row = _write_table(ws, row + 1, [label, "New to market", "New sq ft", "Removed", "Removed sq ft", "Net sq ft"],
                           rows, name, formats=[None, "#,##0", "#,##0", "#,##0", "#,##0", "#,##0"]) + 2

    breakdown("By size band (max available area)", lambda r: r.get("size_band") or "Size Not Disclosed", "WkSize",
              order=[b[0] for b in config.SIZE_BANDS] + ["Size Not Disclosed"], label="Size band")
    breakdown("By county", lambda r: r.get("county") or "Unknown", "WkCounty", order=config.COUNTIES, label="County")
    breakdown("By submarket", lambda r: f"{r.get('county')} – {r.get('submarket')}", "WkSubmarket", label="County – submarket")
    breakdown("By agent (joint instructions count for each agent)", lambda r: list(r.get("agents") or ["Unknown"]),
              "WkAgent", label="Agent")
    ws.cell(row=row, column=1, value="Quoted rents on new stock (only where a £psf rent is published)").font = SUB_FONT
    rents = [r["rent_psf"] for r in supply if r.get("rent_psf")]
    rows = [[len(rents), min(rents), round(statistics.median(rents), 2), max(rents)]] if rents else []
    row = _write_table(ws, row + 1, ["Rent quotes", "Min £psf", "Median £psf", "Max £psf"], rows, "WkRents",
                       formats=["0", "£0.00", "£0.00", "£0.00"]) + 2
    ws.column_dimensions["A"].width = 64

    for title, rs, name, extra_head, extra in (
            ("New to Market", new, "WkNew", None, None),
            ("Returned to Market", rel, "WkRelisted", None, None),
            ("Removed from Market", rem, "WkRemoved", None, None),
            ("New Joint Agents", joint, "WkJoint", "Agent(s) added", lambda r: ", ".join(r.get("added_agents", []))),
            ("Newly Covered Sources", cov, "WkCovered", None, None)):
        w2 = wb.create_sheet(title)
        heads = PROP_HEADS[:-1] + ([extra_head] if extra_head else []) + PROP_HEADS[-1:]
        fmts = PROP_FMT[:-1] + ([None] if extra_head else []) + PROP_FMT[-1:]
        rows = _prop_rows(rs, extra)
        _write_table(w2, 1, heads, rows, name, widths=PROP_W[:-1] + ([24] if extra_head else []) + PROP_W[-1:], formats=fmts)
        _links(w2, len(heads), 2, len(rows))
        w2.freeze_panes = "C2"
        if title == "New to Market":
            for rr in range(2, len(rows) + 2):
                w2.cell(row=rr, column=1).fill = NEW_FILL

    w3 = wb.create_sheet("Weekly Trend")
    rows = [[t["week_ending"], t["baseline_date"], t["new_count"], t["new_sqft"], t["new_immediate_sqft"],
             t["new_pipeline_sqft"], t["removed_count"], t["removed_sqft"], t["new_sqft"] - t["removed_sqft"],
             t["total_available"], t["total_available_sqft"]] for t in trend]
    _write_table(w3, 1, ["Week ending", "Compared with", "New to market", "New sq ft", "New existing sq ft",
                         "New pipeline sq ft", "Removed", "Removed sq ft", "Net sq ft", "Advertised available",
                         "Advertised sq ft"], rows, "WkTrend", widths=[12, 13, 12, 13, 15, 15, 10, 13, 13, 14, 15],
                 formats=[None, None, "#,##0", "#,##0", "#,##0", "#,##0", "#,##0", "#,##0", "#,##0", "#,##0", "#,##0"])
    w3.freeze_panes = "A2"
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def markdown(a: dict, path: Path):
    new, rel, rem = a["new"], a["relisted"], a["removed"]
    supply = new + rel
    s = lambda rs: sum(_sqft(r) for r in rs)
    L = [f"# North West industrial – new stock, week ending {a['cur']['started_at'][:10]}", "",
         f"Compared with the search on {a['base']['started_at'][:10]}.", "",
         f"- **New to market:** {len(new)} properties, {s(new):,.0f} sq ft",
         f"- **Returned to market:** {len(rel)} properties, {s(rel):,.0f} sq ft",
         f"- **Removed (let / sold / withdrawn):** {len(rem)} properties, {s(rem):,.0f} sq ft",
         f"- **Net change:** {s(supply) - s(rem):+,.0f} sq ft",
         f"- Existing properties that gained an extra agent: {len(a['new_joint'])}",
         f"- Not counted (agents first searched this week: {', '.join(a['newly_added_agents']) or 'none'}): "
         f"{len(a['newly_covered'])} properties", ""]
    for title, keyf in (("Size band", lambda r: [r.get("size_band") or "Size Not Disclosed"]),
                        ("County", lambda r: [r.get("county") or "Unknown"]),
                        ("Agent", lambda r: list(r.get("agents") or []))):
        cnt, sq = Counter(), Counter()
        for r in supply:
            for k in keyf(r):
                cnt[k] += 1
                sq[k] += _sqft(r)
        if cnt:
            L += [f"| {title} | New properties | sq ft |", "|---|---:|---:|"]
            L += [f"| {k} | {v} | {sq[k]:,.0f} |" for k, v in cnt.most_common()]
            L.append("")
    if supply:
        L += ["## New instructions", "", "| ID | Property | Location | sq ft | Status | Agents |", "|---|---|---|---:|---|---|"]
        for r in sorted(supply, key=lambda x: -(x.get("max_sqft") or 0)):
            L.append(f"| {r.get('property_id')} | {(r.get('property_name') or '')[:50]} | {r.get('submarket')}, "
                     f"{r.get('county')} | {(r.get('max_sqft') or 0):,.0f} | {r.get('availability_status')} | "
                     f"{', '.join(r.get('agents') or [])} |")
    path.write_text("\n".join(L), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Weekly new-stock report")
    ap.add_argument("--days", type=int, default=7, help="compare with the latest run at least this many days earlier")
    ap.add_argument("--run", type=int, help="report on this run instead of the latest")
    ap.add_argument("--db", default=str(config.DB_PATH))
    ap.add_argument("--output-dir", default=str(config.OUTPUT_DIR / "weekly"))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    from .run import ensure_db
    ensure_db(args.db)
    db = HistoryDB(args.db)
    db.conn.executescript(WEEKLY_SCHEMA)
    cur, base = find_runs(db, args.days, args.run)
    a = analyse(db, cur, base)
    out = Path(args.output_dir)
    week_end = cur["started_at"][:10]
    xlsx = out / f"NW New Industrial Stock - week ending {week_end}.xlsx"
    s = lambda rs: sum(_sqft(r) for r in rs)
    supply = a["new"] + a["relisted"]
    db.conn.execute("INSERT OR REPLACE INTO weekly_reports VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        cur["run_id"], base["run_id"], week_end, base["started_at"][:10], len(a["new"]), s(a["new"]),
        s([r for r in supply if r.get("availability_status") in IMMEDIATE]),
        s([r for r in supply if r.get("availability_status") in PIPELINE]), len(a["removed"]), s(a["removed"]),
        len(a["relisted"]), len(a["new_joint"]), len(a["newly_covered"]), a["total_available"],
        a["total_available_sqft"], str(xlsx)))
    db.conn.commit()
    if args.db == str(config.DB_PATH):
        export_history(db.conn, config.HISTORY_EXPORT_DIR, [cur["run_id"]])
    trend = [dict(r) for r in db.conn.execute("SELECT * FROM weekly_reports ORDER BY week_ending, run_id")]
    build(a, xlsx, trend)
    md = out / f"NW New Industrial Stock - week ending {week_end}.md"
    markdown(a, md)
    (out / "Latest Weekly New Stock.md").write_text(md.read_text(encoding="utf-8"), encoding="utf-8")
    import shutil
    shutil.copyfile(xlsx, out / "Latest Weekly New Stock.xlsx")
    log.info("Weekly report (run %s vs run %s): %d new, %d returned, %d removed, %d newly covered. %s",
             cur["run_id"], base["run_id"], len(a["new"]), len(a["relisted"]), len(a["removed"]),
             len(a["newly_covered"]), xlsx)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
