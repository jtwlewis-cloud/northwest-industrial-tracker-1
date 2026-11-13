"""CLI.

  python -m monitor run [--date YYYY-MM-DD] [--offline]
  python -m monitor gate          # exit 0 if a scheduled run should go ahead now
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from .config import REPORT_HOUR, REPORTS_DIR
from .pipeline import london_now, run


def should_run_now(now=None) -> tuple[bool, str]:
    """GitHub Actions cron is UTC-only, so the workflow fires at two UTC times and this
    gate keeps just one: the first run on a weekday at or after 07:45 London time
    (before 11:00) for which no briefing exists yet. This keeps 08:00 local time
    through the GMT/BST clock changes."""
    now = now or london_now()
    if now.weekday() >= 5:
        return False, "weekend"
    minutes = now.hour * 60 + now.minute
    if not (REPORT_HOUR * 60 - 15 <= minutes < 11 * 60):
        return False, f"outside window ({now:%H:%M} London)"
    out = REPORTS_DIR / f"{now:%Y}" / f"{now:%m}" / f"briefing-{now.date().isoformat()}.md"
    if out.exists():
        return False, "briefing already produced today"
    return True, f"go ({now:%H:%M} London)"


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="monitor")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="collect data and produce the briefing")
    r.add_argument("--date", type=date.fromisoformat, help="report date (default: today, London)")
    r.add_argument("--offline", action="store_true", help="skip network fetches; use stored + manual data")
    sub.add_parser("gate", help="exit 0 if the scheduled run should proceed now")
    a = p.parse_args(argv)

    if a.cmd == "gate":
        ok, why = should_run_now()
        print(why)
        return 0 if ok else 1

    res = run(a.date, offline=a.offline)
    print(f"Markdown: {res['markdown']}\nHTML:     {res['html']}\nStatus:   {res['status']}")
    for f in res["failures"]:
        print(f"DATA FAILURE: {f}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
