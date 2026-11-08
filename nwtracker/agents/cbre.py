"""CBRE – www.cbre.co.uk.

The site sits behind a Cloudflare interactive challenge for automated
clients. The scraper checks the property search page once; if the challenge
is served the agent is recorded as 'Blocked' (the challenge is never bypassed)."""
from __future__ import annotations

import re

from .base import AgentScraper

SEARCH = "https://www.cbre.co.uk/properties/industrial-and-logistics"


class CBRE(AgentScraper):
    name = "CBRE"
    website = "https://www.cbre.co.uk/"
    method = "Property search page (checked for access; Cloudflare challenge is not bypassed)"

    def discover(self):
        self.result.search_urls = [SEARCH]
        html = self.f.get(SEARCH).text  # raises AccessBlocked on a challenge page
        links = sorted(set(re.findall(r'href="(/properties/[^"#?]+)"', html)))
        if not links:
            raise RuntimeError("search page returned no property links (JavaScript-only listing app)")
        raise RuntimeError(f"unexpected CBRE page structure ({len(links)} links) – extractor needs review")
