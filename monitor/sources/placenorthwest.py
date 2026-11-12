"""Place North West RSS feeds - the primary source for North West property news.

Every run reads the main news feed plus the industrial, offices, retail and
regeneration sector feeds, stores each headline once in data/pnw_feed.csv, and
the report lists every headline published since the previous briefing (Friday
morning onwards on a Monday) in Section 10, linked to the article. Headlines are
reproduced as published; nothing is summarised automatically.
"""
from __future__ import annotations

import csv
import html
import re
from datetime import date, datetime, time, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

from ..config import DATA_DIR
from ..http import get
from ..models import FetchResult

PNW_CSV = DATA_DIR / "pnw_feed.csv"
FIELDS = ["guid", "published", "title", "link", "sectors", "first_seen"]
FEEDS = {
    "": "https://www.placenorthwest.co.uk/feed/",
    "industrial": "https://www.placenorthwest.co.uk/sector/industrial/feed/",
    "offices": "https://www.placenorthwest.co.uk/sector/offices/feed/",
    "retail": "https://www.placenorthwest.co.uk/sector/retail/feed/",
    "regeneration": "https://www.placenorthwest.co.uk/sector/regeneration/feed/",
}
LONDON = ZoneInfo("Europe/London")
INDUSTRIAL_WORDS = re.compile(r"industrial|warehouse|logistic|shed|distribution|sq ft|trafford park|port|"
                              r"manufactur|depot|storage|IOS|enterprise zone", re.I)


def _text(item: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", item, re.S)
    return html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", m.group(1))).strip() if m else ""


def parse(feed_xml: str, sector: str) -> list[dict]:
    out = []
    for item in re.findall(r"<item>(.*?)</item>", feed_xml, re.S):
        link = _text(item, "link")
        pub = _text(item, "pubDate")
        if not link or not pub:
            continue
        dt = parsedate_to_datetime(pub).astimezone(LONDON)
        out.append({"guid": _text(item, "guid") or link, "published": dt.isoformat(timespec="minutes"),
                    "title": _text(item, "title"), "link": link, "sectors": sector})
    return out


def load() -> list[dict]:
    if not PNW_CSV.exists():
        return []
    with PNW_CSV.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fetch_and_store(today: date) -> FetchResult:
    res = FetchResult("Place North West")
    rows = {r["link"]: r for r in load()}
    changed = False
    for sector, url in FEEDS.items():
        try:
            for it in parse(get(url).text, sector):
                cur = rows.get(it["link"])
                if cur is None:
                    it["first_seen"] = today.isoformat()
                    rows[it["link"]] = it
                    changed = True
                elif sector and sector not in cur["sectors"].split("|"):
                    cur["sectors"] = "|".join(s for s in (cur["sectors"].split("|") + [sector]) if s)
                    changed = True
        except Exception as e:  # noqa: BLE001
            res.errors.append(f"Place North West feed {sector or 'news'}: {e}")
    if changed:
        with PNW_CSV.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(sorted(rows.values(), key=lambda r: r["published"], reverse=True))
    return res


def window_start(report_date: date) -> datetime:
    """Previous briefing time: the prior weekday at 06:00 London (Friday for a Monday)."""
    d = report_date - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return datetime.combine(d, time(6, 0), tzinfo=LONDON)


def headlines_since(report_date: date, exclude_urls: set[str]) -> list[dict]:
    start = window_start(report_date)
    end = datetime.combine(report_date, time(6, 30), tzinfo=LONDON)
    out = []
    for r in load():
        dt = datetime.fromisoformat(r["published"])
        if start <= dt <= end and r["link"].rstrip("/") not in exclude_urls:
            r = dict(r)
            r["industrial"] = "industrial" in r["sectors"].split("|") or bool(INDUSTRIAL_WORDS.search(r["title"]))
            r["dt"] = dt
            out.append(r)
    out.sort(key=lambda r: (not r["industrial"], -r["dt"].timestamp()))
    return out
