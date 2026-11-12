"""Listed property share-price monitor and REIT valuation metrics."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, timedelta

from .config import DATA_DIR
from .models import Observation
from .sources.equities import load_watchlist

FUNDAMENTALS_CSV = DATA_DIR / "reit_fundamentals.csv"
SHARE_PRICES_CSV = DATA_DIR / "share_prices.csv"
MOVE_ALERT_PCT = 3.0
SEGRO_EXCHANGE_RATIO = 0.0920           # new Prologis shares per SEGRO share (recommended offer)
SEGRO_CASH_ALTERNATIVE_P = 1031.7       # partial cash alternative, pence per share


def pct(a: float | None, b: float | None) -> float | None:
    if a is None or b in (None, 0):
        return None
    return round((a / b - 1) * 100, 2)


@dataclass
class ShareRow:
    w: dict
    latest: Observation | None = None
    prev: Observation | None = None
    d1: float | None = None
    d5: float | None = None
    m1: float | None = None
    ytd: float | None = None
    ytd_base: Observation | None = None
    market_cap: dict | None = None
    div_yield: float | None = None
    div_basis: str = ""
    alert: bool = False
    stale: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def unit(self) -> str:
        return self.w["quote_unit"]

    def price_str(self) -> str:
        if not self.latest:
            return "Not verified"
        v = self.latest.value
        return {"GBX": f"{v:,.1f}p", "USD": f"${v:,.2f}", "EUR": f"€{v:,.2f}"}.get(self.unit, f"{v:,.2f}")


def _before(hist: list[Observation], d: date) -> Observation | None:
    c = [o for o in hist if o.obs_date <= d]
    return c[-1] if c else None


def load_fundamentals(report_date: date) -> dict[str, dict[str, dict]]:
    """Latest value per (ticker, metric) whose report_date <= report_date."""
    out: dict[str, dict[str, dict]] = {}
    if not FUNDAMENTALS_CSV.exists():
        return out
    with FUNDAMENTALS_CSV.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if not r.get("value") or not r.get("source_url"):
                continue
            if date.fromisoformat(r["report_date"]) > report_date:
                continue
            cur = out.setdefault(r["ticker"], {}).get(r["metric"])
            if cur is None or r["report_date"] >= cur["report_date"]:
                out[r["ticker"]][r["metric"]] = r
    return out


def share_rows(store, report_date: date, market_caps: dict, fundamentals: dict) -> list[ShareRow]:
    rows = []
    for w in load_watchlist():
        # Latest COMPLETED session before the 06:30 UK briefing = any close dated before the report date.
        hist = [o for o in store.history(f"PX:{w['ticker']}") if o.obs_date < report_date]
        r = ShareRow(w)
        if hist:
            r.latest = hist[-1]
            r.prev = hist[-2] if len(hist) > 1 else None
            # a "daily" change needs the previous session, not an older cited close
            r.d1 = pct(r.latest.value, r.prev.value) if r.prev and (r.latest.obs_date - r.prev.obs_date).days <= 5 else None
            r.stale = (report_date - r.latest.obs_date).days > 5
            r.d5 = pct(r.latest.value, hist[-6].value) if len(hist) >= 6 else None
            m = _before(hist[:-1], r.latest.obs_date - timedelta(days=30))
            r.m1 = pct(r.latest.value, m.value) if m and (r.latest.obs_date - m.obs_date).days <= 37 else None
            r.ytd_base = _before(hist, date(r.latest.obs_date.year - 1, 12, 31))
            if r.ytd_base and r.ytd_base.obs_date >= date(r.latest.obs_date.year - 1, 12, 20):
                r.ytd = pct(r.latest.value, r.ytd_base.value)
            r.alert = r.d1 is not None and abs(r.d1) >= MOVE_ALERT_PCT
        f = fundamentals.get(w["ticker"], {})
        r.market_cap = market_caps.get(w["ticker"])
        if not r.market_cap and r.latest and "SHARES_IN_ISSUE" in f:
            shares = float(f["SHARES_IN_ISSUE"]["value"])
            px = r.latest.value / 100 if r.unit == "GBX" else r.latest.value
            ccy = "GBP" if r.unit == "GBX" else r.unit
            r.market_cap = {"value": shares * px, "currency": ccy, "as_of": r.latest.obs_date.isoformat(),
                            "source": f"Price × shares in issue ({f['SHARES_IN_ISSUE']['period']})",
                            "url": f["SHARES_IN_ISSUE"]["source_url"]}
        if r.latest and "DPS_ANNUAL" in f:
            dps = float(f["DPS_ANNUAL"]["value"])
            r.div_yield = round(dps / r.latest.value * 100, 2)
            r.div_basis = f"{f['DPS_ANNUAL']['period']} dividend {dps:g}{'p' if r.unit == 'GBX' else ''}"
        rows.append(r)
    return rows


def fmt_cap(mc: dict | None) -> str:
    if not mc:
        return "Not verified"
    v = mc["value"]
    sym = {"GBP": "£", "USD": "$", "EUR": "€"}.get(mc["currency"], "")
    return f"{sym}{v / 1e9:,.1f}bn" if v >= 1e9 else f"{sym}{v / 1e6:,.0f}m"


@dataclass
class ValuationRow:
    ticker: str
    name: str
    metrics: dict
    price: Observation | None
    premium_to_nta: float | None


PRIMARY_METRICS = [
    ("EPRA_NTA_PS", "EPRA NTA per share"), ("LTV", "Loan-to-value"), ("COST_OF_DEBT", "Average cost of debt"),
    ("WAULT", "WAULT"), ("OCCUPANCY", "Occupancy"), ("LFL_RENT_GROWTH", "Like-for-like rental growth"),
    ("ERV_GROWTH", "ERV growth"), ("DEV_PIPELINE", "Development pipeline"), ("DPS_ANNUAL", "Dividend (annualised)"),
]


def valuation_rows(rows: list[ShareRow], fundamentals: dict) -> list[ValuationRow]:
    out = []
    for r in rows:
        if r.w["group"] != "primary":
            continue
        f = fundamentals.get(r.w["ticker"], {})
        prem = None
        if r.latest and "EPRA_NTA_PS" in f:
            prem = pct(r.latest.value, float(f["EPRA_NTA_PS"]["value"]))
        out.append(ValuationRow(r.w["ticker"], r.w["name"], f, r.latest, prem))
    return out


def segro_look_through(rows: list[ShareRow], fx: Observation | None) -> dict | None:
    """Value of the Prologis share offer per SEGRO share, in pence, from PLD's close and USD/GBP."""
    pld = next((r for r in rows if r.w["ticker"] == "PLD"), None)
    sgro = next((r for r in rows if r.w["ticker"] == "SGRO.L"), None)
    if not pld or not pld.latest or not fx:
        return None
    value_p = SEGRO_EXCHANGE_RATIO * pld.latest.value / fx.value * 100
    out = {"value_p": round(value_p, 1), "pld": pld.latest, "fx": fx, "cash_p": SEGRO_CASH_ALTERNATIVE_P}
    if sgro and sgro.latest:
        out["sgro"] = sgro.latest
        out["spread_pct"] = pct(value_p, sgro.latest.value)
    return out
