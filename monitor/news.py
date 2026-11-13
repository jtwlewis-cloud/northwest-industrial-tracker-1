"""Daily property news log.

Stories are researched each morning (by an analyst or the Claude scheduled
task) and appended to data/news_log.csv - one row per story, with
first_reported = the briefing date on which it first appeared. The pipeline:
  * shows only stories first reported on the report date;
  * rejects a story whose URL, or normalised headline, was already reported on
    an earlier date unless it is explicitly marked status=follow-up;
  * never shows a story without a source URL.
"""
from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from datetime import date

from .config import DATA_DIR

NEWS_CSV = DATA_DIR / "news_log.csv"
FIELDS = ["story_id", "first_reported", "pub_date", "label", "rank", "headline", "source", "url", "summary",
          "key_figures", "relevance", "why_matters", "status", "follow_up_of", "nw_transaction", "size_sqft", "region"]
LABELS = ["NORTH WEST INDUSTRIAL", "UK INDUSTRIAL", "PROPERTY INVESTMENT", "OFFICES",
          "PLANNING / DEVELOPMENT", "FINANCE / CAPITAL MARKETS"]
SECTIONS = {
    "industrial": ["UK INDUSTRIAL", "PLANNING / DEVELOPMENT"],
    "north_west": ["NORTH WEST INDUSTRIAL"],
    "offices_investment": ["OFFICES", "PROPERTY INVESTMENT", "FINANCE / CAPITAL MARKETS"],
}


def story_id(url: str) -> str:
    u = re.sub(r"[?#].*$", "", url.strip().lower()).rstrip("/")
    return hashlib.sha1(u.encode()).hexdigest()[:12]


def norm_headline(h: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", h.lower()).strip()


@dataclass
class Story:
    row: dict

    def __getattr__(self, k):
        return self.row.get(k, "")

    @property
    def sqft(self) -> int:
        try:
            return int(float(self.row.get("size_sqft") or 0))
        except ValueError:
            return 0


def load() -> list[dict]:
    if not NEWS_CSV.exists():
        return []
    with NEWS_CSV.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def for_date(report_date: date) -> tuple[list[Story], list[str]]:
    rows = load()
    today = report_date.isoformat()
    earlier_urls = {story_id(r["url"]) for r in rows if r["first_reported"] < today}
    earlier_heads = {norm_headline(r["headline"]) for r in rows if r["first_reported"] < today}
    stories, problems = [], []
    seen = set()
    for r in rows:
        if r["first_reported"] != today:
            continue
        if not r.get("url") or not r.get("headline"):
            problems.append(f"News row without URL/headline skipped: {r.get('headline', '')[:60]}")
            continue
        sid = story_id(r["url"])
        repeat = sid in earlier_urls or norm_headline(r["headline"]) in earlier_heads
        if repeat and r.get("status") != "follow-up":
            problems.append(f"Already reported on an earlier date, not shown as new: {r['headline'][:80]}")
            continue
        if sid in seen:
            problems.append(f"Duplicate story removed: {r['headline'][:80]}")
            continue
        if r.get("label") not in LABELS:
            problems.append(f"Unknown label '{r.get('label')}' for: {r['headline'][:60]}")
        seen.add(sid)
        stories.append(Story(r))
    stories.sort(key=lambda s: int(s.row.get("rank") or 99))
    return stories, problems


def is_north_west(s: Story) -> bool:
    return s.label == "NORTH WEST INDUSTRIAL" or (s.row.get("region") or "").upper() == "NW"


def by_section(stories: list[Story]) -> dict[str, list[Story]]:
    """North West stories (any label) go to the North West section; the rest by label."""
    out = {"north_west": [s for s in stories if is_north_west(s)]}
    for k in ("industrial", "offices_investment"):
        out[k] = [s for s in stories if s.label in SECTIONS[k] and not is_north_west(s)]
    return out
