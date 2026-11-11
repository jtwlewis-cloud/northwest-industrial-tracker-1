# Daily Financial & UK Property Investment Market Monitor

A Python system that produces a professional **Daily Financial & Property Investment
Briefing** for UK commercial property investment (industrial, logistics and offices),
with a focus on the North West industrial and logistics market. It is designed to run
at **08:00 Europe/London every weekday**.

Each run:

1. Collects the latest bond yields, policy rates and inflation data from official sources.
2. Merges them into a permanent CSV history without overwriting good data with missing or stale data.
3. Calculates daily, 7-day and 30-day movements in basis points, curve spreads and property-yield-versus-gilt spreads.
4. Carries forward the latest **published** prime property yields from an evidence register. They are never estimated.
5. Renders the briefing in **Markdown and HTML**, with trend charts once enough verified history exists.
6. Writes an audit trail (source URLs, observation dates, revisions, failures) and reports any retrieval failures in the briefing.

Sample output: [`reports/2026/11/briefing-2026-11-09.md`](reports/2026/11/briefing-2026-11-09.md)
(also `.html`), produced from live data on 9 November 2026.

---

## Data sources

| Data | Primary source | Fallback | Notes |
|---|---|---|---|
| UK 5Y / 10Y gilt | Bank of England IADB `IUDSNPY`, `IUDMNPY` (fitted nominal **par** yields) | Cited entries in `data/manual_observations.csv` | Par yields from the fitted curve are not benchmark-gilt redemption yields. The report labels which one is used. |
| UK 2Y / 30Y gilt | — (no free official daily feed) | Manual entries | Shown as "Not verified" when no cited figure is held. |
| US 2/5/10/30Y Treasury | US Treasury daily par yield curve CSV | FRED `DGS*` | End-of-day constant-maturity yields. |
| Bank Rate | BoE IADB `IUDBEDR` | Manual entry citing the MPC summary | |
| SONIA | BoE IADB `IUDSOIA` | FRED `IUDSOIA` (BoE republication) | Overnight fixing only, never term SONIA or SONIA swaps. |
| 5Y SONIA swap | Manual (agent research panels) | — | Labelled as a finance-cost reference. |
| Fed target range | FRED `DFEDTARL` / `DFEDTARU` | — | |
| UK CPI, CPIH, core CPI | ONS time-series API (`D7G7`, `L55O`, `DKO8`) | — | Includes publication date and next release date. |
| US CPI, core CPI | BLS index via FRED (`CPIAUCNS`, `CPILFENS`), annual rate calculated | — | If the base month is missing (e.g. October 2025, not collected during the US shutdown), the rate is "Not verified". |
| Prime property yields | `data/property_yields.csv` evidence register | — | Every row needs a source URL, period, evidence date and basis (NIY / equivalent / not stated). |
| Events | `config.py` MPC/FOMC dates, ONS API next-release dates, `data/events.csv` | — | |

**Bank of England access:** the BoE website sometimes refuses automated requests
(HTTP 302/403 from its bot protection). The fetcher identifies itself honestly, retries
politely and **does not try to bypass this**. On a refusal, the stored history is used,
the failure is logged and shown in the briefing, and any cited manual figure fills the gap.

## Data-quality rules built into the code

- **No invented numbers.** Missing data prints as "Not verified". Property rows without a source URL are rejected.
- **No overwriting.** A missing value never replaces a stored value. A lower-priority source (manual or secondary) never replaces an official one, and any disagreement of 3bp or more is listed under *Source discrepancies*. Revisions from the same or a higher-priority source are applied and logged with the old value.
- **Like-for-like movements.** When current official data exists, movements use only that series. Comparisons that cross sources or instruments are marked † in the tables.
- **Staleness.** Daily series older than 3 business days (UK or US holiday calendar) are flagged. Property yields older than 45 days are labelled "carried forward (N days)".
- **Correct dates.** Observation date, publication date and report date are kept separate. Policy rates show the date the rate took effect.
- **Basis-point arithmetic.** 1 percentage point = 100bp. Ranges use the midpoint, and the briefing says so.
- **Property-vs-gilt spread** is presented as a simple yield gap. Its change is split into the property-yield and gilt contributions.

## Repository layout

```
monitor/                 Python package
  sources/               treasury.py, fred.py, boe.py, ons.py  (one adapter per source)
  config.py              series, table mappings, MPC/FOMC dates, paths
  store.py               CSV history, overwrite rules, audit log, run log
  metrics.py             bp movements, staleness, inflation trend
  property.py            evidence register, Table C rows, Table D spreads
  commentary.py          confirmed developments + analyst note / rule-based fallback
  charts.py              matplotlib trend charts
  report.py              Markdown + HTML rendering
  pipeline.py            orchestration
  __main__.py            CLI (run, gate)
templates/briefing.md.j2 report template
data/
  observations.csv       full observation history (auto-maintained)
  audit_log.csv          every insert / revision / rejected value / fetch failure
  run_log.csv            one row per run
  manual_observations.csv  cited figures for series with no free official feed
  property_yields.csv    prime yield evidence register
  events.csv             curated calendar
  analyst_notes/YYYY-MM-DD.md  optional interpretation for that day's briefing
reports/YYYY/MM/briefing-YYYY-MM-DD.{md,html} and charts/
.github/workflows/daily-briefing.yml
tests/
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate     # Python 3.11+
pip install -r requirements.txt
python -m pytest -q
python -m monitor run                     # today's briefing (London date)
python -m monitor run --date 2026-11-09   # a specific date
python -m monitor run --offline           # rebuild from stored + manual data only
```

No API keys are required. Outbound HTTPS access is needed to `home.treasury.gov`,
`fred.stlouisfed.org`, `www.bankofengland.co.uk` and `www.ons.gov.uk`.

## Scheduling options

### Option A — GitHub Actions (included)

`.github/workflows/daily-briefing.yml` runs on weekdays at 06:52 and 07:52 UTC. GitHub
cron has no time zones, so `python -m monitor gate` keeps only the run that falls at
or after 07:45 **London** time, which keeps the briefing at 08:00 through the GMT/BST
changes. The job runs the tests, builds the briefing, commits `reports/` and `data/`
back to the default branch, uploads the reports as an artefact, and raises a workflow
warning listing any data-retrieval failures.

To activate:
1. Merge this branch into the default branch. Scheduled workflows only run from the default branch.
2. In the repository settings, go to *Settings → Actions → General → Workflow permissions* and allow **Read and write**.
3. Trigger one run by hand (*Actions → Daily financial & property briefing → Run workflow*) to confirm it works.

GitHub can delay scheduled jobs at busy times, so expect delivery between about 08:00 and 08:30.

### Option B — Claude scheduled task (simpler, adds analysis)

A Claude Code scheduled task can run the same pipeline each weekday at 08:00 London
time, and also do what the code cannot do mechanically:
- read the latest agent research (Knight Frank, Savills, CBRE, C&W, JLL) and append new evidence to `data/property_yields.csv`;
- write `data/analyst_notes/YYYY-MM-DD.md` (executive summary, rate outlook, 200–300-word commentary, 100–150-word North West outlook), separating confirmed facts from interpretation;
- run `python -m monitor run`, then commit and push.

The two options can run together: GitHub Actions provides the reliable data run, and
Claude adds the research and commentary.

## Daily and periodic maintenance

| Task | Frequency | Where |
|---|---|---|
| Add new prime yield evidence (new row per publication; never edit old rows) | Monthly (KF/Savills guides), quarterly (C&W/CBRE/JLL MarketBeats) | `data/property_yields.csv` |
| Add cited figures for UK 2Y/30Y gilts or 5Y SONIA swaps, if needed | As available | `data/manual_observations.csv` |
| Write the day's interpretation (optional; otherwise a labelled rule-based fallback is used) | Daily | `data/analyst_notes/YYYY-MM-DD.md` |
| Update MPC and FOMC dates | Annually | `monitor/config.py` |
| Add other scheduled events (US CPI, UK GDP, fiscal events) | Weekly | `data/events.csv` |

### Property register columns

`series_id, sector, description, provider, basis, low, high, period, evidence_date,
publication_date, source_url, sentiment, substitution_note, notes`

- `basis`: `NIY`, `Equivalent` or `Not stated`. Never assume it.
- `low`/`high`: a single figure uses the same value for both.
- `substitution_note`: required when the series stands in for the table row (e.g. a Manchester figure used for the North West, or KF "Major Regional Cities" used for Manchester offices). It is printed under Table C.
- Table C rows and Table D spreads are mapped in `monitor/config.py` (`PROPERTY_TABLE_C`, `PROPERTY_SPREADS`). Keep the spread rows on one consistent basis and source.

## Property news, listed shares and REIT modules

The briefing runs in this order: Executive Summary; bond yields; interest rates; inflation; prime yields; property-versus-gilt spreads; listed share prices; REIT valuation; UK industrial news; North West news; office and investment news; *What This Means for the North West Industrial Market*; upcoming events; then an appendix (collapsed in HTML) with data quality notes, definitions and sources.

| Module | Data file | How it is filled |
|---|---|---|
| Daily property news (8–12 stories, labelled and ranked) | `data/news_log.csv` | Researched each morning and appended with `first_reported` = briefing date. The pipeline rejects any story whose URL or headline was reported on an earlier date, unless the row is marked `status=follow-up`. |
| Share prices | `data/watchlist.csv`, `data/share_prices.csv` (history) | US listings come from the Nasdaq end-of-day API (no key). London and Euronext listings need a licensed feed; see below. Cited closing prices can be added to `data/manual_prices.csv` and are labelled secondary. |
| Company announcements (RNS) | `data/announcements.csv` | Fetched automatically from Investegate for UK tickers. Routine filings (Form 8, holdings, voting rights, own-share transactions) are filtered out. |
| REIT fundamentals (EPRA NTA, LTV, cost of debt, WAULT, occupancy, like-for-like rent growth, ERV growth, pipeline, dividend) | `data/reit_fundamentals.csv` | Entered from company results and trading updates, with reporting period, report date and source URL. The share-price premium or discount to NTA is calculated automatically. |
| SEGRO / Prologis offer look-through | — | 0.0920 × Prologis close ÷ USD/GBP (FRED `DEXUSUK`), compared with SEGRO's price when available. |
| Alerts | — | Daily share moves of 3% or more, prime-yield changes in the last 7 days, North West transactions flagged in the news log, and watchlist corporate actions. |

**London and Euronext prices.** Yahoo Finance and Stooq refuse automated clients unless they pretend to be a web browser, which this project does not do. The London Stock Exchange site blocks automated access. To enable UK and European prices:
1. Get a Twelve Data key on a plan that covers LSE and Euronext. The free plan is US-only.
2. Save it as a network credential for host `api.twelvedata.com`, header `Authorization`, prefix `apikey`, and allow that host.
3. Set the non-secret environment variable `TWELVEDATA_ENABLED=1`.

Until then those rows show "Not verified", and the gap is listed in the appendix.

## Known limitations

- **Market-implied BoE expectations** (OIS or SONIA futures) need a paid data source. Until one is configured, the briefing reports them as "Not verified" and gives only cited qualitative guidance.
- **UK 2Y/30Y gilts and 5Y SONIA swaps** have no free official daily feed here, so they depend on cited manual entries.
- **North West-specific prime yields** are published only occasionally (the latest found is Knight Frank's Q4 2025 Manchester figure). The register marks them as carried forward.
- **US CPI release dates** are not captured from FRED. Use `data/events.csv` for upcoming releases.
