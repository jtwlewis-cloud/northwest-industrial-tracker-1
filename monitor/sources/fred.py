"""FRED (St. Louis Fed) - used for SONIA (BoE republication), Fed target range,
US CPI index levels and a fallback for US Treasury yields."""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta

from ..config import SERIES
from ..http import get
from ..models import FetchResult, Observation
from . import now_iso

CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={start}"
PAGE = "https://fred.stlouisfed.org/series/{sid}"

# series_id -> (FRED id, description)
DIRECT = {
    "SONIA": ("IUDSOIA", "FRED republication of Bank of England SONIA overnight fixing"),
    "FED_TARGET_LOWER": ("DFEDTARL", "FRED: Federal Reserve target range lower limit"),
    "FED_TARGET_UPPER": ("DFEDTARU", "FRED: Federal Reserve target range upper limit"),
    "FX_USD_PER_GBP": ("DEXUSUK", "FRED: US dollars per pound sterling, noon buying rate (H.10)"),
}
UST_FALLBACK = {sid: m["fred"] for sid, m in SERIES.items() if sid.startswith("US_UST") and "fred" in m}


def _series(fred_id: str, start: date) -> list[tuple[date, float]]:
    text = get(CSV.format(sid=fred_id, start=start.isoformat())).text
    out = []
    for row in csv.reader(io.StringIO(text)):
        if not row or row[0] == "observation_date":
            continue
        if len(row) > 1 and row[1] not in ("", "."):
            out.append((date.fromisoformat(row[0]), float(row[1])))
    return out


def yoy_from_index(points: list[tuple[date, float]]) -> list[tuple[date, float, float, float]]:
    """Annual % change. Returns (month, yoy, index, base). Skips months whose
    base month is missing (e.g. Oct-2025, not published during the US shutdown)."""
    lookup = dict(points)
    out = []
    for d, v in points:
        base = lookup.get(date(d.year - 1, d.month, 1))
        if base:
            out.append((d, round((v / base - 1) * 100, 1), v, base))
    return out


def fetch(as_of: date, include_ust_fallback: bool = False) -> FetchResult:
    res = FetchResult("FRED")
    ts = now_iso()
    start = as_of - timedelta(days=420)
    for sid, (fid, desc) in DIRECT.items():
        try:
            for d, v in _series(fid, start):
                res.observations.append(Observation(sid, d, v, f"FRED {fid}", PAGE.format(sid=fid),
                                                    "official", None, ts, desc))
        except Exception as e:  # noqa: BLE001
            res.errors.append(f"FRED {fid}: {e}")

    for sid in ("US_CPI_YOY", "US_CORE_CPI_YOY"):
        fid = SERIES[sid]["fred_index"]
        try:
            pts = _series(fid, as_of - timedelta(days=800))
            for d, yoy, idx, base in yoy_from_index(pts):
                res.observations.append(Observation(
                    sid, d, yoy, f"BLS CPI via FRED {fid}", PAGE.format(sid=fid), "official", None, ts,
                    f"Calculated 12m change from NSA index {idx} / {base} (BLS publishes the official rounded rate)"))
            months = {d for d, _ in pts}
            latest = max(months) if months else None
            if latest and date(latest.year - 1, latest.month, 1) not in months:
                res.errors.append(f"{sid}: base month for {latest:%b %Y} missing in FRED; 12m rate not verified")
        except Exception as e:  # noqa: BLE001
            res.errors.append(f"FRED {fid}: {e}")

    if include_ust_fallback:
        for sid, fid in UST_FALLBACK.items():
            try:
                for d, v in _series(fid, start):
                    res.observations.append(Observation(sid, d, v, f"FRED {fid}", PAGE.format(sid=fid),
                                                        "official", None, ts, "FRED republication of Treasury CMT"))
            except Exception as e:  # noqa: BLE001
                res.errors.append(f"FRED {fid}: {e}")
    return res
