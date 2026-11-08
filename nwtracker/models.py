"""Data model for one agent's advertisement of one property/unit."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Listing:
    agent: str
    url: str
    title: str = ""
    address: str = ""
    postcode: str = ""
    town: str = ""
    county: str = ""
    local_authority: str = ""
    submarket: str = ""
    property_name: str = ""
    unit_number: str = ""
    estate: str = ""
    property_type: str = ""
    total_sqft: float | None = None
    min_sqft: float | None = None
    max_sqft: float | None = None
    warehouse_sqft: float | None = None
    office_sqft: float | None = None
    eaves_m: float | None = None
    dock_doors: int | None = None
    level_doors: int | None = None
    yard_depth_m: float | None = None
    site_acres: float | None = None
    power: str = ""
    epc: str = ""
    breeam: str = ""
    sprinklers: str = ""
    build_status: str = ""          # Existing / Existing – Refurbished / New Build / Design & Build
    specification: str = ""
    availability_date: str = ""
    availability_status: str = ""   # one of config.AVAILABILITY_STATUSES
    marketing_status: str = ""      # as advertised (To Let / For Sale / Under Offer ...)
    rent_psf: float | None = None
    rent_text: str = ""
    price_text: str = ""
    tenure: str = ""
    agent_contacts: str = ""
    brochure_urls: list[str] = field(default_factory=list)
    description: str = ""
    notes: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)   # web / brochure
    lat: float | None = None
    lng: float | None = None
    excluded_reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("raw", None)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Listing":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)
