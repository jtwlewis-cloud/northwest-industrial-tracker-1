"""Data source adapters. Each exposes fetch(as_of: date) -> FetchResult."""
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
