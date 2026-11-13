from datetime import date, datetime
from zoneinfo import ZoneInfo

from monitor.__main__ import should_run_now
from monitor.metrics import bp, movement, trend_label
from monitor.models import Observation
from monitor.property import PropertyYield, spreads
from monitor.sources.fred import yoy_from_index
from monitor.store import Store


def ob(sid, d, v, src="A", st="official"):
    return Observation(sid, d, v, src, "http://x", st)


def test_bp_conversion():
    assert bp(5.16, 5.42) == -26.0
    assert bp(4.0, 3.75) == 25.0
    assert bp(None, 1) is None


def test_movement_windows():
    hist = [ob("US_UST_10Y", date(2026, 10, 6), 5.30), ob("US_UST_10Y", date(2026, 10, 30), 4.94),
            ob("US_UST_10Y", date(2026, 11, 5), 4.84), ob("US_UST_10Y", date(2026, 11, 6), 4.86)]
    m = movement("US_UST_10Y", hist, date(2026, 11, 9))
    assert m.d1 == 2.0 and m.d7 == -8.0 and m.d30 == -44.0
    assert not m.stale and not m.mixed_sources


def test_daily_change_not_reported_across_gap():
    hist = [ob("US_UST_10Y", date(2026, 10, 1), 5.0), ob("US_UST_10Y", date(2026, 11, 6), 4.86)]
    m = movement("US_UST_10Y", hist, date(2026, 11, 9))
    assert m.d1 is None and m.d7 is None


def test_mixed_source_flag():
    hist = [ob("UK_GILT_10Y", date(2026, 10, 6), 5.42, "KF"), ob("UK_GILT_10Y", date(2026, 11, 6), 5.16, "TE")]
    m = movement("UK_GILT_10Y", hist, date(2026, 11, 9))
    assert m.d30 == -26.0 and "30d" in m.mixed_sources


def test_store_never_overwrites_with_missing_or_lower_priority(tmp_path):
    s = Store(tmp_path / "o.csv", tmp_path / "a.csv", tmp_path / "r.csv")
    d = date(2026, 11, 6)
    assert s.upsert(ob("X", d, 5.0), "r") == "inserted"
    assert s.upsert(ob("X", d, None), "r") == "skipped_missing"
    assert s.upsert(ob("X", d, 4.0, st="manual"), "r") == "kept_existing"
    assert s.history("X")[0].value == 5.0
    assert s.upsert(ob("X", d, 5.1), "r") == "revised"
    s.save()
    assert Store(tmp_path / "o.csv", tmp_path / "a.csv", tmp_path / "r.csv").history("X")[0].value == 5.1


def test_yoy_skips_missing_base_month():
    pts = [(date(2025, 9, 1), 324.8), (date(2026, 9, 1), 336.94), (date(2026, 10, 1), 338.0)]
    out = yoy_from_index(pts)
    assert out == [(date(2026, 9, 1), 3.7, 336.94, 324.8)]


def test_trend_label():
    assert trend_label([3.0, 3.1, 3.5]) == "Accelerating"
    assert trend_label([3.5, 3.2, 3.0]) == "Moderating"
    assert trend_label([3.0, 3.1, 3.0]) == "Broadly stable"


def py(sid, low, high, d):
    return PropertyYield(sid, "", "", "KF", "NIY", low, high, "", d, d, "http://x", "", "", "")


def test_spread_decomposition():
    reg = {"P": [py("P", 5.25, 5.25, date(2026, 9, 8)), py("P", 5.25, 5.50, date(2026, 10, 6))]}
    gilts = [ob("UK_GILT_10Y", date(2026, 9, 7), 5.17), ob("UK_GILT_10Y", date(2026, 10, 6), 5.42),
             ob("UK_GILT_10Y", date(2026, 11, 6), 5.16)]
    (s,) = spreads(reg, [("x", "P")], gilts, date(2026, 11, 9))
    assert s.spread_bp == 21.5 and s.prev_spread_bp == 8.0 and s.spread_at_evidence_bp == -4.5
    assert s.change_bp == 13.5 and s.property_contrib_bp == 12.5 and s.gilt_contrib_bp == 1.0


def test_gate_handles_bst_and_gmt():
    lon = ZoneInfo("Europe/London")
    assert should_run_now(datetime(2026, 7, 6, 7, 52, tzinfo=lon))[0]          # summer, 06:52 UTC cron
    assert not should_run_now(datetime(2026, 12, 7, 6, 52, tzinfo=lon))[0]     # winter, too early
    assert should_run_now(datetime(2026, 12, 7, 7, 52, tzinfo=lon))[0]         # winter, 07:52 UTC cron
    assert not should_run_now(datetime(2026, 12, 5, 8, 0, tzinfo=lon))[0]      # Saturday
