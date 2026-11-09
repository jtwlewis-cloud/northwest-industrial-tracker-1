"""Key events in the next seven days: scheduled central-bank meetings (config),
ONS next-release dates (from the ONS API) and a curated calendar in data/events.csv."""
from __future__ import annotations

import csv
from datetime import date, timedelta

from .config import BOE_MPC_DATES, BOE_MPC_SOURCE, EVENTS_CSV, FOMC_DECISION_DATES, FOMC_SOURCE


def upcoming(report_date: date, ons_meta: dict, days: int = 7) -> list[dict]:
    end = report_date + timedelta(days=days)
    ev = []
    for d in BOE_MPC_DATES:
        if report_date <= d <= end:
            ev.append({"date": d, "event": "Bank of England MPC decision", "source_url": BOE_MPC_SOURCE})
    for d in FOMC_DECISION_DATES:
        if report_date <= d <= end:
            ev.append({"date": d, "event": "FOMC rate decision", "source_url": FOMC_SOURCE})
    seen = set()
    for sid, meta in (ons_meta or {}).items():
        nr = meta.get("next_release")
        if not nr or nr in seen:
            continue
        seen.add(nr)
        try:
            from datetime import datetime
            d = datetime.strptime(nr, "%d %B %Y").date()
        except ValueError:
            continue
        if report_date <= d <= end:
            ev.append({"date": d, "event": "ONS consumer price inflation release (07:00)",
                       "source_url": "https://www.ons.gov.uk/releasecalendar"})
    if EVENTS_CSV.exists():
        with EVENTS_CSV.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                d = date.fromisoformat(r["date"])
                if report_date <= d <= end:
                    ev.append({"date": d, "event": r["event"], "source_url": r.get("source_url", "")})
    # de-duplicate on (date, event)
    uniq = {(e["date"], e["event"]): e for e in ev}
    return sorted(uniq.values(), key=lambda e: e["date"])


def next_after(dates: list[date], d: date) -> date | None:
    later = [x for x in dates if x > d]
    return later[0] if later else None
