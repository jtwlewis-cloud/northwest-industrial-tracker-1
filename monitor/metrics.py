"""Movement calculations (basis points) and staleness checks."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import holidays

from .config import SERIES, STALE_DAILY_BUSINESS_DAYS
from .models import Observation


def bp(a: float | None, b: float | None) -> float | None:
    """Change from b to a in basis points (1 percentage point = 100 bp)."""
    if a is None or b is None:
        return None
    return round((a - b) * 100, 1)


@dataclass
class Movement:
    series_id: str
    latest: Observation | None = None
    previous: Observation | None = None
    d1: float | None = None
    d7: float | None = None
    d30: float | None = None
    ref7: Observation | None = None
    ref30: Observation | None = None
    stale: bool = False
    effective: date | None = None    # event series: date the current value took effect
    mixed_sources: list[str] = field(default_factory=list)   # windows computed across different sources


def _on_or_before(hist: list[Observation], d: date) -> Observation | None:
    cands = [o for o in hist if o.obs_date <= d]
    return cands[-1] if cands else None


def business_days_between(a: date, b: date, cal) -> int:
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if d.weekday() < 5 and d not in cal:
            n += 1
    return n


def calendars(year: int):
    uk = holidays.country_holidays("GB", subdiv="ENG", years=[year - 1, year])
    try:
        us = holidays.financial_holidays("NYSE", years=[year - 1, year])
    except Exception:  # noqa: BLE001
        us = holidays.country_holidays("US", years=[year - 1, year])
    return uk, us


def movement(series_id: str, hist: list[Observation], report_date: date) -> Movement:
    m = Movement(series_id)
    hist = [o for o in hist if o.obs_date <= report_date]
    if not hist:
        return m
    m.latest = hist[-1]
    m.previous = hist[-2] if len(hist) > 1 else None
    freq = SERIES.get(series_id, {}).get("freq", "daily")
    if freq == "daily":
        # A daily change is only meaningful against the immediately preceding trading day
        # that we actually hold; flag a gap if the previous point is > 5 calendar days back.
        if m.previous and (m.latest.obs_date - m.previous.obs_date).days <= 5:
            m.d1 = bp(m.latest.value, m.previous.value)
        m.ref7 = _on_or_before(hist[:-1], m.latest.obs_date - timedelta(days=7))
        m.ref30 = _on_or_before(hist[:-1], m.latest.obs_date - timedelta(days=30))
        # reject reference points that are too far from the target window
        if m.ref7 and (m.latest.obs_date - m.ref7.obs_date).days > 11:
            m.ref7 = None
        if m.ref30 and (m.latest.obs_date - m.ref30.obs_date).days > 37:
            m.ref30 = None
        m.d7 = bp(m.latest.value, m.ref7.value) if m.ref7 else None
        m.d30 = bp(m.latest.value, m.ref30.value) if m.ref30 else None
        uk, us = calendars(report_date.year)
        cal = us if series_id.startswith("US_") else uk
        m.stale = business_days_between(m.latest.obs_date, report_date, cal) > STALE_DAILY_BUSINESS_DAYS
        for label, ref in (("1d", m.previous if m.d1 is not None else None), ("7d", m.ref7), ("30d", m.ref30)):
            if ref and ref.source != m.latest.source:
                m.mixed_sources.append(label)
    elif freq == "monthly":
        m.d1 = bp(m.latest.value, m.previous.value) if m.previous else None
        m.stale = (report_date - m.latest.obs_date).days > 75
    else:  # event-driven (policy rates): previous = last different value
        diff = [o for o in hist[:-1] if o.value != m.latest.value]
        m.previous = diff[-1] if diff else None
        run = [o for o in hist if o.value == m.latest.value and (not m.previous or o.obs_date > m.previous.obs_date)]
        m.effective = run[0].obs_date if run and m.previous else None
        m.d1 = bp(m.latest.value, m.previous.value) if m.previous else None
    return m


def trend_label(values: list[float], tol: float = 0.15) -> str:
    """Classify the last three monthly inflation readings."""
    if len(values) < 3:
        return "Insufficient data"
    a, b, c = values[-3:]
    if c - a > tol and c >= b:
        return "Accelerating"
    if a - c > tol and c <= b:
        return "Moderating"
    return "Broadly stable"
