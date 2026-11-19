"""New North West industrial listings, from the agents' listings sweep.

The sweep runs separately and publishes its daily digest on the branch
claude/magical-ride-4nijqh as `output/daily/Latest New Listings.md`. Each
briefing fetches that branch and includes the digest only if its sweep date is
the report date; otherwise it states that today's sweep did not complete.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import date

from .config import ROOT

BRANCH = "claude/magical-ride-4nijqh"
PATH = "output/daily/Latest New Listings.md"
NOT_COMPLETE = "Today's listings sweep did not complete"


@dataclass
class ListingsDigest:
    ok: bool                      # sweep date == report date
    sweep_date: date | None = None
    sweep_label: str = ""         # e.g. "2026-11-15 09:34 UTC"
    body: str = ""                # markdown to show (heading removed)
    new_count: int | None = None
    new_sqft: int | None = None
    largest: dict | None = None   # {"name", "url", "location", "sqft", "agents"}
    error: str = ""
    rows: list[dict] = field(default_factory=list)


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=120)


def fetch_branch() -> str:
    r = _git("fetch", "origin", BRANCH)
    return "" if r.returncode == 0 else (r.stderr.strip().splitlines() or ["git fetch failed"])[-1]


def read_file() -> str | None:
    r = _git("show", f"origin/{BRANCH}:{PATH}")
    return r.stdout if r.returncode == 0 else None


def _num(s: str) -> int | None:
    s = s.replace(",", "").strip()
    return int(s) if s.isdigit() else None


def parse(text: str, report_date: date) -> ListingsDigest:
    lines = text.splitlines()
    head = next((ln for ln in lines if ln.strip()), "")
    m = re.search(r"sweep\s+(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2})\s*UTC)?", head)
    if not m:
        return ListingsDigest(False, error="sweep date not found in the digest header")
    d = date.fromisoformat(m.group(1))
    label = m.group(1) + (f" {m.group(2)} UTC" if m.group(2) else "")
    body = "\n".join(lines[lines.index(head) + 1:]).strip()
    dg = ListingsDigest(d == report_date, d, label, body)
    mc = re.search(r"New to market:\*\*\s*([\d,]+)\s+propert\w*,\s*([\d,]+)\s*sq ft", text)
    if mc:
        dg.new_count, dg.new_sqft = _num(mc.group(1)), _num(mc.group(2))
    # first table = new listings: | [Name](url) | Location | sq ft | Status | Agents |
    for ln in lines:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) >= 5 and cells[0].startswith("["):
            lm = re.match(r"\[(.*?)\]\((.*?)\)", cells[0])
            dg.rows.append({"name": lm.group(1) if lm else cells[0], "url": lm.group(2) if lm else "",
                            "location": cells[1], "sqft": _num(cells[2]), "status": cells[3], "agents": cells[4]})
    sized = [r for r in dg.rows if r["sqft"]]
    if sized:
        dg.largest = max(sized, key=lambda r: r["sqft"])
    if dg.new_count is None and dg.rows:
        dg.new_count = len(dg.rows)
    return dg


def load(report_date: date, fetch: bool = True) -> ListingsDigest:
    err = fetch_branch() if fetch else ""
    text = read_file()
    if text is None:
        return ListingsDigest(False, error=f"digest file not readable ({err or 'missing on branch'})")
    dg = parse(text, report_date)
    if err:
        dg.error = f"git fetch failed ({err}); used last fetched copy"
    return dg


def summary_line(dg: ListingsDigest) -> str:
    """One line for the phone summary."""
    if not dg.ok:
        return NOT_COMPLETE + "."
    s = f"{dg.new_count} new North West industrial listings"
    if dg.new_sqft:
        s += f" ({dg.new_sqft:,} sq ft)"
    if dg.largest:
        short = dg.largest["name"].split(",")[0].strip()      # table names are truncated addresses
        s += f"; largest {short}, {dg.largest['location']}, {dg.largest['sqft']:,} sq ft"
    return s + "."
