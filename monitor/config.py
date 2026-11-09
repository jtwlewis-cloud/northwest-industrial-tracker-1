"""Static configuration: series definitions, sources, calendars and paths."""
from __future__ import annotations

from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"
TEMPLATES_DIR = ROOT / "templates"

OBSERVATIONS_CSV = DATA_DIR / "observations.csv"
MANUAL_OBSERVATIONS_CSV = DATA_DIR / "manual_observations.csv"
PROPERTY_YIELDS_CSV = DATA_DIR / "property_yields.csv"
EVENTS_CSV = DATA_DIR / "events.csv"
AUDIT_LOG_CSV = DATA_DIR / "audit_log.csv"
RUN_LOG_CSV = DATA_DIR / "run_log.csv"
ANALYST_NOTES_DIR = DATA_DIR / "analyst_notes"

TIMEZONE = "Europe/London"
REPORT_HOUR = 8

# Honest client identification. Do not impersonate a browser.
USER_AGENT = "nw-market-monitor/1.0 (+https://github.com/jtwlewis-cloud/northwest-industrial-tracker-1)"

# Source priority: lower number wins when two sources give the same series/date.
SOURCE_PRIORITY = {
    "official": 1,      # central bank / statistics office / Treasury feed (incl. FRED republications)
    "manual": 2,        # manually verified entry with a citation (data/manual_observations.csv)
    "secondary": 3,     # market data vendor / press report
    "derived": 4,       # calculated by this system
}

# ---------------------------------------------------------------------------
# Market series. "freq" drives staleness checks and change windows.
# ---------------------------------------------------------------------------
SERIES: dict[str, dict] = {
    # UK gilts. Primary: BoE fitted nominal par yields (IADB). These are curve-fitted
    # par yields, NOT benchmark gilt redemption yields - the report labels them as such.
    "UK_GILT_2Y": {"label": "UK 2-Year gilt", "freq": "daily", "unit": "%"},
    "UK_GILT_5Y": {"label": "UK 5-Year gilt", "freq": "daily", "unit": "%", "boe": "IUDSNPY"},
    "UK_GILT_10Y": {"label": "UK 10-Year gilt", "freq": "daily", "unit": "%", "boe": "IUDMNPY"},
    "UK_GILT_30Y": {"label": "UK 30-Year gilt", "freq": "daily", "unit": "%"},
    # US Treasuries: US Treasury daily par yield curve (CMT).
    "US_UST_2Y": {"label": "US 2-Year Treasury", "freq": "daily", "unit": "%", "ust": "2 Yr", "fred": "DGS2"},
    "US_UST_5Y": {"label": "US 5-Year Treasury", "freq": "daily", "unit": "%", "ust": "5 Yr", "fred": "DGS5"},
    "US_UST_10Y": {"label": "US 10-Year Treasury", "freq": "daily", "unit": "%", "ust": "10 Yr", "fred": "DGS10"},
    "US_UST_30Y": {"label": "US 30-Year Treasury", "freq": "daily", "unit": "%", "ust": "30 Yr", "fred": "DGS30"},
    # Rates
    "BOE_BANK_RATE": {"label": "BoE Bank Rate", "freq": "event", "unit": "%", "boe": "IUDBEDR"},
    "SONIA": {"label": "SONIA (overnight fixing)", "freq": "daily", "unit": "%", "boe": "IUDSOIA", "fred": "IUDSOIA"},
    "UK_SONIA_SWAP_5Y": {"label": "5Y SONIA swap rate", "freq": "daily", "unit": "%"},
    "FED_TARGET_LOWER": {"label": "Fed funds target (lower)", "freq": "event", "unit": "%", "fred": "DFEDTARL"},
    "FED_TARGET_UPPER": {"label": "Fed funds target (upper)", "freq": "event", "unit": "%", "fred": "DFEDTARU"},
    # Inflation (annual rates, monthly; obs_date = first day of reference month)
    "UK_CPI_YOY": {"label": "UK CPI (12m)", "freq": "monthly", "unit": "%", "ons": "d7g7"},
    "UK_CPIH_YOY": {"label": "UK CPIH (12m)", "freq": "monthly", "unit": "%", "ons": "l55o"},
    "UK_CORE_CPI_YOY": {"label": "UK core CPI (12m, ex energy, food, alcohol & tobacco)", "freq": "monthly", "unit": "%", "ons": "dko8"},
    "US_CPI_YOY": {"label": "US CPI-U (12m, NSA)", "freq": "monthly", "unit": "%", "fred_index": "CPIAUCNS"},
    "US_CORE_CPI_YOY": {"label": "US core CPI-U (12m, NSA)", "freq": "monthly", "unit": "%", "fred_index": "CPILFENS"},
}

TABLE_A = ["UK_GILT_5Y", "UK_GILT_10Y", "US_UST_5Y", "US_UST_10Y"]
TABLE_A_REF = ["UK_GILT_2Y", "UK_GILT_30Y", "US_UST_2Y", "US_UST_30Y"]

# ---------------------------------------------------------------------------
# Property: which register series feeds each headline row (Table C) and
# which ones feed the gilt-spread calculation (Table D). Keep the basis
# consistent across the spread rows.
# ---------------------------------------------------------------------------
PROPERTY_TABLE_C = [
    ("UK Industrial & Logistics", "KF_PRIME_DISTRIBUTION_20Y"),
    ("Prime Distribution Warehouses", "KF_PRIME_DISTRIBUTION_15Y_OMRR"),
    ("South East Industrial", "KF_SE_ESTATES"),
    ("Greater London Industrial", "KF_GREATER_LONDON_ESTATES"),
    ("Prime Multi-let Industrial (Rest of UK)", "KF_REST_OF_UK_ESTATES"),
    ("North West Industrial", "KF_MANCHESTER_INDUSTRIAL"),
    ("UK Logistics (average of 71 submarkets)", "CW_UK_LOGISTICS_AVG"),
    ("London West End Offices", "KF_WEST_END_PRIME_CORE"),
    ("London City Offices", "KF_CITY_PRIME"),
    ("Manchester Offices", "KF_MAJOR_REGIONAL_OFFICES_10Y"),
    ("Regional UK Offices", "KF_MAJOR_REGIONAL_OFFICES_10Y"),
]

PROPERTY_SPREADS = [
    ("Prime UK industrial less 10Y gilt", "KF_PRIME_DISTRIBUTION_20Y"),
    ("Prime London (City) office less 10Y gilt", "KF_CITY_PRIME"),
    ("Prime London (West End) office less 10Y gilt", "KF_WEST_END_PRIME_CORE"),
    ("Prime Manchester office less 10Y gilt", "KF_MAJOR_REGIONAL_OFFICES_10Y"),
    ("North West industrial less 10Y gilt", "KF_MANCHESTER_INDUSTRIAL"),
]

# ---------------------------------------------------------------------------
# Scheduled policy meetings (dates are announcement dates).
# Update annually from the official calendars.
# ---------------------------------------------------------------------------
BOE_MPC_DATES = [date(2026, 2, 5), date(2026, 3, 19), date(2026, 4, 30), date(2026, 6, 18),
                 date(2026, 7, 30), date(2026, 9, 17), date(2026, 11, 5), date(2026, 12, 17)]
FOMC_DECISION_DATES = [date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2026, 6, 17),
                       date(2026, 7, 29), date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9)]
BOE_MPC_SOURCE = "https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates"
FOMC_SOURCE = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"

STALE_DAILY_BUSINESS_DAYS = 3   # daily series older than this are flagged stale
MIN_POINTS_FOR_CHART = 10       # verified points required before a chart is drawn
