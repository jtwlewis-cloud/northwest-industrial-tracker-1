"""Excel availability schedule (openpyxl)."""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from . import config

ND = "Not Disclosed"
NAVY = "1F3864"
HEAD_FILL = PatternFill("solid", fgColor=NAVY)
HEAD_FONT = Font(bold=True, color="FFFFFF", size=10)
TITLE_FONT = Font(bold=True, size=14, color=NAVY)
SUB_FONT = Font(bold=True, size=11, color=NAVY)
NEW_FILL = PatternFill("solid", fgColor="E2EFDA")
CHG_FILL = PatternFill("solid", fgColor="FFF2CC")
FLAG_FILL = PatternFill("solid", fgColor="FCE4D6")
STATUS_FILL = {
    "Available Now": "C6EFCE", "Available at a Future Date": "DDEBF7", "Under Construction": "BDD7EE",
    "Proposed / Design and Build": "E4DFEC", "Under Offer": "F8CBAD", "Availability Unconfirmed": "EDEDED",
}
THIN = Border(bottom=Side(style="thin", color="D9D9D9"))
WRAP = Alignment(wrap_text=True, vertical="top")
TOP = Alignment(vertical="top")

# (header, key or callable, width, number_format, kind)
COLUMNS = [
    ("Property ID", "property_id", 11, None, "text"),
    ("Change Since Last Search", "change_flag", 14, None, "text"),
    ("Property Name", "property_name", 34, None, "text"),
    ("Unit Number", "unit_number", 10, None, "text"),
    ("Estate / Development", "estate", 28, None, "text"),
    ("Full Address", "address", 40, None, "text"),
    ("Postcode", "postcode", 10, None, "text"),
    ("Town", "town", 14, None, "text"),
    ("County", "county", 17, None, "text"),
    ("Local Authority", "local_authority", 18, None, "text"),
    ("Industrial Submarket", "submarket", 26, None, "text"),
    ("Total Floor Area (sq ft)", "total_sqft", 13, "#,##0", "num"),
    ("Min Divisible Area (sq ft)", "min_sqft", 13, "#,##0", "num"),
    ("Max Available Area (sq ft)", "max_sqft", 13, "#,##0", "num"),
    ("Size Band", "size_band", 18, None, "text"),
    ("Warehouse Area (sq ft)", "warehouse_sqft", 12, "#,##0", "num"),
    ("Office Area (sq ft)", "office_sqft", 11, "#,##0", "num"),
    ("Eaves Height (m)", "eaves_m", 9, "0.0#", "num"),
    ("Dock-Level Doors", "dock_doors", 8, "0", "num"),
    ("Level-Access Doors", "level_doors", 8, "0", "num"),
    ("Yard Depth (m)", "yard_depth_m", 8, "0", "num"),
    ("Site Area (acres)", "site_acres", 9, "0.00", "num"),
    ("Power Supply", "power", 14, None, "text"),
    ("EPC Rating", "epc", 9, None, "text"),
    ("BREEAM Rating", "breeam", 12, None, "text"),
    ("Sprinklers", "sprinklers", 12, None, "text"),
    ("Existing / New Build", "build_status", 16, None, "text"),
    ("Specification / Condition", "specification", 40, None, "wrap"),
    ("Availability Date", "availability_date", 12, None, "text"),
    ("Availability Status", "availability_status", 20, None, "status"),
    ("Marketing Status (as advertised)", "marketing_status", 16, None, "text"),
    ("Leasehold Rent (£ psf pa)", "rent_psf", 11, "£0.00", "num"),
    ("Quoted Rent (as advertised)", "rent_text", 18, None, "text"),
    ("Freehold Asking Price", "price_text", 18, None, "text"),
    ("Tenure", "tenure", 16, None, "text"),
    ("Marketing Agents", "agents_text", 24, None, "text"),
    ("No. of Agents", "agent_count", 7, "0", "num"),
    ("Agent Contact Details", "agent_contacts", 45, None, "wrap"),
    ("Property Webpage", "primary_url", 30, None, "link"),
    ("Other Agent Webpages", "other_urls", 40, None, "wrap"),
    ("PDF Brochure", "primary_brochure", 30, None, "link"),
    ("Other Brochures", "other_brochures", 30, None, "wrap"),
    ("Data Sources", "sources_text", 12, None, "text"),
    ("Last Verified", "last_verified", 11, None, "text"),
    ("First Recorded", "first_seen", 11, None, "text"),
    ("Duplicate / Overlap Flag", "dup_flag", 22, None, "wrap"),
    ("Conflicts – Check", "conflicts_text", 40, None, "wrap"),
    ("Additional Notes", "notes_text", 45, None, "wrap"),
]
TEXT_ND = {"power", "epc", "breeam", "sprinklers", "availability_date", "rent_text", "price_text", "tenure",
           "agent_contacts", "estate", "unit_number", "postcode"}


def prepare(rec: dict) -> dict:
    r = dict(rec)
    urls = r.get("agent_urls") or {}
    ordered = list(urls.values()) or r.get("listing_urls", [])
    r["primary_url"] = ordered[0] if ordered else r.get("url", "")
    extra = [f"{a}: {u}" for a, u in urls.items() if u != r["primary_url"]]
    extra += [u for u in r.get("listing_urls", []) if u not in urls.values()]
    r["other_urls"] = "\n".join(extra)
    br = r.get("brochure_urls") or []
    r["primary_brochure"] = br[0] if br else ""
    r["other_brochures"] = "\n".join(br[1:4]) + (f"\n(+{len(br) - 4} more)" if len(br) > 4 else "")
    r["agents_text"] = ", ".join(r.get("agents") or [r.get("agent", "")])
    r["agent_count"] = len(r.get("agents") or [1])
    r["sources_text"] = " + ".join(r.get("sources") or ["web"])
    r["conflicts_text"] = "\n".join(r.get("conflicts") or [])
    r["notes_text"] = "\n".join(r.get("notes") or [])
    if not r.get("specification"):
        r["specification"] = spec_summary(r)
    r["dup_flag"] = r.get("dup_flag", "")
    return r


def spec_summary(r: dict) -> str:
    desc = (r.get("description") or "")
    # first ~2 sentences of the agent's own description, as published
    import re
    parts = [p.strip() for p in re.split(r"\s\|\s", desc) if len(p.strip()) > 25]
    s = " | ".join(parts[:3])
    return s[:400]


def _write_table(ws, start_row: int, headers: list, rows: list[list], name: str, widths=None,
                 formats=None, style="TableStyleMedium2"):
    for j, h in enumerate(headers, 1):
        c = ws.cell(row=start_row, column=j, value=h)
        c.font, c.fill = HEAD_FONT, HEAD_FILL
        c.alignment = Alignment(wrap_text=True, vertical="center")
    for i, row in enumerate(rows, start_row + 1):
        for j, v in enumerate(row, 1):
            c = ws.cell(row=i, column=j, value=v)
            if formats and formats[j - 1]:
                c.number_format = formats[j - 1]
            c.alignment = TOP
    if widths:
        for j, w in enumerate(widths, 1):
            cur = ws.column_dimensions[get_column_letter(j)].width or 0
            ws.column_dimensions[get_column_letter(j)].width = max(cur, w)
    end_row = start_row + max(len(rows), 1)
    if not rows:
        ws.cell(row=start_row + 1, column=1, value="(none)")
    ref = f"A{start_row}:{get_column_letter(len(headers))}{end_row}"
    t = Table(displayName=name, ref=ref)
    t.tableStyleInfo = TableStyleInfo(name=style, showRowStripes=True)
    ws.add_table(t)
    return end_row


def write_schedule_sheet(ws, recs: list[dict], tname: str, title: str):
    ws.sheet_view.zoomScale = 85
    headers = [c[0] for c in COLUMNS]
    for j, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=j, value=h)
        c.font, c.fill = HEAD_FONT, HEAD_FILL
        c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        ws.column_dimensions[get_column_letter(j)].width = COLUMNS[j - 1][2]
    ws.row_dimensions[1].height = 42
    for i, rec in enumerate(recs, 2):
        r = prepare(rec)
        for j, (h, key, w, fmt, kind) in enumerate(COLUMNS, 1):
            v = r.get(key)
            if isinstance(v, list):
                v = ", ".join(str(x) for x in v)
            if v in (None, "", []):
                v = ND if key in TEXT_ND else None
            c = ws.cell(row=i, column=j, value=v)
            if fmt:
                c.number_format = fmt
            c.alignment = WRAP if kind == "wrap" else TOP
            if kind == "link" and v and str(v).startswith("http"):
                c.hyperlink = str(v)
                c.value = "Open listing" if key == "primary_url" else "Open brochure (PDF)"
                c.font = Font(color="0563C1", underline="single")
            if kind == "status" and v in STATUS_FILL:
                c.fill = PatternFill("solid", fgColor=STATUS_FILL[v])
        flag = r.get("change_flag", "")
        if flag in ("New", "Re-listed"):
            for j in (1, 2, 3):
                ws.cell(row=i, column=j).fill = NEW_FILL
        elif flag == "Changed":
            for j in (1, 2, 3):
                ws.cell(row=i, column=j).fill = CHG_FILL
        if r.get("conflicts_text") or r.get("dup_flag"):
            ws.cell(row=i, column=headers.index("Conflicts – Check") + 1).fill = FLAG_FILL
        ws.row_dimensions[i].height = 45
    last = max(len(recs) + 1, 2)
    if not recs:
        ws.cell(row=2, column=1, value="No properties in this category")
    ref = f"A1:{get_column_letter(len(headers))}{last}"
    t = Table(displayName=tname, ref=ref)
    t.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
    ws.add_table(t)
    ws.freeze_panes = "D2"


def is_available(r):
    return r.get("availability_status") != "Under Offer"


def sqft(r):
    return r.get("max_sqft") or 0


def counted(r):
    return r.get("count_in_totals", True)


def build_summary(ws, recs, changes, coverage, history, run_date):
    ws.sheet_view.showGridLines = False
    ws["A1"] = "North West Industrial & Logistics – Market Supply Summary"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = (f"Search date {run_date}. Floor space = maximum available area per unique property (divisible "
                "options are not added together); unit listings that sit inside an estate-level listing for the same "
                "space are excluded from totals (see Duplicate Review). Under-offer space is shown separately.")
    ws["A2"].alignment = Alignment(wrap_text=True)
    ws.merge_cells("A2:H2")
    ws.row_dimensions[2].height = 45
    row = 4
    avail = [r for r in recs if is_available(r)]
    tot = [r for r in avail if counted(r)]
    imm = [r for r in tot if r["availability_status"] in ("Available Now", "Availability Unconfirmed")
           and r.get("build_status", "").startswith("Existing")]
    fut = [r for r in tot if r["availability_status"] in ("Available at a Future Date", "Under Construction")
           or (r["availability_status"] == "Availability Unconfirmed" and r.get("build_status") == "New Build")]
    dnb = [r for r in tot if r["availability_status"] == "Proposed / Design and Build"]
    uo = [r for r in recs if r["availability_status"] == "Under Offer"]
    fh = [r for r in tot if "Freehold" in (r.get("tenure") or "")]
    spec = [r for r in tot if r.get("build_status") == "New Build"]
    nd = [r for r in avail if not r.get("max_sqft")]
    new = [c for c in changes if c["change_type"] in ("New", "Re-listed")]
    rem = [c for c in changes if c["change_type"] == "Removed"]
    chg = [c for c in changes if c["change_type"] == "Changed"]
    s = lambda rs: sum(sqft(r) for r in rs)
    head = [
        ["Unique properties in schedule (all statuses)", len(recs), s([r for r in recs if counted(r)])],
        ["Unique advertised available properties (excl. under offer)", len(avail), s(tot)],
        ["  – Available now (explicitly stated)", sum(1 for r in tot if r["availability_status"] == "Available Now"),
         s([r for r in tot if r["availability_status"] == "Available Now"])],
        ["  – Advertised, availability not stated (existing + new build)", sum(1 for r in tot if r["availability_status"] == "Availability Unconfirmed"),
         s([r for r in tot if r["availability_status"] == "Availability Unconfirmed"])],
        ["  – Available at a future date", sum(1 for r in tot if r["availability_status"] == "Available at a Future Date"),
         s([r for r in tot if r["availability_status"] == "Available at a Future Date"])],
        ["  – Under construction", sum(1 for r in tot if r["availability_status"] == "Under Construction"),
         s([r for r in tot if r["availability_status"] == "Under Construction"])],
        ["  – Proposed / design and build", len(dnb), s(dnb)],
        ["Immediate supply – existing buildings (available now or date not stated)", len(imm), s(imm)],
        ["Future supply – under construction / future date / new build not yet complete", len(fut), s(fut)],
        ["Speculative new-build supply (all statuses excl. under offer)", len(spec), s(spec)],
        ["Design-and-build opportunities (indicative max size)", len(dnb), s(dnb)],
        ["Freehold supply (for sale, incl. lease-or-sale)", len(fh), s(fh)],
        ["Under offer", len(uo), s(uo)],
        ["Advertised available with size not disclosed", len(nd), None],
        ["Excluded from floor-space totals to avoid double counting", sum(1 for r in avail if not counted(r)),
         s([r for r in avail if not counted(r)])],
        ["New advertisements since previous search", len(new), None],
        ["Removed from advertising since previous search", len(rem), None],
        ["Changed advertisements since previous search", len(chg), None],
    ]
    ws.cell(row=row, column=1, value="Headline supply").font = SUB_FONT
    row = _write_table(ws, row + 1, ["Measure", "Properties", "Floor space (sq ft)"], head, "Headline",
                       widths=[70, 12, 18], formats=[None, "#,##0", "#,##0"]) + 2

    def group_table(title, keyf, name, rs, extra_cols=True):
        nonlocal row
        ws.cell(row=row, column=1, value=title).font = SUB_FONT
        g = defaultdict(list)
        for r in rs:
            g[keyf(r)].append(r)
        rows = []
        for k in sorted(g, key=lambda x: (str(x[0]) if isinstance(x, tuple) else str(x))):
            items = g[k]
            av = [r for r in items if is_available(r) and counted(r)]
            label = list(k) if isinstance(k, tuple) else [k]
            rows.append(label + [len([r for r in items if is_available(r)]), s(av),
                                 s([r for r in av if r in imm]), s([r for r in av if r in fut]), s([r for r in av if r in dnb]),
                                 len([r for r in items if r["availability_status"] == "Under Offer"])])
        label_heads = ["County", "Submarket"] if rows and len(rows[0]) == 8 else ["County"]
        heads = label_heads + ["Available properties", "Available sq ft", "Immediate sq ft", "Future sq ft",
                               "D&B sq ft", "Under offer (no.)"]
        fm = [None] * len(label_heads) + ["#,##0"] * 6
        row = _write_table(ws, row + 1, heads, rows, name, formats=fm) + 2

    group_table("Supply by county", lambda r: r.get("county") or "Unknown", "ByCounty", recs)
    group_table("Supply by county and submarket", lambda r: (r.get("county") or "", r.get("submarket") or "Unknown"),
                "BySubmarket", recs)
    order = {b[0]: i for i, b in enumerate(config.SIZE_BANDS)}
    ws.cell(row=row, column=1, value="Supply by size band (max available area)").font = SUB_FONT
    rows = []
    for band in [b[0] for b in config.SIZE_BANDS] + ["Size Not Disclosed"]:
        items = [r for r in recs if r.get("size_band") == band]
        av = [r for r in items if is_available(r) and counted(r)]
        rows.append([band, len([r for r in items if is_available(r)]), s(av), s([r for r in av if r in imm]),
                     s([r for r in av if r in fut]), s([r for r in av if r in dnb]),
                     len([r for r in items if r["availability_status"] == "Under Offer"])])
    row = _write_table(ws, row + 1, ["Size band", "Available properties", "Available sq ft", "Immediate sq ft",
                                     "Future sq ft", "D&B sq ft", "Under offer (no.)"], rows, "BySize",
                       formats=[None] + ["#,##0"] * 6) + 2

    ws.cell(row=row, column=1, value="Existing buildings by county").font = SUB_FONT
    rows = []
    for cty in config.COUNTIES:
        items = [r for r in tot if r.get("county") == cty and (r.get("build_status") or "").startswith("Existing")]
        ref = [r for r in items if r.get("build_status") == "Existing – Refurbished"]
        rows.append([cty, len(items), s(items), len(ref), s(ref)])
    row = _write_table(ws, row + 1, ["County", "Existing buildings", "sq ft", "of which refurbished", "Refurbished sq ft"],
                       rows, "Existing", formats=[None, "#,##0", "#,##0", "#,##0", "#,##0"]) + 2

    def list_table(title, rs, name):
        nonlocal row
        ws.cell(row=row, column=1, value=title).font = SUB_FONT
        rows = [[r.get("property_id"), r.get("property_name"), r.get("county"), r.get("submarket"), r.get("max_sqft"),
                 r.get("availability_status"), r.get("availability_date") or ND, ", ".join(r.get("agents") or [])]
                for r in sorted(rs, key=lambda x: -(x.get("max_sqft") or 0))]
        row = _write_table(ws, row + 1, ["Property ID", "Property", "County", "Submarket", "Max sq ft", "Status",
                                         "Availability date", "Agents"], rows, name,
                           formats=[None, None, None, None, "#,##0", None, None, None]) + 2

    list_table("Speculative development pipeline (new build: under construction, future or not yet confirmed)",
               [r for r in avail if r.get("build_status") == "New Build"], "Pipeline")
    list_table("Design-and-build opportunities", dnb, "DesignBuild")

    ws.cell(row=row, column=1, value="Freehold supply by county").font = SUB_FONT
    rows = []
    for cty in config.COUNTIES:
        items = [r for r in fh if r.get("county") == cty]
        only = [r for r in items if r.get("tenure") == "Freehold"]
        rows.append([cty, len(items), s(items), len(only)])
    row = _write_table(ws, row + 1, ["County", "Freehold available (incl. lease or sale)", "sq ft", "Freehold only"],
                       rows, "Freehold", formats=[None, "#,##0", "#,##0", "#,##0"]) + 2

    ws.cell(row=row, column=1, value="Quoted rents (£ per sq ft pa, as advertised – only where a psf rent is published)").font = SUB_FONT
    rows = []
    for cty in config.COUNTIES:
        for band, _, _ in config.SIZE_BANDS:
            rents = [r["rent_psf"] for r in recs if r.get("county") == cty and r.get("size_band") == band and r.get("rent_psf")]
            if rents:
                rows.append([cty, band, len(rents), min(rents), round(statistics.median(rents), 2), max(rents)])
    row = _write_table(ws, row + 1, ["County", "Size band", "Rent quotes", "Min £psf", "Median £psf", "Max £psf"], rows,
                       "Rents", formats=[None, None, "0", "£0.00", "£0.00", "£0.00"]) + 2
    ws.cell(row=row, column=1, value="Quoted rents by submarket").font = SUB_FONT
    g = defaultdict(list)
    for r in recs:
        if r.get("rent_psf"):
            g[(r.get("county"), r.get("submarket"))].append(r["rent_psf"])
    rows = [[k[0], k[1], len(v), min(v), round(statistics.median(v), 2), max(v)] for k, v in sorted(g.items())]
    row = _write_table(ws, row + 1, ["County", "Submarket", "Rent quotes", "Min £psf", "Median £psf", "Max £psf"], rows,
                       "RentsSub", formats=[None, None, "0", "£0.00", "£0.00", "£0.00"]) + 2

    ws.cell(row=row, column=1, value="Changes since previous search").font = SUB_FONT
    rows = [["New advertisements", len(new), s([r for r in recs if r.get("change_flag") in ("New", "Re-listed")])],
            ["Removed from advertising", len(rem), sum((c.get("record") or {}).get("max_sqft") or 0 for c in rem)],
            ["Changed advertisements", len(chg), None]]
    row = _write_table(ws, row + 1, ["Change", "Properties", "sq ft"], rows, "ChangeSummary",
                       formats=[None, "#,##0", "#,##0"]) + 2
    ws.cell(row=row, column=1, value="Supply history (all runs)").font = SUB_FONT
    rows = [[h["run_id"], h["started_at"], h["properties"]] for h in history]
    row = _write_table(ws, row + 1, ["Run", "Run date/time", "Unique properties recorded"], rows, "History",
                       formats=["0", None, "#,##0"]) + 2
    ws.column_dimensions["A"].width = 70
    for col, w in zip("BCDEFGH", (34, 18, 26, 14, 26, 16, 30)):
        ws.column_dimensions[col].width = max(ws.column_dimensions[col].width or 0, w)


def build_workbook(path, recs, changes, coverage, pairs, history, run_date, excluded_counts):
    wb = Workbook()
    recs = sorted(recs, key=lambda r: (config.COUNTIES.index(r["county"]) if r.get("county") in config.COUNTIES else 9,
                                       r.get("submarket") or "", -(r.get("max_sqft") or 0)))
    sheets = [
        ("Master Availability", "Master", recs),
        ("Greater Manchester", "GM", [r for r in recs if r.get("county") == "Greater Manchester"]),
        ("Merseyside", "Mers", [r for r in recs if r.get("county") == "Merseyside"]),
        ("Cheshire", "Ches", [r for r in recs if r.get("county") == "Cheshire"]),
        ("Lancashire", "Lancs", [r for r in recs if r.get("county") == "Lancashire"]),
        ("Cumbria", "Cumb", [r for r in recs if r.get("county") == "Cumbria"]),
        ("Existing Buildings", "Existing_", [r for r in recs if (r.get("build_status") or "").startswith("Existing")]),
        ("New Build and Pipeline", "NewBuild", [r for r in recs if r.get("build_status") in ("New Build", "Design & Build")
                                                or r.get("availability_status") in ("Under Construction", "Proposed / Design and Build")]),
        ("Under Offer – Unconfirmed", "UOUnconf", [r for r in recs if r.get("availability_status") in ("Under Offer", "Availability Unconfirmed")]),
    ]
    for label, lo, hi in config.SIZE_BANDS:
        sheets.append((label.replace("sq ft", "sq ft").strip(), "Band" + str(lo),
                       [r for r in recs if r.get("max_sqft") and lo <= r["max_sqft"] < hi]))
    first = True
    for title, tname, rs in sheets:
        ws = wb.active if first else wb.create_sheet()
        first = False
        ws.title = title[:31]
        write_schedule_sheet(ws, rs, tname, title)

    # Changes
    ws = wb.create_sheet("Changes Since Last Search")
    byid = {r["property_id"]: r for r in recs}
    rows = []
    for c in sorted(changes, key=lambda c: (c["change_type"], c["property_id"])):
        rec = byid.get(c["property_id"]) or c.get("record") or {}
        rows.append([c["change_type"], c["property_id"], c.get("property_name") or rec.get("property_name"),
                     rec.get("county"), rec.get("submarket"), rec.get("max_sqft"), rec.get("availability_status"),
                     ", ".join(rec.get("agents") or []), c["details"]])
    if not changes:
        rows.append(["No previous search – this run is the baseline", None, None, None, None, None, None, None,
                     "Every property in the Master sheet is flagged 'Baseline (first run)'. Changes will be listed from the next run."])
    _write_table(ws, 1, ["Change", "Property ID", "Property", "County", "Submarket", "Max sq ft", "Status", "Agents",
                         "Details"], rows, "Changes", widths=[16, 11, 40, 17, 24, 12, 22, 30, 80],
                 formats=[None, None, None, None, None, "#,##0", None, None, None])
    for rr in range(2, len(rows) + 2):
        ws.cell(row=rr, column=9).alignment = WRAP
        t = ws.cell(row=rr, column=1).value
        fill = NEW_FILL if t in ("New", "Re-listed") else CHG_FILL if t == "Changed" else FLAG_FILL if t == "Removed" else None
        if fill:
            ws.cell(row=rr, column=1).fill = fill
    ws.freeze_panes = "A2"

    ws = wb.create_sheet("Market Supply Summary")
    build_summary(ws, recs, changes, coverage, history, run_date)

    ws = wb.create_sheet("Source Coverage and Errors")
    rows = []
    for c in coverage:
        rows.append([c.agent, c.website, c.status, c.method, "\n".join(c.search_urls), c.listings_scanned,
                     c.candidates, len(c.included), excluded_counts.get(c.agent, 0), c.brochures_read, c.brochure_errors,
                     c.duration_s, c.message, "\n".join(e[:300] for e in c.errors[:8]), run_date])
    _write_table(ws, 1, ["Agent", "Website", "Search status", "Method", "Search URL(s) used", "Listings scanned",
                         "NW/industrial candidates", "Included NW industrial listings", "Excluded after checks",
                         "Brochures read", "Brochure errors", "Duration (s)", "Summary", "Errors / limitations",
                         "Checked on"], rows, "Coverage",
                 widths=[24, 32, 12, 40, 45, 10, 12, 12, 12, 10, 10, 9, 50, 70, 11],
                 formats=[None, None, None, None, None, "#,##0", "#,##0", "#,##0", "#,##0", "#,##0", "#,##0", "0.0", None, None, None])
    for rr in range(2, len(rows) + 2):
        for cc in (4, 5, 13, 14):
            ws.cell(row=rr, column=cc).alignment = WRAP
        st = ws.cell(row=rr, column=3).value
        ws.cell(row=rr, column=3).fill = PatternFill("solid", fgColor={"Success": "C6EFCE", "Partial": "FFEB9C"}.get(st, "FFC7CE"))
        ws.row_dimensions[rr].height = 60
    ws.freeze_panes = "B2"
    # exclusion reasons breakdown under the coverage table
    start = len(rows) + 4
    ws.cell(row=start, column=1, value="Listings excluded after checking (by reason)").font = SUB_FONT
    reason_rows = sorted(([a, r, n] for (a, r), n in excluded_counts.get("_reasons", {}).items()),
                         key=lambda x: (x[0], -x[2]))
    _write_table(ws, start + 1, ["Agent", "Reason", "Listings"], reason_rows, "Exclusions", formats=[None, None, "#,##0"])

    ws = wb.create_sheet("Duplicate Review")
    rows = []
    for p in pairs:
        rows.append([p["decision_label"], p["property_id_a"], p["agent_a"], p["name_a"], p["size_a"],
                     p["property_id_b"], p["agent_b"], p["name_b"], p["size_b"], round(p["score"], 1), p["reason"],
                     p["url_a"], p["url_b"]])
    _write_table(ws, 1, ["Decision", "Property ID A", "Agent A", "Listing A", "Size A (sq ft)", "Property ID B",
                         "Agent B", "Listing B", "Size B (sq ft)", "Match score", "Reasoning", "URL A", "URL B"],
                 rows, "Duplicates", widths=[26, 11, 18, 36, 11, 11, 18, 36, 11, 8, 60, 40, 40],
                 formats=[None, None, None, None, "#,##0", None, None, None, "#,##0", "0.0", None, None, None])
    for rr in range(2, len(rows) + 2):
        ws.cell(row=rr, column=11).alignment = WRAP
        for cc in (12, 13):
            v = ws.cell(row=rr, column=cc).value
            if v:
                ws.cell(row=rr, column=cc).hyperlink = v
                ws.cell(row=rr, column=cc).font = Font(color="0563C1", underline="single")
        d = ws.cell(row=rr, column=1).value or ""
        ws.cell(row=rr, column=1).fill = FLAG_FILL if "check" in d.lower() else NEW_FILL
    ws.freeze_panes = "B2"

    wb.properties.title = "North West Industrial & Logistics Availability"
    wb.properties.creator = "NW Industrial Availability Tracker"
    wb.save(path)
