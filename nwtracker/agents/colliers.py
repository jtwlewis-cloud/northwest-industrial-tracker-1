"""Colliers – www.colliers.com (UK property search).
Like CBRE, the site serves a Cloudflare challenge to automated clients; the
agent is recorded as Blocked and the challenge is never bypassed."""
from __future__ import annotations

from .base import AgentScraper

SEARCH = "https://www.colliers.com/en-gb/properties"


class Colliers(AgentScraper):
    name = "Colliers"
    website = "https://www.colliers.com/en-gb/properties"
    method = "UK property search page (checked for access; Cloudflare challenge is not bypassed)"

    def discover(self):
        self.result.search_urls = [SEARCH]
        self.f.get(SEARCH)  # raises AccessBlocked on a challenge page
        raise RuntimeError("Colliers search page reachable but its listing format has not been mapped yet")
