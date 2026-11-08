import json
from types import SimpleNamespace

import openpyxl

from nwtracker.db import HistoryDB
from nwtracker.weekly import analyse, build


def rec(url, name, size, agent, status="Available Now"):
    return {"listing_urls": [url], "property_name": name, "max_sqft": size, "agents": [agent], "county": "Cheshire",
            "submarket": "Warrington", "availability_status": status, "size_band": "25,000–50,000 sq ft",
            "agent_urls": {agent: url}, "notes": [], "conflicts": [], "count_in_totals": True}


def add_run(db, recs, agents, when):
    rid = db.start_run(False)
    db.conn.execute("UPDATE runs SET started_at=? WHERE run_id=?", (when, rid))
    for a in agents:
        db.save_agent_result(rid, SimpleNamespace(agent=a, website="", status="Success", method="", search_urls=[],
                                                  listings_scanned=1, candidates=1, included=[], excluded=[],
                                                  errors=[], brochures_read=0, brochure_errors=0, duration_s=0,
                                                  message=""))
    for r in recs:
        db.conn.execute("INSERT INTO listings VALUES (?,?,?,?,?,?,?)",
                        (rid, r["agents"][0], r["listing_urls"][0], None, 1, "", "{}"))
    db.assign_ids(recs)
    db.record(rid, recs, set())
    db.finish_run(rid, "w", "d")
    return rid


def test_new_stock_vs_newly_covered_and_removed(tmp_path):
    db = HistoryDB(tmp_path / "h.sqlite")
    add_run(db, [rec("u1", "A", 30000, "JLL"), rec("u2", "B", 40000, "JLL")], ["JLL"], "2026-11-01T07:00:00")
    add_run(db, [rec("u1", "A", 30000, "JLL"), rec("u3", "C", 26000, "JLL"), rec("s1", "D", 50000, "Savills")],
            ["JLL", "Savills"], "2026-11-08T07:00:00")
    runs = [dict(r) for r in db.conn.execute("SELECT run_id, started_at FROM runs ORDER BY run_id")]
    a = analyse(db, runs[1], runs[0])
    assert [r["property_name"] for r in a["new"]] == ["C"]          # genuinely new from a tracked agent
    assert [r["property_name"] for r in a["newly_covered"]] == ["D"]  # Savills only just added
    assert [r["property_name"] for r in a["removed"]] == ["B"]
    assert a["newly_added_agents"] == ["Savills"]
    p = tmp_path / "w.xlsx"
    build(a, p, [])
    wb = openpyxl.load_workbook(p)
    assert wb.sheetnames == ["Summary", "New to Market", "Returned to Market", "Removed from Market",
                             "New Joint Agents", "Newly Covered Sources", "Weekly Trend"]
