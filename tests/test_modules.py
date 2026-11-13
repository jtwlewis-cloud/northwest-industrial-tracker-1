import csv
from datetime import date

from monitor import news, shares
from monitor.models import Observation
from monitor.sources import investegate
from monitor.store import Store


def test_news_repeat_detection(tmp_path, monkeypatch):
    p = tmp_path / "news.csv"
    rows = [
        {"first_reported": "2026-11-10", "headline": "Big shed let", "url": "https://x.com/a?utm=1", "rank": "1",
         "label": "UK INDUSTRIAL", "status": "new"},
        {"first_reported": "2026-11-11", "headline": "Big shed let", "url": "https://x.com/a", "rank": "1",
         "label": "UK INDUSTRIAL", "status": "new"},                                 # repeat -> rejected
        {"first_reported": "2026-11-11", "headline": "Big shed let - update", "url": "https://x.com/a",
         "rank": "2", "label": "UK INDUSTRIAL", "status": "follow-up"},              # explicit follow-up -> kept
        {"first_reported": "2026-11-11", "headline": "New NW deal", "url": "https://y.com/b", "rank": "3",
         "label": "NORTH WEST INDUSTRIAL", "status": "new"},
    ]
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=news.FIELDS)
        w.writeheader()
        w.writerows(rows)
    monkeypatch.setattr(news, "NEWS_CSV", p)
    stories, problems = news.for_date(date(2026, 11, 11))
    assert [s.headline for s in stories] == ["Big shed let - update", "New NW deal"]
    assert any("Already reported" in x for x in problems)
    assert len(news.by_section(stories)["north_west"]) == 1


def test_share_returns_and_alert(tmp_path, monkeypatch):
    st = Store(tmp_path / "px.csv", tmp_path / "a.csv", tmp_path / "r.csv")
    closes = [(date(2025, 12, 31), 100.0)] + [(date(2026, 11, d), 100.0 + d) for d in range(1, 11)]
    closes.append((date(2026, 11, 10), 115.0))           # +3.6% on the day (overrides 110)
    for d, v in closes:
        st.upsert(Observation("PX:PLD", d, v, "Nasdaq", "u", "official"), "r")
    monkeypatch.setattr(shares, "load_watchlist", lambda: [
        {"ticker": "PLD", "name": "Prologis", "group": "international", "quote_unit": "USD", "corporate_action": ""}])
    (r,) = shares.share_rows(st, date(2026, 11, 11), {}, {})
    assert r.latest.value == 115.0 and r.d1 == round((115 / 109 - 1) * 100, 2)
    assert r.alert and r.ytd == 15.0 and r.d5 == round((115 / 105 - 1) * 100, 2)
    # a close dated on the report day itself is not a completed session for the 08:00 briefing
    st.upsert(Observation("PX:PLD", date(2026, 11, 11), 200.0, "Nasdaq", "u", "official"), "r")
    (r2,) = shares.share_rows(st, date(2026, 11, 11), {}, {})
    assert r2.latest.value == 115.0


def test_premium_to_nta_and_look_through():
    class W(dict):
        pass
    sgro = shares.ShareRow({"ticker": "SGRO.L", "group": "primary", "name": "SEGRO", "quote_unit": "GBX"},
                           latest=Observation("PX:SGRO.L", date(2026, 11, 10), 880.0, "x", "u"))
    pld = shares.ShareRow({"ticker": "PLD", "group": "international", "name": "Prologis", "quote_unit": "USD"},
                          latest=Observation("PX:PLD", date(2026, 11, 10), 130.10, "x", "u"))
    fx = Observation("FX_USD_PER_GBP", date(2026, 11, 6), 1.3371, "FRED", "u")
    lt = shares.segro_look_through([sgro, pld], fx)
    assert lt["value_p"] == round(0.092 * 130.10 / 1.3371 * 100, 1)
    assert lt["spread_pct"] == shares.pct(0.092 * 130.10 / 1.3371 * 100, 880.0)
    v = shares.valuation_rows([sgro, pld], {"SGRO.L": {"EPRA_NTA_PS": {"value": "902"}}})
    assert len(v) == 1 and v[0].premium_to_nta == round((880 / 902 - 1) * 100, 2)


def test_investegate_filters_routine_filings():
    page = """<table>
    <tr><td>11 Nov 2026</td><td>03:43 PM</td><td>RNS</td><td><a href="https://www.investegate.co.uk/announcement/rns/x/1">Form 8.3 - Segro plc</a></td></tr>
    <tr><td>19 Oct 2026</td><td>07:00 AM</td><td>RNS</td><td><a href="https://www.investegate.co.uk/announcement/rns/x/2">Trading Update</a></td></tr>
    <tr><td>05 Aug 2026</td><td>04:37 PM</td><td>RNS</td><td><a href="https://www.investegate.co.uk/announcement/rns/x/3">Proposed Equity Issue</a></td></tr>
    </table>"""
    rows = investegate.parse("LMP", page)
    assert [r["headline"] for r in rows] == ["Trading Update", "Proposed Equity Issue"]
    assert rows[0]["category"] == "Trading update" and rows[1]["category"] == "Capital / debt"


def test_place_north_west_feed_and_window():
    from monitor.sources import placenorthwest as pnw
    xml = """<rss><channel>
    <item><title><![CDATA[Shed let at Trafford Park]]></title><link>https://www.placenorthwest.co.uk/a/</link>
    <pubDate>Wed, 11 Nov 2026 10:00:00 +0000</pubDate><guid>a</guid></item>
    <item><title><![CDATA[Old story]]></title><link>https://www.placenorthwest.co.uk/b/</link>
    <pubDate>Mon, 09 Nov 2026 10:00:00 +0000</pubDate><guid>b</guid></item></channel></rss>"""
    items = pnw.parse(xml, "industrial")
    assert [i["title"] for i in items] == ["Shed let at Trafford Park", "Old story"]
    # Monday's window starts on Friday morning; Thursday's starts on Wednesday morning
    assert pnw.window_start(date(2026, 11, 16)).date() == date(2026, 11, 13)
    assert pnw.window_start(date(2026, 11, 12)).date() == date(2026, 11, 11)


def test_north_west_stories_route_by_region():
    s1 = news.Story({"label": "PLANNING / DEVELOPMENT", "region": "NW", "headline": "Bolton plan"})
    s2 = news.Story({"label": "PLANNING / DEVELOPMENT", "region": "UK", "headline": "Ladywood"})
    s3 = news.Story({"label": "NORTH WEST INDUSTRIAL", "headline": "Shed"})
    sec = news.by_section([s1, s2, s3])
    assert [s.headline for s in sec["north_west"]] == ["Bolton plan", "Shed"]
    assert [s.headline for s in sec["industrial"]] == ["Ladywood"]
