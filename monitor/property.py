"""Prime property yield evidence register and property-vs-gilt spreads.

Property yields are NOT fetched automatically: agents publish them monthly or
quarterly in PDFs and web reports, so each figure goes into
data/property_yields.csv with its basis (NIY / equivalent yield / not stated),
period, publication date and source URL. The latest entry is carried forward
and labelled with its original date. A movement is reported only when a newer
published entry differs from the previous one for the same series.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date

from .config import PROPERTY_YIELDS_CSV
from .metrics import bp
from .models import Observation

FIELDS = ["series_id", "sector", "description", "provider", "basis", "low", "high", "period",
          "evidence_date", "publication_date", "source_url", "sentiment", "substitution_note", "notes"]


@dataclass
class PropertyYield:
    series_id: str
    sector: str
    description: str
    provider: str
    basis: str
    low: float
    high: float
    period: str
    evidence_date: date
    publication_date: date | None
    source_url: str
    sentiment: str
    substitution_note: str
    notes: str

    @property
    def mid(self) -> float:
        return round((self.low + self.high) / 2, 3)

    @property
    def display(self) -> str:
        return f"{self.low:.2f}%" if self.low == self.high else f"{self.low:.2f}–{self.high:.2f}%"


def load(path=PROPERTY_YIELDS_CSV) -> dict[str, list[PropertyYield]]:
    out: dict[str, list[PropertyYield]] = {}
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if not r.get("low") or not r.get("source_url"):
                continue   # never accept an unsourced yield
            low = float(r["low"])
            high = float(r["high"]) if r.get("high") else low
            py = PropertyYield(
                r["series_id"], r["sector"], r["description"], r["provider"], r["basis"] or "Not stated",
                low, high, r["period"], date.fromisoformat(r["evidence_date"]),
                date.fromisoformat(r["publication_date"]) if r.get("publication_date") else None,
                r["source_url"], r.get("sentiment", ""), r.get("substitution_note", ""), r.get("notes", ""))
            out.setdefault(py.series_id, []).append(py)
    for v in out.values():
        v.sort(key=lambda p: p.evidence_date)
    return out


@dataclass
class PropertyRow:
    label: str
    latest: PropertyYield | None
    previous: PropertyYield | None
    move_bp: float | None
    age_days: int | None


def table_rows(register, mapping, report_date: date) -> list[PropertyRow]:
    rows = []
    for label, sid in mapping:
        hist = [p for p in register.get(sid, []) if p.evidence_date <= report_date]
        latest = hist[-1] if hist else None
        prev = hist[-2] if len(hist) > 1 else None
        move = bp(latest.mid, prev.mid) if latest and prev else None
        age = (report_date - latest.evidence_date).days if latest else None
        rows.append(PropertyRow(label, latest, prev, move, age))
    return rows


@dataclass
class SpreadRow:
    label: str
    prop: PropertyYield | None
    gilt: Observation | None                 # latest 10Y gilt
    spread_bp: float | None                  # today: latest property yield - latest gilt
    gilt_at_evidence: Observation | None
    spread_at_evidence_bp: float | None      # latest property yield - gilt at its evidence date
    prev_prop: PropertyYield | None
    prev_gilt: Observation | None
    prev_spread_bp: float | None             # previous property yield - gilt at that evidence date
    change_bp: float | None                  # today vs previous comparable spread
    property_contrib_bp: float | None
    gilt_contrib_bp: float | None
    driver: str


def _gilt_on_or_before(gilt_hist: list[Observation], d: date) -> Observation | None:
    c = [o for o in gilt_hist if o.obs_date <= d]
    if not c or (d - c[-1].obs_date).days > 7:
        return None
    return c[-1]


def spreads(register, mapping, gilt_hist: list[Observation], report_date: date) -> list[SpreadRow]:
    """Simple yield spreads (bp): property yield (range midpoint) less UK 10Y gilt.

    The previous comparable spread uses the previous published property figure and the
    gilt yield on (or within 7 days before) that figure's evidence date. The change is
    split into a property-yield contribution and a gilt contribution."""
    out = []
    gilt_hist = [g for g in gilt_hist if g.obs_date <= report_date]
    g_now = gilt_hist[-1] if gilt_hist else None
    for label, sid in mapping:
        hist = [p for p in register.get(sid, []) if p.evidence_date <= report_date]
        prop = hist[-1] if hist else None
        prev = hist[-2] if len(hist) > 1 else None
        s_now = bp(prop.mid, g_now.value) if prop and g_now else None
        g_ev = _gilt_on_or_before(gilt_hist, prop.evidence_date) if prop else None
        s_ev = bp(prop.mid, g_ev.value) if prop and g_ev else None
        g_prev = _gilt_on_or_before(gilt_hist, prev.evidence_date) if prev else None
        s_prev = bp(prev.mid, g_prev.value) if prev and g_prev else None
        change = round(s_now - s_prev, 1) if s_now is not None and s_prev is not None else None
        pc = bp(prop.mid, prev.mid) if change is not None else None
        gc = -bp(g_now.value, g_prev.value) if change is not None else None
        out.append(SpreadRow(label, prop, g_now, s_now, g_ev, s_ev, prev, g_prev, s_prev, change, pc, gc,
                             _driver(pc, gc) if change is not None else "Not verified"))
    return out


def _driver(pc: float | None, gc: float | None) -> str:
    pc, gc = pc or 0.0, gc or 0.0
    if abs(pc) < 1 and abs(gc) < 1:
        return "Little change"
    if abs(pc) < 1:
        return "Gilt-driven"
    if abs(gc) < 1:
        return "Property-yield-driven"
    if (pc > 0) == (gc > 0):
        return "Both (reinforcing)"
    return "Both (offsetting)"
