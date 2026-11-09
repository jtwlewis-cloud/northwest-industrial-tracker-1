"""Commentary.

Two layers, kept separate in the report:
  1. Confirmed developments - generated mechanically from the verified data held.
  2. Interpretation - taken from an analyst note for the report date
     (data/analyst_notes/YYYY-MM-DD.md, written by an analyst or by a Claude
     scheduled task). If there is no note, a cautious rule-based interpretation
     is generated and labelled as such.
"""
from __future__ import annotations

import re
from datetime import date

from .config import ANALYST_NOTES_DIR

SECTIONS = ["Executive Summary", "Interest Rate Outlook", "Market Commentary",
            "North West Industrial & Logistics Outlook", "Analyst Sources"]


def load_notes(report_date: date) -> dict[str, str] | None:
    p = ANALYST_NOTES_DIR / f"{report_date.isoformat()}.md"
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8")
    out, current, buf = {}, None, []
    for line in text.splitlines():
        m = re.match(r"^##\s+(.*)$", line)
        if m:
            if current:
                out[current] = "\n".join(buf).strip()
            current, buf = m.group(1).strip(), []
        elif current:
            buf.append(line)
    if current:
        out[current] = "\n".join(buf).strip()
    return out


def _dir(x: float | None, up="rose", down="fell", flat="was unchanged") -> str:
    if x is None:
        return "change not verified"
    if abs(x) < 0.5:
        return flat
    n = f"{abs(x):.0f}" if abs(x - round(x)) < 0.05 else f"{abs(x):.1f}"
    return f"{up} {n}bp" if x > 0 else f"{down} {n}bp"


def confirmed_developments(ctx) -> list[str]:
    out = []
    mv = ctx["moves"]
    for sid, name in (("UK_GILT_10Y", "UK 10Y gilt"), ("US_UST_10Y", "US 10Y Treasury")):
        m = mv.get(sid)
        if m and m.latest:
            out.append(f"{name} {m.latest.value:.2f}% on {m.latest.obs_date:%d %b %Y}: "
                       f"{_dir(m.d1)} on the day, {_dir(m.d7)} over 7 days, {_dir(m.d30)} over 30 days"
                       + (" (mixed sources - see Table A notes)" if m.mixed_sources else "") + ".")
        else:
            out.append(f"{name}: Not verified (no observation retrieved).")
    br = mv.get("BOE_BANK_RATE")
    if br and br.latest:
        chg = f", changed {br.d1:+.0f}bp from {br.previous.value:.2f}%" if br.previous and br.d1 else ""
        out.append(f"Bank Rate {br.latest.value:.2f}% (effective {(br.effective or br.latest.obs_date):%d %b %Y}{chg}).")
    for sid, name in (("UK_CPI_YOY", "UK CPI"), ("US_CPI_YOY", "US CPI")):
        m = mv.get(sid)
        if m and m.latest:
            prev = f" (previous {m.previous.value:.1f}%)" if m.previous else ""
            out.append(f"{name} {m.latest.value:.1f}% in {m.latest.obs_date:%B %Y}{prev}; "
                       f"trend: {ctx['inflation_trend'].get(sid, 'n/a')}.")
    moved = [r for r in ctx["property_rows"] if r.move_bp]
    if moved:
        out.append("Latest published prime yield movements: " + "; ".join(
            f"{r.label} {r.move_bp:+g}bp to {r.latest.display} ({r.latest.provider}, {r.latest.period})"
            for r in moved) + ".")
    return out


def rule_based(ctx) -> dict[str, str]:
    """Fallback interpretation when no analyst note exists for the day."""
    mv = ctx["moves"]
    g = mv.get("UK_GILT_10Y")
    g30 = g.d30 if g else None
    if g30 is None:
        bond = "The direction of UK gilt yields over the past month could not be verified from the data held."
    elif g30 > 10:
        bond = (f"UK 10-year gilt yields are {g30:.0f}bp higher over 30 days. Higher risk-free rates "
                "raise the hurdle for property income returns and, other things equal, point to outward "
                "pressure on prime yields and capital values.")
    elif g30 < -10:
        bond = (f"UK 10-year gilt yields are {abs(g30):.0f}bp lower over 30 days, easing some of the "
                "pressure on property pricing, although agents' published yields typically lag bond moves.")
    else:
        bond = "UK 10-year gilt yields are broadly unchanged over 30 days."
    neg = [s for s in ctx["spreads"] if s.spread_bp is not None and s.spread_bp < 100]
    spread = ""
    if neg:
        spread = (" Spreads of " + ", ".join(f"{s.label.split(' less')[0]} ({s.spread_bp:+.0f}bp)" for s in neg)
                  + " over the 10-year gilt are below 100bp, leaving little yield cushion "
                  "if gilt yields rise further.")
    text = (bond + spread + " This is an automated, rule-based interpretation; no analyst note was "
            "supplied for this date.")
    nw = ("No analyst note was supplied. North West prime industrial pricing is carried forward from the "
          "latest published evidence shown in Table C; read alongside the gilt and swap moves above.")
    return {"Market Commentary": text, "North West Industrial & Logistics Outlook": nw}
