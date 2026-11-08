# North West Industrial & Logistics Availability Tracker

A reusable Python application that searches the public websites of 12 commercial property agents,
collects every advertised industrial and logistics property in the North West of England, removes
duplicate (jointly marketed) listings, keeps a permanent history in SQLite and produces a dated,
filterable Excel availability schedule with a market supply analysis.

**Latest outputs (committed in this repository):**

| File | What it is |
|---|---|
| `output/North West Industrial & Logistics Availability.xlsx` | Latest schedule (19 worksheets) |
| `output/history/… <date> run<N>.xlsx` | Dated copy of every run |
| `output/Latest Run Report.md` | Coverage, totals, duplicates, missing information, limitations |
| `data/nw_industrial.sqlite` | Persistent history database (all runs, listings, snapshots, changes) |

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
`pse-api.sharplaunch.com`, `sdk.sharplaunch.com`, `assets.cushmanwakefield.com`).

## Running

```bash
python -m nwtracker                      # full run: all 12 agents + brochures (≈20–30 min)
python -m nwtracker --no-brochures       # faster, web pages only
python -m nwtracker --agents jll,b8,dtre # selected agents only
python -m nwtracker --delay 2            # slower, gentler crawling (seconds between requests per site)
python -m nwtracker -v                   # debug logging
```

Agent keys: `jll, cbre, cushman, avisonyoung, willsill, b8, dtre, cpp, bc, daviesharrison, legatowen, lsh`.

Each run:

1. Searches the 12 agencies in parallel – each agent is an independent module, so one failing website
   never stops the others (its status is recorded as Success / Partial / Failed / Blocked).
2. Extracts the public listings and reads brochures.
3. Matches listings to properties recorded in earlier runs (stable `NW-00001` style IDs).
4. Identifies new, changed, removed and re-listed advertisements.
5. De-duplicates jointly marketed properties.
6. Updates the SQLite history database.
7. Writes a new dated workbook plus `output/North West Industrial & Logistics Availability.xlsx` (latest).
8. Highlights changes (green = new, yellow = changed) and lists them on *Changes Since Last Search*.

To run it automatically, schedule the command, e.g. weekly with cron:

```
0 6 * * MON cd /path/to/northwest-industrial-tracker-1 && python -m nwtracker >> logs/cron.log 2>&1
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

| Table | Contents |
|---|---|
| `runs` | One row per run |
| `agent_runs` | Per-agent coverage, counts, errors for each run |
| `listings` | Every listing seen (included and excluded with reason), per run |
| `listing_map` | Listing URL → stable property ID |
| `properties` | Property register: first/last seen, active/removed |
| `property_snapshots` | Full merged record per property per run (for trend analysis) |
| `changes` | New / Changed / Removed / Re-listed / Not re-checked events |
| `duplicate_reviews` | Merge and ambiguous-match decisions with reasons |
| `geo_cache` | Cached postcode lookups |

A property whose only agents could not be searched in a run is reported as "Not re-checked" rather than removed.

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

See section 7 of `output/Latest Run Report.md` (regenerated every run). In short: CBRE blocks automated access;
Cushman & Wakefield currently has no North West industrial listings online; some agents omit postcodes or
specifications; image-only brochures cannot be read; and an online advertisement does not guarantee that
space is still available today.
