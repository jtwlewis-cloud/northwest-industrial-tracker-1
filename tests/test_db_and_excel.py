from types import SimpleNamespace

import openpyxl

from nwtracker.db import HistoryDB
from nwtracker.excel import build_workbook


def rec(urls, name, size, status="Available Now", agents=("JLL",)):
    return {"listing_urls": list(urls), "property_name": name, "title": name, "max_sqft": size, "min_sqft": size,
            "total_sqft": size, "availability_status": status, "agents": list(agents), "county": "Cheshire",
            "submarket": "Warrington", "notes": [], "conflicts": [], "agent_urls": {agents[0]: urls[0]},
            "brochure_urls": ["https://x/b.pdf"], "size_band": "25,000–50,000 sq ft", "build_status": "Existing",
            "tenure": "Leasehold", "rent_psf": 7.0, "count_in_totals": True, "sources": ["web"]}


def test_ids_stable_and_changes_detected(tmp_path):
    db = HistoryDB(tmp_path / "h.sqlite")
    r1 = db.start_run(False)
    a, b = rec(["u1"], "A", 30000), rec(["u2"], "B", 40000)
    db.assign_ids([a, b])
    db.record(r1, [a, b], set())
    db.finish_run(r1, "w", "d")
    assert a["change_flag"] == "Baseline (first run)"
    r2 = db.start_run(False)
    a2 = rec(["u1", "u9"], "A", 30000, status="Under Offer", agents=("JLL", "DTRE"))
    c = rec(["u3"], "C", 26000)
    db.assign_ids([a2, c])
    assert a2["property_id"] == a["property_id"]  # stable ID via shared URL
    changes = db.record(r2, [a2, c], set())
    types = {ch["change_type"] for ch in changes}
    assert {"Changed", "New", "Removed"} <= types
    detail = next(ch for ch in changes if ch["change_type"] == "Changed")["details"]
    assert "Under Offer" in detail and "DTRE" in detail


def test_failed_agent_not_marked_removed(tmp_path):
    db = HistoryDB(tmp_path / "h.sqlite")
    r1 = db.start_run(False)
    a = rec(["u1"], "A", 30000, agents=("CBRE",))
    db.assign_ids([a]); db.record(r1, [a], set()); db.finish_run(r1, "w", "d")
    r2 = db.start_run(False)
    changes = db.record(r2, [], {"CBRE"})
    assert changes[0]["change_type"] == "Not re-checked"


def test_workbook_has_all_sheets(tmp_path):
    recs = [rec(["https://x/1"], "A", 30000), rec(["https://x/2"], "B", 120000, status="Under Offer")]
    for i, r in enumerate(recs):
        r["property_id"] = f"NW-{i:05d}"
        r["size_band"] = "25,000–50,000 sq ft" if i == 0 else "100,000–250,000 sq ft"
    cov = [SimpleNamespace(agent="JLL", website="w", status="Success", method="m", search_urls=["s"],
                           listings_scanned=5, candidates=2, included=[1, 2], brochures_read=1, brochure_errors=0,
                           duration_s=1.0, message="ok", errors=[])]
    p = tmp_path / "wb.xlsx"
    build_workbook(p, recs, [], cov, [], [{"run_id": 1, "started_at": "t", "properties": 2}], "2026-01-01",
                   {"JLL": 0, "_reasons": {}})
    wb = openpyxl.load_workbook(p)
    expected = ["Master Availability", "Greater Manchester", "Merseyside", "Cheshire", "Lancashire", "Cumbria",
                "Existing Buildings", "New Build and Pipeline", "Under Offer – Unconfirmed", "Under 10,000 sq ft",
                "10,000–25,000 sq ft", "25,000–50,000 sq ft", "50,000–100,000 sq ft", "100,000–250,000 sq ft",
                "Over 250,000 sq ft", "Changes Since Last Search", "Market Supply Summary",
                "Source Coverage and Errors", "Duplicate Review"]
    assert wb.sheetnames == expected
    ws = wb["Master Availability"]
    hdr = [c.value for c in ws[1]]
    size_col = hdr.index("Max Available Area (sq ft)") + 1
    assert isinstance(ws.cell(row=2, column=size_col).value, (int, float))
    link_col = hdr.index("Property Webpage") + 1
    assert ws.cell(row=2, column=link_col).hyperlink is not None
    assert ws.freeze_panes == "D2"
    assert ws.tables  # filterable table
    assert wb["25,000–50,000 sq ft"].max_row == 2
