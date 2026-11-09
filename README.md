# North West Industrial & Logistics Availability Tracker

A reusable Python application that searches the public websites of 18 commercial property agents and the landlord Indurent,
collects every advertised industrial and logistics property in the North West of England, removes
duplicate (jointly marketed) listings, keeps a permanent history in SQLite and produces a dated,
filterable Excel availability schedule with a market supply analysis.

**Latest outputs (committed in this repository):**

| File | What it is |
|---|---|
| `output/North West Industrial & Logistics Availability.xlsx` | Latest schedule (19 worksheets) |
| `output/history/… <date> run<N>.xlsx` | Dated copy of every run |
| `output/Latest Run Report.md` | Coverage, totals, duplicates, missing information, limitations |
| `data/history/` | Persistent history: one compressed export per run + current state (the SQLite database is rebuilt from these) |
| `output/weekly/` | Weekly new-stock reports (Excel + summary) |

---

## Agents searched

| # | Agent | How it is searched |
|---|---|---|
| 1 | JLL – property.jll.co.uk | Published property sitemap (robots.txt disallows the search pages) + structured JSON on each detail page |
| 2 | CBRE – cbre.co.uk | Checked each run; currently returns a Cloudflare bot challenge → recorded as **Blocked** (never bypassed) |
| 3 | Cushman & Wakefield | UK lease + sale search pages (server-rendered, paginated) |
| 4 | Avison Young | Playwright renders the listings page; the JSON feed the page itself loads is read; static detail pages |
| 5 | Williams Sillitoe | Property search filtered to Industrial, all pages, detail pages |
| 6 | B8 Real Estate | All search-result pages, detail pages |
| 7 | DTRE | All search pages (UK-wide), North West postcodes kept, detail pages |
| 8 | CPP (Commercial Property Partners) | Industrial + Trade Counter searches, North West postcodes kept |
| 9 | BC Real Estate | "North West" property archive, all pages, detail pages |
| 10 | Davies Harrison | Availability tiles on the home page, detail pages |
| 11 | Legat Owen | Industrial property filter, all pages, detail pages |
| 12 | Lambert Smith Hampton | The site's own search endpoint, 180 km radius around the North West, detail pages |
| 13 | Savills | North West industrial search (to let + for sale); listing data embedded in the server-rendered pages |
| 14 | Knight Frank | Playwright renders the UK industrial search (to let + for sale) and pages through it; the data the page loads is read; NW postcodes kept |
| 15 | Colliers | Checked each run; currently returns a Cloudflare bot challenge → recorded as **Blocked** (never bypassed) |
| 16 | Taylor Weaver | Full property list page (use encoded in URL) + detail pages |
| 17 | LM6 | Property search, all pages + detail pages |
| 18 | Fisher German | Industrial to-rent and for-sale searches (England & Wales, all pages), NW postcodes kept, detail pages |
| 19 | Indurent (landlord) | Public unit feed behind "Find your space" (all UK units, NW kept) + unit pages. Indurent's own status is mapped: available → Available Now; coming soon → Future Date; under development → Under Construction / D&B; under offer → Under Offer. Rent £psf is derived from the quoted annual rent ÷ size |

PDF brochures linked from each in-scope listing are downloaded (max 20 MB, cached 7 days) and read with
PyMuPDF (pdfplumber fallback) to fill specification fields the web page does not state.

## Geography and scope

* **Included counties:** Greater Manchester, Merseyside, Cheshire (incl. Warrington, Halton, Cheshire East,
  Cheshire West and Chester), Lancashire (incl. Blackburn with Darwen, Blackpool) and Cumbria.
* Location is decided from the **postcode via postcodes.io (ONS data)** → local authority → county, so
  e.g. Deeside/Flintshire (CH5–CH8), Glossop/High Peak (SK13) and Todmorden/Calderdale (OL14) are correctly
  excluded. Where no postcode is published, map coordinates or the town name are used and the record is
  flagged "(check)".
* **Included:** industrial units, warehouses, distribution/logistics, manufacturing, trade counter; freehold
  and leasehold; existing, refurbished, speculative new build and design-and-build; all sizes.
* **Excluded (and counted in the coverage sheet):** offices, retail/leisure, residential, land or open storage
  with no building or D&B proposal, completed lettings/sales, and investment sales without occupier availability.

## Installation

Requires Python 3.10+.

```bash
pip install -r requirements.txt
python -m playwright install chromium      # only needed for Avison Young
```

The machine needs outbound HTTPS to the agents' websites, `api.postcodes.io`, and the brochure hosts
(`s3-eu-west-1.amazonaws.com`, `cdn.sharplaunch.com`, `hive.agencypilot.com`, `legatowencrm.agencypilot.com`,
`pse-api.sharplaunch.com`, `sdk.sharplaunch.com`, `assets.cushmanwakefield.com`, `assets.savills.com`,
`api-v2.web.prd-knightfrank.com`, `content.knightfrank.com`).

## Running

```bash
python -m nwtracker                      # full run: all 19 sources + brochures (≈20–30 min)
python -m nwtracker --no-brochures       # faster, web pages only
python -m nwtracker --agents jll,b8,dtre # selected agents only
python -m nwtracker --delay 2            # slower, gentler crawling (seconds between requests per site)
python -m nwtracker -v                   # debug logging
python -m nwtracker --rebuild            # regenerate the latest workbook + report from the database (no web access)
python -m nwtracker --rebuild 2          # regenerate the workbook + report for run 2
```

Agent keys: `jll, cbre, cushman, avisonyoung, willsill, b8, dtre, cpp, bc, daviesharrison, legatowen, lsh,
savills, knightfrank, colliers, taylorweaver, lm6, fishergerman, indurent`.

Sources considered but not included: **Novaloca** (its terms of use prohibit commercial use or storage of its
listings without written permission) and **LoopNet** (CoStar's terms prohibit automated access).

Each run:

1. Searches the 18 agencies and Indurent in parallel – each agent is an independent module, so one failing website
   never stops the others (its status is recorded as Success / Partial / Failed / Blocked).
2. Extracts the public listings and reads brochures.
3. Matches listings to properties recorded in earlier runs (stable `NW-00001` style IDs).
4. Identifies new, changed, removed and re-listed advertisements.
5. De-duplicates jointly marketed properties.
6. Updates the SQLite history database.
7. Writes a new dated workbook plus `output/North West Industrial & Logistics Availability.xlsx` (latest).
8. Highlights changes (green = new, yellow = changed) and lists them on *Changes Since Last Search*.

## Weekly new-stock report

```bash
python -m nwtracker.weekly               # latest run vs the run about 7 days earlier
```

Produces `output/weekly/NW New Industrial Stock - week ending <date>.xlsx` (+ a short `.md` summary, and
`Latest Weekly New Stock.xlsx`) with:

* **Summary** – new properties and floor space to market, split into existing buildings vs pipeline; returned to
  market; removed (let / sold / withdrawn); net change; breakdowns by size band, county, submarket and agent
  (joint instructions count for each agent); quoted rents on new stock.
* **New to Market**, **Returned to Market**, **Removed from Market**, **New Joint Agents** – property lists with links.
* **Newly Covered Sources** – listings that appear only because an agent was added to the tracker that week. These
  are *not* counted as new stock, so coverage changes never inflate the weekly figures.
* **Weekly Trend** – one row per weekly report, building up a time series of new supply and take-up.

A property counts as new to market only if an agent already being searched at the comparison run has a new
advertisement for it.

## Scheduling

The full search and the weekly report run automatically every Sunday morning as a scheduled Claude Code task
(fresh cloud session in the `northwest-industrial-tracker` environment), which commits the new workbook, weekly
report and history export to the repository. To run it yourself on a server instead, use cron, e.g.:

```
40 6 * * SUN cd /path/to/northwest-industrial-tracker-1 && python -m nwtracker && python -m nwtracker.weekly >> logs/cron.log 2>&1
```

Logs for every run are written to `logs/`.

## The workbook

19 worksheets: Master Availability · Greater Manchester · Merseyside · Cheshire · Lancashire · Cumbria ·
Existing Buildings · New Build and Pipeline · Under Offer – Unconfirmed\* · six size-band sheets (by maximum
available area) · Changes Since Last Search · Market Supply Summary · Source Coverage and Errors · Duplicate Review.

\* Excel does not allow "/" in sheet names, so "Under Offer / Unconfirmed" is named "Under Offer – Unconfirmed".

Every schedule sheet is an Excel table (filter and sort buttons), with frozen headings, numeric size,
rent and specification columns, colour-coded availability status and clickable links to the listing page
and PDF brochure. Text fields that the agent did not publish show **Not Disclosed**; numeric fields are left
blank so that sorting and totals still work.

### Availability status (evidence-based)

| Status | Rule |
|---|---|
| Available Now | Listing/brochure explicitly says available now / immediately / vacant possession |
| Available at a Future Date | A future date is stated (e.g. "available Q1 2027", refurbishment completing) |
| Under Construction | New build with construction in progress / completion date stated |
| Proposed / Design and Build | D&B, build-to-suit, proposed scheme or pre-let opportunity |
| Under Offer | Agent label or text says under offer / let agreed / STC |
| Availability Unconfirmed | Advertised, but no availability statement – or a stated date has already passed |

Conflicting information (e.g. one agent shows "under offer", another "to let"; different sizes, rents or EPCs)
is retained in the *Conflicts – Check* column and the more cautious status is used.

### De-duplication

Listings are merged only when they share a location (same full postcode, or same postcode district with a
similar name) **and** their unit numbers do not conflict **and** their floor areas agree (within 5%, or 20%
with strong name/unit agreement, which is flagged). Different unit numbers are never merged. Uncertain pairs
(same estate, different sizes; estate-level vs unit-level listings) are kept separate and listed on
*Duplicate Review* for manual checking. Unit listings that fall inside an estate-level listing for the same
space are excluded from floor-space totals so supply is not double counted.

### Market Supply Summary

Headline supply, immediate vs future supply, supply by county, by county + submarket and by size band,
existing buildings, the speculative pipeline, design-and-build opportunities, freehold supply, quoted rents by
county/size band and by submarket, changes since the previous run and a supply history across all runs.

## Database (`data/nw_industrial.sqlite`)

The SQLite file is a working copy and is not committed. Each run is exported to `data/history/run-NNNN.json.gz`
(about 0.6 MB) plus `data/history/state.json.gz`; on a fresh checkout the database is rebuilt from these
automatically. Long descriptions are not stored (the specification summary and all extracted fields are).


| Table | Contents |
|---|---|
| `runs` | One row per run |
| `agent_runs` | Per-agent coverage, counts, errors for each run |
| `listings` | Every listing seen (included and excluded with reason), per run |
| `listing_map` | Listing URL → stable property ID |
| `properties` | Property register: first/last seen, active/removed |
| `property_snapshots` | Full merged record per property per run (for trend analysis) |
| `changes` | New / Changed / Removed / Re-listed / Merged / Not re-checked events |
| `duplicate_reviews` | Merge and ambiguous-match decisions with reasons |
| `geo_cache` | Cached postcode lookups |
| `weekly_reports` | Headline figures of each weekly new-stock report (trend) |

A property whose only agents could not be searched in a run is reported as "Not re-checked" rather than removed.
When a newly searched agent's listing shows that two previously separate records are the same property, the
retired ID is reported as "Merged" (still advertised) rather than "Removed".

## Responsible access

* robots.txt is read and obeyed for every site (wildcard rules supported).
* At least 1 second between requests to the same site; retries with back-off.
* Bot challenges, CAPTCHAs and access controls are **never** bypassed – the agent is reported as Blocked.
* Only publicly advertised information is collected.

## Tests

```bash
python -m pytest -q
```

Offline tests cover the specification extraction rules, robots.txt parsing, de-duplication (joint
instructions merged, separate units kept apart, ambiguous pairs flagged, conflicts retained), stable IDs and
change detection, and workbook structure.

## Project layout

```
nwtracker/
  run.py            orchestration / CLI          agents/  one module per agent + base framework
  http.py           polite fetcher + robots      extract.py  specification & status rules
  geo.py            postcode → county/submarket  pdf.py      brochure text
  dedupe.py         matching & merging           db.py       SQLite history & change detection
  excel.py          workbook                     report.py   run report
tests/              pytest suite
```

## Known limitations

See section 7 of `output/Latest Run Report.md` (regenerated every run). In short: CBRE and Colliers block automated access;
Cushman & Wakefield currently has no North West industrial listings online; some agents omit postcodes or
specifications; image-only brochures cannot be read; and an online advertisement does not guarantee that
space is still available today.
