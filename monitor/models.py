from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date


@dataclass
class Observation:
    series_id: str
    obs_date: date
    value: float | None
    source: str                 # human-readable source name
    source_url: str
    source_type: str = "official"   # official | manual | secondary | derived
    publication_date: date | None = None
    retrieved_at: str = ""      # ISO timestamp
    notes: str = ""

    def to_row(self) -> dict:
        d = asdict(self)
        d["obs_date"] = self.obs_date.isoformat()
        d["publication_date"] = self.publication_date.isoformat() if self.publication_date else ""
        d["value"] = "" if self.value is None else f"{self.value:.4f}".rstrip("0").rstrip(".")
        return d


@dataclass
class FetchResult:
    source: str
    observations: list[Observation] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)   # e.g. ONS next release dates
