"""US Treasury daily par yield curve rates (CMT)."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime

from ..config import SERIES
from ..http import get
from ..models import FetchResult, Observation
from . import now_iso

NAME = "US Treasury - Daily Treasury Par Yield Curve Rates"
URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
       "daily-treasury-rates.csv/{year}/all?type=daily_treasury_yield_curve"
       "&field_tdr_date_value={year}&page&_format=csv")
PAGE = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
        "TextView?type=daily_treasury_yield_curve&field_tdr_date_value={year}")


def parse(text: str, year: int, retrieved: str) -> list[Observation]:
    obs = []
    cols = {sid: m["ust"] for sid, m in SERIES.items() if "ust" in m}
    for row in csv.DictReader(io.StringIO(text)):
        d = datetime.strptime(row["Date"], "%m/%d/%Y").date()
        for sid, col in cols.items():
            v = (row.get(col) or "").strip()
            if v:
                obs.append(Observation(sid, d, float(v), NAME, PAGE.format(year=year),
                                       "official", d, retrieved,
                                       "Par yield, constant maturity (CMT), end of day"))
    return obs


def fetch(as_of: date) -> FetchResult:
    res = FetchResult(NAME)
    years = {as_of.year}
    if as_of.month <= 2:          # make sure 30-day windows span the year boundary
        years.add(as_of.year - 1)
    for y in sorted(years):
        try:
            res.observations += parse(get(URL.format(year=y)).text, y, now_iso())
        except Exception as e:  # noqa: BLE001
            res.errors.append(f"{NAME} {y}: {e}")
    return res
