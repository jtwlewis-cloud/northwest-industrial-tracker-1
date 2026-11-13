"""Share prices for the listed property watchlist.

Providers, in priority order:
  1. Nasdaq public quote API - US listings (NYSE/Nasdaq). No key needed.
  2. Twelve Data - London and Euronext listings. Needs an API key, which the
     environment's network proxy adds as an `Authorization: apikey ...` header.
     If no key is configured the request fails with 401 and is reported.
  3. data/manual_prices.csv - cited closing prices entered by an analyst
     (source_type "secondary"); used only where no provider data exists.

Yahoo Finance and Stooq refuse automated clients without browser
impersonation, which this project does not do.

Prices are stored in their quote unit: GBX (pence) for London, USD, EUR.
"""
from __future__ import annotations

import csv
import re
from datetime import date, datetime, timedelta

import os

import requests

from ..config import DATA_DIR, USER_AGENT
from ..models import FetchResult, Observation
from . import now_iso

WATCHLIST_CSV = DATA_DIR / "watchlist.csv"
NASDAQ_HIST = "https://api.nasdaq.com/api/quote/{s}/historical?assetclass=stocks&fromdate={f}&todate={t}&limit=400"
NASDAQ_SUMMARY = "https://api.nasdaq.com/api/quote/{s}/summary?assetclass=stocks"
NASDAQ_PAGE = "https://www.nasdaq.com/market-activity/stocks/{s}/historical"
TWELVE = "https://api.twelvedata.com/time_series?symbol={s}&exchange={x}&interval=1day&start_date={f}&outputsize=400"
TWELVE_PAGE = "https://twelvedata.com/markets"
# Set to "1" (environment variable, not a secret) once a Twelve Data key has been saved
# as a network credential for api.twelvedata.com and the host is allowed.
TWELVE_ENABLED = os.environ.get("TWELVEDATA_ENABLED") == "1"

_s = requests.Session()
# Plain client name (still a non-browser, honest identifier): Nasdaq stalls requests whose
# User-Agent contains a URL.
_s.headers.update({"User-Agent": USER_AGENT.split(" ")[0], "Accept": "application/json", "Accept-Encoding": "gzip",
                   "Connection": "close"})


def session() -> requests.Session:
    return _s


def _get(url: str, tries: int = 3) -> requests.Response:
    import time
    last = None
    for i in range(tries):
        try:
            time.sleep(3)          # Nasdaq throttles rapid successive requests
            # fresh request each time: no cookie carry-over between calls
            return requests.get(url, headers=dict(_s.headers), timeout=20)
        except requests.RequestException as e:
            last = e
            time.sleep(5 * (i + 1))
    raise last


def load_watchlist() -> list[dict]:
    with WATCHLIST_CSV.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _num(s: str) -> float | None:
    s = re.sub(r"[^0-9.\-]", "", s or "")
    return float(s) if s not in ("", "-", ".") else None


def _nasdaq(w: dict, start: date, end: date, res: FetchResult, ts: str) -> None:
    sym = w["nasdaq_symbol"]
    r = _get(NASDAQ_HIST.format(s=sym, f=start.isoformat(), t=end.isoformat()))
    r.raise_for_status()
    rows = ((r.json().get("data") or {}).get("tradesTable") or {}).get("rows") or []
    if not rows:
        raise RuntimeError("no rows returned")
    for row in rows:
        d = datetime.strptime(row["date"], "%m/%d/%Y").date()
        v = _num(row["close"])
        if v is not None:
            res.observations.append(Observation(f"PX:{w['ticker']}", d, v, "Nasdaq (official close)",
                                                NASDAQ_PAGE.format(s=sym.lower()), "official", None, ts,
                                                "End-of-day close, USD"))
    try:
        r2 = _get(NASDAQ_SUMMARY.format(s=sym))
        sd = ((r2.json().get("data") or {}).get("summaryData") or {})
        mc = _num((sd.get("MarketCap") or {}).get("value", ""))
        if mc:
            res.meta.setdefault("market_cap", {})[w["ticker"]] = {
                "value": mc, "currency": "USD", "as_of": end.isoformat(), "source": "Nasdaq",
                "url": f"https://www.nasdaq.com/market-activity/stocks/{sym.lower()}"}
    except Exception as e:  # noqa: BLE001
        res.errors.append(f"Nasdaq market cap {sym}: {e}")


def _twelvedata(w: dict, start: date, res: FetchResult, ts: str) -> None:
    r = _get(TWELVE.format(s=w["twelvedata_symbol"], x=w["twelvedata_exchange"], f=start.isoformat()), tries=1)
    if r.status_code in (401, 403):
        raise RuntimeError("no Twelve Data API key configured (HTTP %d)" % r.status_code)
    r.raise_for_status()
    js = r.json()
    if js.get("status") == "error":
        raise RuntimeError(js.get("message", "error"))
    cur = (js.get("meta") or {}).get("currency", "")
    for v in js.get("values", []):
        d = date.fromisoformat(v["datetime"][:10])
        px = float(v["close"])
        # Twelve Data quotes LSE shares in GBp (pence); keep pence.
        res.observations.append(Observation(f"PX:{w['ticker']}", d, px, "Twelve Data (end of day)", TWELVE_PAGE,
                                            "official", None, ts, f"End-of-day close, {cur or w['quote_unit']}"))


def fetch(as_of: date) -> FetchResult:
    res = FetchResult("Share prices")
    ts = now_iso()
    start = date(as_of.year - 1, 12, 1)            # covers year-to-date base
    no_feed = []
    for w in load_watchlist():
        try:
            if w.get("nasdaq_symbol"):
                _nasdaq(w, start, as_of, res, ts)
            elif w.get("twelvedata_symbol") and TWELVE_ENABLED:
                _twelvedata(w, start, res, ts)
            else:
                no_feed.append(w["ticker"])
        except Exception as e:  # noqa: BLE001
            res.errors.append(f"Share price {w['ticker']}: {e}")
    if no_feed:
        res.errors.append("No licensed price feed configured for London/Euronext listings ("
                          + ", ".join(no_feed) + "); only cited closes in data/manual_prices.csv are used")
    return res


def load_manual_prices() -> list[Observation]:
    p = DATA_DIR / "manual_prices.csv"
    out = []
    if not p.exists():
        return out
    with p.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("close") and r.get("source_url"):
                out.append(Observation(f"PX:{r['ticker']}", date.fromisoformat(r["date"]), float(r["close"]),
                                       r["source"], r["source_url"], "secondary", None, r.get("retrieved_at", ""),
                                       r.get("notes", "")))
    return out
