"""Orchestrates one daily run: fetch -> store -> calculate -> render."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import charts, commentary, events, property as prop
from .config import (BOE_MPC_DATES, MANUAL_OBSERVATIONS_CSV, PROPERTY_SPREADS, PROPERTY_TABLE_C,
                     REPORTS_DIR, SERIES, TIMEZONE)
from .metrics import movement, trend_label
from .models import Observation
from .sources import boe, fred, ons, treasury
from .store import Store, load_manual

log = logging.getLogger("monitor")


def london_now() -> datetime:
    return datetime.now(ZoneInfo(TIMEZONE))


def collect(store: Store, report_date: date, run_id: str, offline: bool = False) -> tuple[list[str], dict]:
    """Fetch all automated sources, then manual entries; upsert into the store."""
    failures: list[str] = []
    meta: dict = {}
    results = []
    if not offline:
        results.append(treasury.fetch(report_date))
        ust_ok = bool(results[-1].observations)
        results.append(fred.fetch(report_date, include_ust_fallback=not ust_ok))
        results.append(boe.fetch(report_date))
        results.append(ons.fetch(report_date))
    for res in results:
        failures += res.errors
        meta.update(res.meta)
        for e in res.errors:
            store.log_failure(run_id, e)
        for ob in res.observations:
            if ob.obs_date <= report_date:
                store.upsert(ob, run_id)
    for ob in load_manual(MANUAL_OBSERVATIONS_CSV):
        if ob.obs_date <= report_date:
            store.upsert(ob, run_id)
    return failures, meta


def derive_spreads(store: Store, register, report_date: date, run_id: str) -> dict[str, list]:
    """Daily property-vs-gilt spread history (derived, for charting)."""
    gilts = store.history("UK_GILT_10Y", report_date)
    hist: dict[str, list] = {}
    for label, sid in PROPERTY_SPREADS:
        entries = register.get(sid, [])
        pts = []
        for g in gilts:
            in_force = [p for p in entries if p.evidence_date <= g.obs_date]
            if not in_force:
                continue
            v = round((in_force[-1].mid - g.value) * 100, 1)
            pts.append((g.obs_date, v))
            store.upsert(Observation(f"SPREAD_{sid}", g.obs_date, v, "Derived: property yield midpoint less UK 10Y",
                                     in_force[-1].source_url, "derived", None, "",
                                     f"{in_force[-1].provider} {in_force[-1].period} vs {g.source}"), run_id)
        hist[label] = pts
    return hist


def build_context(store: Store, report_date: date, failures: list[str], meta: dict, run_id: str) -> dict:
    moves = {sid: movement(sid, store.history(sid, report_date), report_date) for sid in SERIES}
    register = prop.load()
    gilt_hist = store.history("UK_GILT_10Y", report_date)
    prop_rows = prop.table_rows(register, PROPERTY_TABLE_C, report_date)
    spreads = prop.spreads(register, PROPERTY_SPREADS, gilt_hist, report_date)
    spread_hist = derive_spreads(store, register, report_date, run_id)

    infl_trend = {}
    for sid in ("UK_CPI_YOY", "UK_CPIH_YOY", "UK_CORE_CPI_YOY", "US_CPI_YOY", "US_CORE_CPI_YOY"):
        infl_trend[sid] = trend_label([o.value for o in store.history(sid, report_date)])

    def curve(a, b):
        ma, mb = moves[a].latest, moves[b].latest
        if ma and mb and ma.obs_date == mb.obs_date:
            return round((ma.value - mb.value) * 100, 1), ma.obs_date
        return None, None

    ctx = {
        "report_date": report_date,
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0),
        "moves": moves,
        "series": SERIES,
        "property_rows": prop_rows,
        "spreads": spreads,
        "spread_hist": spread_hist,
        "inflation_trend": infl_trend,
        "curve_uk": curve("UK_GILT_10Y", "UK_GILT_5Y"),
        "curve_us": curve("US_UST_10Y", "US_UST_5Y"),
        "failures": failures,
        "ons_meta": meta,
        "events": events.upcoming(report_date, meta),
        "next_mpc": events.next_after(BOE_MPC_DATES, report_date - timedelta(days=1)),
        "discrepancies": [d | {"label": SERIES.get(d["series_id"], {}).get("label", d["series_id"])}
                          for d in store.discrepancies(report_date - timedelta(days=45))],
    }
    ctx["confirmed"] = commentary.confirmed_developments(ctx)
    notes = commentary.load_notes(report_date)
    ctx["notes"] = notes or {}
    ctx["notes_source"] = "analyst note" if notes else "rule-based"
    if not notes:
        ctx["notes"].update(commentary.rule_based(ctx))
    return ctx


def run(report_date: date | None = None, offline: bool = False) -> dict:
    from .report import render

    started = datetime.now(timezone.utc).replace(microsecond=0)
    report_date = report_date or london_now().date()
    run_id = started.strftime("%Y%m%dT%H%M%SZ")
    store = Store()
    failures, meta = collect(store, report_date, run_id, offline)
    ctx = build_context(store, report_date, failures, meta, run_id)

    out_dir = REPORTS_DIR / f"{report_date:%Y}" / f"{report_date:%m}"
    chart_dir = out_dir / "charts"
    ctx["bond_chart"], ctx["bond_chart_note"] = charts.bond_chart(
        store, report_date, chart_dir / f"bonds-{report_date.isoformat()}.png")
    ctx["spread_chart"], ctx["spread_chart_note"] = charts.spread_chart(
        ctx["spread_hist"], chart_dir / f"spreads-{report_date.isoformat()}.png", report_date,
        {s.label for s in ctx["spreads"] if s.prop and (report_date - s.prop.evidence_date).days > 90})

    md_path, html_path = render(ctx, out_dir)
    store.save()
    status = ("ok" if not failures else "partial") + (" (offline)" if offline else "")
    store.log_run({"run_id": run_id, "report_date": report_date.isoformat(), "started_at": started.isoformat(),
                   "finished_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                   "status": status, "inserted": store.counts["inserted"], "revised": store.counts["revised"],
                   "failures": len(failures), "failure_detail": " | ".join(failures)[:2000]})
    return {"markdown": md_path, "html": html_path, "failures": failures, "status": status}
