"""Polite HTTP client: robots.txt checks, per-host rate limiting, retries,
and detection of bot-protection pages (which are reported, never bypassed)."""
from __future__ import annotations

import logging
import re
import threading
import time
from urllib.parse import urlparse

import requests

from . import config

log = logging.getLogger(__name__)


class AccessBlocked(Exception):
    """The site refused automated access (CAPTCHA / challenge / 403)."""


class RobotsDisallowed(Exception):
    """robots.txt disallows the URL for our user agent."""


class Robots:
    """Minimal robots.txt parser supporting '*' and '$' wildcards (the
    standard library parser ignores them, which matters for e.g. JLL)."""

    def __init__(self, text: str | None):
        self.rules: list[tuple[bool, str]] = []
        if not text:
            return
        groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
        agents: list[str] = []
        rules: list[tuple[bool, str]] = []
        last_was_rule = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, val = [x.strip() for x in line.split(":", 1)]
            key = key.lower()
            if key == "user-agent":
                if last_was_rule:
                    groups.append((agents, rules))
                    agents, rules = [], []
                agents.append(val.lower())
                last_was_rule = False
            elif key in ("allow", "disallow"):
                last_was_rule = True
                if val:
                    rules.append((key == "allow", val))
        groups.append((agents, rules))
        star = [r for a, r in groups if "*" in a]
        for r in star:
            self.rules.extend(r)

    @staticmethod
    def _to_regex(pattern: str) -> re.Pattern:
        anchored = pattern.endswith("$")
        if anchored:
            pattern = pattern[:-1]
        rx = "".join(".*" if c == "*" else re.escape(c) for c in pattern)
        return re.compile("^" + rx + ("$" if anchored else ""))

    def allowed(self, url: str) -> bool:
        p = urlparse(url)
        path = p.path or "/"
        if p.query:
            path += "?" + p.query
        best: tuple[int, bool] | None = None
        for allow, pat in self.rules:
            if self._to_regex(pat).match(path):
                ln = len(pat)
                if best is None or ln > best[0] or (ln == best[0] and allow):
                    best = (ln, allow)
        return True if best is None else best[1]


CHALLENGE_MARKERS = (
    "cf-browser-verification", "challenges.cloudflare.com", "Just a moment...",
    "_cf_chl_opt", "captcha-delivery", "Access Denied</h1>", "px-captcha",
)


class Fetcher:
    """Shared, thread-safe fetcher. One instance per run."""

    def __init__(self, delay: float = config.REQUEST_DELAY_SECONDS, respect_robots: bool = True):
        self.delay = delay
        self.respect_robots = respect_robots
        self._local = threading.local()
        self._host_lock: dict[str, threading.Lock] = {}
        self._last: dict[str, float] = {}
        self._robots: dict[str, Robots] = {}
        self._glock = threading.Lock()
        self.request_count = 0
        self._dead_hosts: set[str] = set()

    @property
    def session(self) -> requests.Session:
        s = getattr(self._local, "s", None)
        if s is None:
            s = requests.Session()
            s.headers.update({
                "User-Agent": config.USER_AGENT,
                "Accept-Language": "en-GB,en;q=0.9",
            })
            self._local.s = s
        return s

    def _lock_for(self, host: str) -> threading.Lock:
        with self._glock:
            return self._host_lock.setdefault(host, threading.Lock())

    # public APIs designed for programmatic use can be called faster
    HOST_DELAY = {"api.postcodes.io": 0.1}

    def _throttle(self, host: str) -> None:
        with self._lock_for(host):
            wait = self._last.get(host, 0) + self.HOST_DELAY.get(host, self.delay) - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last[host] = time.monotonic()

    def robots_for(self, url: str) -> Robots:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        with self._glock:
            if base in self._robots:
                return self._robots[base]
        text = None
        try:
            r = self.session.get(base + "/robots.txt", timeout=config.REQUEST_TIMEOUT)
            if r.status_code == 200 and "text/plain" in r.headers.get("content-type", "text/plain"):
                text = r.text
        except requests.RequestException as e:  # robots unreachable -> treat as allow-all
            log.debug("robots fetch failed for %s: %s", base, e)
        rb = Robots(text)
        with self._glock:
            self._robots[base] = rb
        return rb

    def check_robots(self, url: str) -> None:
        if self.respect_robots and not self.robots_for(url).allowed(url):
            raise RobotsDisallowed(url)

    def request(self, method: str, url: str, *, retries: int = 3, check_robots: bool = True,
                **kw) -> requests.Response:
        if check_robots:
            self.check_robots(url)
        host = urlparse(url).netloc
        if host in self._dead_hosts:
            raise AccessBlocked(f"{host} is not reachable from this network (refused earlier in this run)")
        kw.setdefault("timeout", config.REQUEST_TIMEOUT)
        err: Exception | None = None
        for attempt in range(retries):
            self._throttle(host)
            try:
                r = self.session.request(method, url, **kw)
                self.request_count += 1
            except requests.exceptions.ProxyError as e:
                self._dead_hosts.add(host)
                raise AccessBlocked(f"{host} refused by the network proxy (host not allowed): {e}") from e
            except requests.RequestException as e:
                err = e
                time.sleep(2 ** attempt)
                continue
            body_head = r.text[:5000] if "text" in r.headers.get("content-type", "") else ""
            if r.status_code in (403, 429, 503) and any(m in body_head for m in CHALLENGE_MARKERS):
                raise AccessBlocked(f"{host} returned a bot-protection challenge (HTTP {r.status_code})")
            if r.status_code in (429, 500, 502, 503, 504):
                err = requests.HTTPError(f"HTTP {r.status_code} for {url}")
                time.sleep(2 ** (attempt + 1))
                continue
            if r.status_code == 403:
                raise AccessBlocked(f"{host} refused access (HTTP 403) for {url}")
            r.raise_for_status()
            return r
        raise err or RuntimeError(f"request failed: {url}")

    def get(self, url: str, **kw) -> requests.Response:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw) -> requests.Response:
        return self.request("POST", url, **kw)
