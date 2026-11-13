"""Trend charts. Drawn only when enough verified history exists."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from .config import MIN_POINTS_FOR_CHART, SERIES  # noqa: E402

PALETTE = ["#1f5f99", "#c8553d", "#2a9d8f", "#8a6fb3", "#d99a1e"]


def _style(ax, title: str, ylabel: str):
    ax.set_title(title, loc="left", fontsize=11, fontweight="bold", color="#222")
    ax.set_ylabel(ylabel, fontsize=9, color="#444")
    ax.grid(axis="y", color="#ddd", linewidth=0.6)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.tick_params(labelsize=8, colors="#444")


def bond_chart(store, report_date: date, out: Path, days: int = 120) -> tuple[Path | None, str]:
    start = report_date - timedelta(days=days)
    series = ["UK_GILT_5Y", "UK_GILT_10Y", "US_UST_5Y", "US_UST_10Y"]
    data = {s: [o for o in store.history(s, report_date) if o.obs_date >= start] for s in series}
    usable = {s: v for s, v in data.items() if len(v) >= MIN_POINTS_FOR_CHART}
    skipped = [SERIES[s]["label"] for s in series if s not in usable]
    if not usable:
        return None, "Bond chart not drawn: fewer than %d verified observations." % MIN_POINTS_FOR_CHART
    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=150)
    for i, (s, v) in enumerate(usable.items()):
        ax.plot([o.obs_date for o in v], [o.value for o in v], color=PALETTE[i % len(PALETTE)], linewidth=1.6,
                label=SERIES[s]["label"])
        ax.annotate(f"{v[-1].value:.2f}", (v[-1].obs_date, v[-1].value), fontsize=7, color=PALETTE[i % len(PALETTE)],
                    xytext=(3, 0), textcoords="offset points", va="center")
    _style(ax, "Government bond yields (%)", "%")
    ax.legend(fontsize=8, frameon=False, ncol=2, loc="upper left")
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    plt.close(fig)
    note = ("Excluded (insufficient verified history): " + ", ".join(skipped)) if skipped else ""
    return out, note


def spread_chart(spread_history: dict[str, list[tuple[date, float]]], out: Path, report_date: date | None = None,
                 dashed: set[str] | None = None, days: int = 120) -> tuple[Path | None, str]:
    """dashed: series whose property figure is carried forward from old evidence."""
    dashed = dashed or set()
    if report_date:
        start = report_date - timedelta(days=days)
        spread_history = {k: [(d, x) for d, x in v if d >= start] for k, v in spread_history.items()}
    usable = {k: v for k, v in spread_history.items() if len(v) >= MIN_POINTS_FOR_CHART}
    if not usable:
        return None, ("Property-gilt spread chart not drawn: fewer than %d verified daily spread points so far."
                      % MIN_POINTS_FOR_CHART)
    fig, ax = plt.subplots(figsize=(9.5, 3.6), dpi=150)
    for i, (k, v) in enumerate(usable.items()):
        v = sorted(v)
        ax.plot([d for d, _ in v], [x for _, x in v], color=PALETTE[i % len(PALETTE)], linewidth=1.6,
                linestyle="--" if k in dashed else "-", label=k + (" (carried-forward yield)" if k in dashed else ""))
    ax.axhline(0, color="#999", linewidth=0.8)
    _style(ax, "Prime property yield less UK 10Y gilt (bp)", "bp")
    ax.legend(fontsize=7, frameon=False, loc="upper left", bbox_to_anchor=(1.01, 1))
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    plt.close(fig)
    keys = list(usable)
    same = [f"{a} and {b}" for i, a in enumerate(keys) for b in keys[i + 1:]
            if usable[a][-20:] == usable[b][-20:]]
    note = ("Lines overlap where the published yields are identical: " + "; ".join(same) + ".") if same else ""
    return out, note
