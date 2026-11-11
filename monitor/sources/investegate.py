"""Company regulatory announcements (RNS and other RIS) from Investegate.

Routine filings (Form 8 disclosures, own-share transactions, holdings,
voting-rights and PDMR notices) are filtered out; everything else is kept as a
potential "major company announcement".
"""
from __future__ import annotations

import csv
import html
import re
from datetime import datetime

from ..config import DATA_DIR
from ..http import get
from ..models import FetchResult

ANNOUNCEMENTS_CSV = DATA_DIR / "announcements.csv"
FIELDS = ["tidm", "datetime", "source", "headline", "url", "category", "first_seen"]
URL = "https://www.investegate.co.uk/company/{t}"
NOISE = re.compile(r"Form ?8|Transaction in Own|Holding\(s\)|Holdings? in Company|Voting Rights|PDMR|"
                   r"Block ?listing|Director/PDMR|Disclosure Table|Rule 2\.9|Form8", re.I)
CATEGORIES = [
    ("Results", r"result|interim|half[- ]year|annual report|full[- ]year"),
    ("Trading update", r"trading update|trading statement|business update"),
    ("M&A / corporate action", r"offer|scheme|acquisition|merger|disposal|combination|cancellation|admission|"
                               r"general meeting|circular|court"),
    ("Capital / debt", r"equity issue|placing|retail offer|bond|notes|refinanc|debt|facility"),
    ("Dividend", r"dividend"),
    ("Asset / leasing", r"pre-let|letting|logistics facility|development|sq ft|warehouse"),
    ("Board", r"director|chair|ceo|cfo|retirement|appointment|board"),
]


def classify(headline: str) -> str:
    for name, pat in CATEGORIES:
        if re.search(pat, headline, re.I):
            return name
    return "Other"


def parse(tidm: str, page: str) -> list[dict]:
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, flags=re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S)
        if len(tds) < 4:
            continue
        txt = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t))).strip() for t in tds]
        link = re.search(r'href="(https://www\.investegate\.co\.uk/announcement/[^"]+)"', tr)
        try:
            dt = datetime.strptime(f"{txt[0]} {txt[1]}", "%d %b %Y %I:%M %p")
        except ValueError:
            continue
        head = txt[3]
        if NOISE.search(head):
            continue
        rows.append({"tidm": tidm, "datetime": dt.isoformat(timespec="minutes"), "source": txt[2],
                     "headline": head, "url": link.group(1) if link else URL.format(t=tidm),
                     "category": classify(head)})
    return rows


def load() -> list[dict]:
    if not ANNOUNCEMENTS_CSV.exists():
        return []
    with ANNOUNCEMENTS_CSV.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fetch_and_store(tidms: list[str], today: str) -> FetchResult:
    res = FetchResult("Investegate announcements")
    known = {r["url"] + r["headline"] for r in load()}
    new = []
    for t in tidms:
        try:
            for r in parse(t, get(URL.format(t=t)).text):
                if r["url"] + r["headline"] not in known:
                    r["first_seen"] = today
                    new.append(r)
                    known.add(r["url"] + r["headline"])
        except Exception as e:  # noqa: BLE001
            res.errors.append(f"Investegate {t}: {e}")
    if new:
        exists = ANNOUNCEMENTS_CSV.exists()
        with ANNOUNCEMENTS_CSV.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if not exists:
                w.writeheader()
            w.writerows(new)
    res.meta["new_announcements"] = new
    return res
