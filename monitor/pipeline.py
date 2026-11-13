"""Orchestrates one daily run: fetch -> store -> calculate -> render."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import charts, commentary, events, news, property as prop, shares
from .config import (BOE_MPC_DATES, MANUAL_OBSERVATIONS_CSV, PROPERTY_SPREADS, PROPERTY_TABLE_C,
                     REPORTS_DIR, SERIES, TIMEZONE)
from .metrics import movement, trend_label
from .models import Observation
from .sources import boe, equities, fred, investegate, ons, placenorthwest, treasury
from .store import Store, load_manual

log = logging.getLogger("monitor")


def london_now() -> datetime:
    return datetime.now(ZoneInfo(TIMEZONE))


def collect_shares(px_store: Store, report_date: date, run_id: str, offline: bool) -> tuple[list[str], dict]:
    """Share prices (provider data, then cited manual closes) and company announcements."""
    failures: list[str] = []
    meta: dict = {}
    if not offline:
        res = equities.fetch(report_date)
        failures += res.errors
        meta.update(res.meta)
        for e in res.errors:
            px_store.log_failure(run_id, e)
        for ob in res.observations:
            if ob.obs_date <= report_date:
                px_store.upsert(ob, run_id)
        tidms = [w["investegate_tidm"] for w in equities.load_watchlist() if w.get("investegate_tidm")]
        ann = investegate.fetch_and_store(tidms, report_date.isoformat())
        failures += ann.errors
        meta.update(ann.meta)
        failures += placenorthwest.fetch_and_store(report_date).errors
    for ob in equities.load_manual_prices():
        if ob.obs_date <= report_date:
            px_store.upsert(ob, run_id)
    return failures, meta


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


def build_context(store: Store, report_date: date, failures: list[str], meta: dict, run_id: str,
                  px_store: Store | None = None) -> dict:
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
    # ---- listed property shares, REIT valuation, announcements, news ----
    px_store = px_store or Store(shares.SHARE_PRICES_CSV)
    fundamentals = shares.load_fundamentals(report_date)
    share_rows = shares.share_rows(px_store, report_date, meta.get("market_cap", {}), fundamentals)
    fx_hist = store.history("FX_USD_PER_GBP", report_date)
    stories, news_problems = news.for_date(report_date)
    recent_ann = [a for a in investegate.load()
                  if a["datetime"][:10] >= (report_date - timedelta(days=14)).isoformat()]
    recent_ann.sort(key=lambda a: a["datetime"], reverse=True)
    ctx.update({
        "share_rows": share_rows,
        "share_primary": [r for r in share_rows if r.w["group"] in ("primary", "uk_comparator")] +
                         [r for r in share_rows if r.w["ticker"] == "PLD"],
        "share_secondary": [r for r in share_rows if r.w["group"] == "international" and r.w["ticker"] != "PLD"],
        "share_alerts": [r for r in share_rows if r.alert],
        "corporate_actions": [r for r in share_rows if r.w.get("corporate_action")],
        "valuation": shares.valuation_rows(share_rows, fundamentals),
        "metric_labels": shares.PRIMARY_METRICS,
        "look_through": shares.segro_look_through(share_rows, fx_hist[-1] if fx_hist else None),
        "fmt_cap": shares.fmt_cap,
        "announcements": recent_ann,
        "stories": stories,
        "news_sections": news.by_section(stories),
        "news_problems": news_problems,
        "pnw_headlines": placenorthwest.headlines_since(
            report_date, {r["url"].rstrip("/") for r in news.load()}),
        "pnw_window_start": placenorthwest.window_start(report_date),
        "nw_deals": [s for s in stories if s.label == "NORTH WEST INDUSTRIAL" and s.nw_transaction == "yes"],
        "yield_alerts": [r for r in prop_rows if r.latest and r.move_bp and
                         (report_date - (r.latest.publication_date or r.latest.evidence_date)).days <= 7],
    })
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
    px_store = Store(shares.SHARE_PRICES_CSV)
    failures, meta = collect(store, report_date, run_id, offline)
    f2, m2 = collect_shares(px_store, report_date, run_id, offline)
    failures += f2
    meta.update(m2)
    ctx = build_context(store, report_date, failures, meta, run_id, px_store)

    out_dir = REPORTS_DIR / f"{report_date:%Y}" / f"{report_date:%m}"
    chart_dir = out_dir / "charts"
    ctx["bond_chart"], ctx["bond_chart_note"] = charts.bond_chart(
        store, report_date, chart_dir / f"bonds-{report_date.isoformat()}.png")
    ctx["spread_chart"], ctx["spread_chart_note"] = charts.spread_chart(
        ctx["spread_hist"], chart_dir / f"spreads-{report_date.isoformat()}.png", report_date,
        {s.label for s in ctx["spreads"] if s.prop and (report_date - s.prop.evidence_date).days > 90})

    md_path, html_path = render(ctx, out_dir)
    store.save()
    px_store.save()
    status = ("ok" if not failures else "partial") + (" (offline)" if offline else "")
    store.log_run({"run_id": run_id, "report_date": report_date.isoformat(), "started_at": started.isoformat(),
                   "finished_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                   "status": status, "inserted": store.counts["inserted"], "revised": store.counts["revised"],
                   "failures": len(failures), "failure_detail": " | ".join(failures)[:2000]})
    return {"markdown": md_path, "html": html_path, "failures": failures, "status": status}
