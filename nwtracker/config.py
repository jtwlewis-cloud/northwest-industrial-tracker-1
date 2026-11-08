"""Static configuration: paths, geography, size bands and agent list."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
OUTPUT_DIR = ROOT / "output"
HISTORY_DIR = OUTPUT_DIR / "history"
REPORT_DIR = OUTPUT_DIR / "reports"
LOG_DIR = ROOT / "logs"
DB_PATH = DATA_DIR / "nw_industrial.sqlite"
WORKBOOK_NAME = "North West Industrial & Logistics Availability.xlsx"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 NWIndustrialAvailabilityTracker/1.0"
)
REQUEST_DELAY_SECONDS = 1.0     # minimum gap between requests to the same host
REQUEST_TIMEOUT = 40
MAX_PDF_BYTES = 20 * 1024 * 1024

COUNTIES = ["Greater Manchester", "Merseyside", "Cheshire", "Lancashire", "Cumbria"]

# Local authority (postcodes.io admin_district) -> county used in the schedule.
DISTRICT_TO_COUNTY = {
    # Greater Manchester
    "Bolton": "Greater Manchester", "Bury": "Greater Manchester", "Manchester": "Greater Manchester",
    "Oldham": "Greater Manchester", "Rochdale": "Greater Manchester", "Salford": "Greater Manchester",
    "Stockport": "Greater Manchester", "Tameside": "Greater Manchester", "Trafford": "Greater Manchester",
    "Wigan": "Greater Manchester",
    # Merseyside
    "Knowsley": "Merseyside", "Liverpool": "Merseyside", "Sefton": "Merseyside",
    "St. Helens": "Merseyside", "St Helens": "Merseyside", "Wirral": "Merseyside",
    # Cheshire (incl. Warrington and Halton unitary authorities)
    "Cheshire East": "Cheshire", "Cheshire West and Chester": "Cheshire",
    "Warrington": "Cheshire", "Halton": "Cheshire",
    # Lancashire (incl. Blackburn with Darwen and Blackpool)
    "Blackburn with Darwen": "Lancashire", "Blackpool": "Lancashire", "Burnley": "Lancashire",
    "Chorley": "Lancashire", "Fylde": "Lancashire", "Hyndburn": "Lancashire", "Lancaster": "Lancashire",
    "Pendle": "Lancashire", "Preston": "Lancashire", "Ribble Valley": "Lancashire",
    "Rossendale": "Lancashire", "South Ribble": "Lancashire", "West Lancashire": "Lancashire",
    "Wyre": "Lancashire",
    # Cumbria (current and pre-2023 districts)
    "Cumberland": "Cumbria", "Westmorland and Furness": "Cumbria", "Allerdale": "Cumbria",
    "Barrow-in-Furness": "Cumbria", "Carlisle": "Cumbria", "Copeland": "Cumbria",
    "Eden": "Cumbria", "South Lakeland": "Cumbria",
}

# Postcode areas that can contain North West addresses (used only as a cheap
# pre-filter before the authoritative postcodes.io lookup).
NW_POSTCODE_AREAS = {"M", "WA", "WN", "BL", "OL", "SK", "L", "CH", "CW", "PR", "BB", "FY", "LA", "CA"}
NW_EXTRA_DISTRICTS = {"SY14"}  # Malpas (Cheshire West and Chester)

# Recognised industrial clusters by postcode district; otherwise the local
# authority is used as the submarket.
SUBMARKET_OVERRIDES = {
    "M17": "Trafford Park", "M41": "Trafford Park / Urmston", "M32": "Trafford Park / Stretford",
    "M44": "Irlam / Port Salford", "M30": "Eccles / Barton", "M50": "Salford Quays",
    "M22": "Wythenshawe / Manchester Airport", "M23": "Wythenshawe / Manchester Airport",
    "M90": "Manchester Airport", "SK8": "Cheadle / Manchester Airport",
    "M11": "East Manchester", "M12": "East Manchester", "M40": "North Manchester",
    "M24": "Middleton / Stakehill", "M26": "Radcliffe / Kearsley", "M28": "Worsley / Walkden",
    "M27": "Swinton / Pendlebury", "M29": "Tyldesley / Astley", "M46": "Atherton",
    "OL10": "Heywood (M62 J19)", "OL11": "Rochdale / Kingsway (M62 J20-21)", "OL16": "Rochdale / Kingsway (M62 J20-21)",
    "BL5": "Westhoughton / Bolton West (M61)", "BL6": "Horwich / Middlebrook (M61)",
    "WN2": "Wigan / Hindley", "WN3": "Wigan South (M6 J25)", "WN5": "Wigan West / Orrell",
    "WA11": "Haydock / St Helens (M6 J23)", "WA12": "Newton-le-Willows / Parkside",
    "WA9": "St Helens", "WA10": "St Helens",
    "WA1": "Warrington Central", "WA2": "Warrington North (M62 J9)", "WA3": "Warrington East / Birchwood (Omega / M62 J11)",
    "WA4": "Warrington South (M6/M56 Stretton)", "WA5": "Warrington West (Omega / M62 J8)",
    "WA7": "Runcorn", "WA8": "Widnes", "WA14": "Altrincham / Broadheath",
    "L24": "Speke / Halewood", "L26": "Halewood", "L33": "Knowsley Industrial Park",
    "L34": "Knowsley / Prescot", "L36": "Huyton", "L30": "Netherton / Aintree",
    "L20": "Bootle / Liverpool Docks", "L9": "Aintree", "L10": "Aintree / Fazakerley", "L11": "Gillmoss / Croxteth",
    "CH62": "Bromborough / Wirral", "CH41": "Birkenhead", "CH44": "Wallasey", "CH46": "Moreton / Wirral",
    "CH65": "Ellesmere Port", "CH66": "Ellesmere Port",
    "CW1": "Crewe", "CW2": "Crewe", "CW4": "Holmes Chapel", "CW7": "Winsford", "CW8": "Northwich",
    "CW9": "Northwich", "CW10": "Middlewich", "CW11": "Sandbach", "CW12": "Congleton",
    "SK10": "Macclesfield", "SK11": "Macclesfield",
    "WN8": "Skelmersdale", "PR2": "Preston North / Red Scar", "PR1": "Preston", "PR4": "Preston West / Fylde",
    "PR5": "South Ribble (Bamber Bridge / Walton Summit)", "PR25": "Leyland", "PR26": "Leyland / Farington",
    "PR6": "Chorley", "PR7": "Chorley / Buckshaw", "PR9": "Southport",
    "BB1": "Blackburn", "BB2": "Blackburn", "BB3": "Darwen", "BB4": "Rossendale", "BB5": "Hyndburn / Accrington",
    "BB10": "Burnley", "BB11": "Burnley", "BB12": "Burnley / Padiham", "BB9": "Nelson / Pendle",
    "FY4": "Blackpool", "FY5": "Thornton-Cleveleys / Wyre", "FY8": "Lytham St Annes",
    "LA1": "Lancaster", "LA3": "Heysham / Morecambe", "LA14": "Barrow-in-Furness", "LA9": "Kendal",
    "CA1": "Carlisle", "CA2": "Carlisle", "CA3": "Carlisle (Kingmoor)", "CA6": "Carlisle North",
    "CA14": "Workington / Lillyhall", "CA28": "Whitehaven", "CA11": "Penrith",
}

SIZE_BANDS = [
    ("Under 10,000 sq ft", 0, 10_000),
    ("10,000–25,000 sq ft", 10_000, 25_000),
    ("25,000–50,000 sq ft", 25_000, 50_000),
    ("50,000–100,000 sq ft", 50_000, 100_000),
    ("100,000–250,000 sq ft", 100_000, 250_000),
    ("Over 250,000 sq ft", 250_000, float("inf")),
]

AVAILABILITY_STATUSES = [
    "Available Now",
    "Available at a Future Date",
    "Under Construction",
    "Proposed / Design and Build",
    "Under Offer",
    "Availability Unconfirmed",
]


def size_band(sqft: float | None) -> str:
    if not sqft:
        return "Size Not Disclosed"
    for label, lo, hi in SIZE_BANDS:
        if lo <= sqft < hi:
            return label
    return "Size Not Disclosed"
