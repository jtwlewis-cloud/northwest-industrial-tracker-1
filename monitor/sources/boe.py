"""Bank of England Interactive Statistical Database (IADB).

Series used:
  IUDSNPY  5-year nominal par yield (fitted curve)
  IUDMNPY  10-year nominal par yield (fitted curve)
  IUDBEDR  Bank Rate
  IUDSOIA  SONIA overnight fixing

The BoE website sits behind a bot-protection layer that can refuse automated
clients (HTTP 403). This adapter identifies itself honestly and does not try to
get round that; a refusal is reported as a data failure and the system falls
back to FRED (SONIA) or verified manual entries (gilts, Bank Rate).
"""
from __future__ import annotations

import csv
import io
import time
from datetime import date, datetime, timedelta

from ..config import SERIES
from ..http import get
from ..models import FetchResult, Observation
from . import now_iso

NAME = "Bank of England Database (IADB)"
URL = ("https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp?csv.x=yes"
       "&Datefrom={start}&Dateto=now&SeriesCodes={codes}&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N")
PAGE = "https://www.bankofengland.co.uk/boeapps/database/fromshowcolumns.asp?SeriesCodes={code}&UsingCodes=Y"

NOTES = {
    "IUDSNPY": "BoE fitted nominal par yield (5Y) - curve estimate, not a benchmark gilt redemption yield",
    "IUDMNPY": "BoE fitted nominal par yield (10Y) - curve estimate, not a benchmark gilt redemption yield",
    "IUDBEDR": "Official Bank Rate",
    "IUDSOIA": "SONIA overnight fixing (not term SONIA, not SONIA swap)",
}


def parse(text: str, retrieved: str) -> list[Observation]:
    code_to_sid = {m["boe"]: sid for sid, m in SERIES.items() if "boe" in m}
    obs = []
    for row in csv.DictReader(io.StringIO(text)):
        raw = row.get("DATE") or row.get("Date")
        if not raw:
            continue
        d = datetime.strptime(raw.strip(), "%d %b %Y").date()
        for code, sid in code_to_sid.items():
            v = (row.get(code) or "").strip()
            if v:
                obs.append(Observation(sid, d, float(v), NAME, PAGE.format(code=code),
                                       "official", None, retrieved, NOTES[code]))
    return obs


def fetch(as_of: date, attempts: int = 4, backoff: float = 20.0) -> FetchResult:
    res = FetchResult(NAME)
    codes = ",".join(m["boe"] for m in SERIES.values() if "boe" in m)
    start = (as_of - timedelta(days=420)).strftime("%d/%b/%Y")
    last_err = ""
    for attempt in range(attempts):
        try:
            r = get(URL.format(start=start, codes=codes), allow_redirects=False)
            if r.status_code == 200 and "DATE" in r.text[:200]:
                res.observations = parse(r.text, now_iso())
                return res
            last_err = f"unexpected response (HTTP {r.status_code}); BoE may be refusing automated access"
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
        if attempt < attempts - 1:
            time.sleep(backoff * (attempt + 1))
    res.errors.append(f"{NAME}: {last_err} (after {attempts} attempts)")
    return res
