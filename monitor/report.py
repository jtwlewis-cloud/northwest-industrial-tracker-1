"""Render the briefing to Markdown and HTML."""
from __future__ import annotations

import os
from pathlib import Path

import markdown as md
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .config import TEMPLATES_DIR

NV = "Not verified"


def pct(v, dp=2):
    return NV if v is None else f"{v:.{dp}f}%"


def bps(v):
    if v is None:
        return NV
    if abs(v) < 0.05:
        return "0bp"
    return f"{v:+.0f}bp" if abs(v - round(v)) < 0.05 else f"{v:+.1f}bp"


def d(v, fmt="%d %b %Y"):
    return "" if v is None else v.strftime(fmt)


def link(text, url):
    return f"[{text}]({url})" if url else text


def env() -> Environment:
    e = Environment(loader=FileSystemLoader(TEMPLATES_DIR), undefined=StrictUndefined,
                    trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)
    e.filters.update(pct=pct, bps=bps, d=d)
    e.globals.update(link=link, NV=NV)
    return e


HTML_SHELL = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Financial &amp; Property Briefing {date}</title>
<style>
:root {{ --fg:#1d232b; --muted:#5b6673; --bg:#ffffff; --line:#d9dee4; --head:#f3f5f8; --accent:#1f5f99; }}
@media (prefers-color-scheme: dark) {{ :root {{ --fg:#e6e9ee; --muted:#9aa5b1; --bg:#14181d; --line:#2c333b; --head:#1c2229; --accent:#7fb3e6; }} }}
body {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; color:var(--fg); background:var(--bg);
       max-width: 980px; margin: 0 auto; padding: 24px 16px 60px; line-height: 1.5; font-size: 15px; }}
h1 {{ font-size: 1.45rem; letter-spacing: .02em; border-bottom: 3px solid var(--accent); padding-bottom: 8px; }}
h2 {{ font-size: 1.12rem; margin-top: 2rem; color: var(--accent); }}
h3 {{ font-size: 1rem; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; margin: .6rem 0 1rem; display:block; overflow-x:auto; }}
th, td {{ border: 1px solid var(--line); padding: 5px 8px; text-align: left; vertical-align: top; }}
th {{ background: var(--head); }}
td:not(:first-child) {{ font-variant-numeric: tabular-nums; }}
a {{ color: var(--accent); }}
img {{ max-width: 100%; height: auto; border: 1px solid var(--line); background:#fff; }}
small, .muted {{ color: var(--muted); }}
blockquote {{ border-left: 3px solid var(--line); margin: 0; padding-left: 12px; color: var(--muted); }}
</style></head><body>
{body}
</body></html>
"""


def render(ctx: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rd = ctx["report_date"]
    # chart paths relative to the report directory
    for k in ("bond_chart", "spread_chart"):
        ctx[k + "_rel"] = os.path.relpath(ctx[k], out_dir) if ctx.get(k) else None
    text = env().get_template("briefing.md.j2").render(**ctx)
    md_path = out_dir / f"briefing-{rd.isoformat()}.md"
    md_path.write_text(text, encoding="utf-8")
    body = md.markdown(text, extensions=["tables", "sane_lists"])
    html_path = out_dir / f"briefing-{rd.isoformat()}.html"
    html_path.write_text(HTML_SHELL.format(date=rd.isoformat(), body=body), encoding="utf-8")
    # convenience copies at the reports root
    latest_md = out_dir.parent.parent / "latest.md"
    latest_md.write_text(text.replace("](charts/", f"]({rd:%Y}/{rd:%m}/charts/"), encoding="utf-8")
    return md_path, html_path
