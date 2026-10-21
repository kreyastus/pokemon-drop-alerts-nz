"""A polite HTTP client: identifies itself, honours robots.txt, spaces out requests
to the same host and retries transient failures with back-off."""
from __future__ import annotations

import logging
import time
import urllib.robotparser
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

DEFAULT_UA = (
    "Mozilla/5.0 (compatible; PokeDropNZ/1.0; personal stock alerts; "
    "+https://github.com/kreyastus/pokemon-drop-alerts-nz)"
)


class RobotsDisallowed(Exception):
    pass


class PoliteClient:
    def __init__(
        self,
        user_agent: str = DEFAULT_UA,
        min_delay: float = 2.0,
        timeout: float = 20.0,
        respect_robots: bool = True,
        retries: int = 2,
    ):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Language": "en-NZ,en;q=0.9",
            }
        )
        self.user_agent = user_agent
        self.min_delay = min_delay
        self.timeout = timeout
        self.respect_robots = respect_robots
        self.retries = retries
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    # robots.txt ------------------------------------------------------------
    def _robots_for(self, url: str):
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.session.get(f"{base}/robots.txt", timeout=self.timeout)
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                else:
                    rp = None  # no robots.txt (or error) means no restrictions
            except requests.RequestException:
                rp = None
            self._robots[base] = rp
        return self._robots[base]

    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        rp = self._robots_for(url)
        return True if rp is None else rp.can_fetch(self.user_agent, url)

    # throttling ------------------------------------------------------------
    def _wait_for_host(self, url: str):
        host = urlparse(url).netloc
        last = self._last_hit.get(host)
        if last is not None:
            gap = time.monotonic() - last
            if gap < self.min_delay:
                time.sleep(self.min_delay - gap)
        self._last_hit[host] = time.monotonic()

    # requests --------------------------------------------------------------
    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        if not self.allowed(url):
            raise RobotsDisallowed(url)
        attempt = 0
        while True:
            self._wait_for_host(url)
            try:
                r = self.session.request(method, url, timeout=self.timeout, **kwargs)
            except requests.RequestException as exc:
                if attempt >= self.retries:
                    raise
                log.debug("%s %s failed (%s), retrying", method, url, exc)
            else:
                if r.status_code in (429, 500, 502, 503, 504) and attempt < self.retries:
                    wait = float(r.headers.get("Retry-After", 0) or 0) or 5 * (attempt + 1)
                    log.debug("%s %s -> %s, waiting %.0fs", method, url, r.status_code, wait)
                    time.sleep(min(wait, 60))
                else:
                    return r
            attempt += 1
            time.sleep(2 ** attempt)

    def get(self, url: str, **kwargs) -> requests.Response:
        return self._request("GET", url, **kwargs)

    def post_form(self, url: str, data: dict, headers: dict | None = None) -> requests.Response:
        """A form POST with the same manners as get(): robots.txt, spacing, retries.
        Only used for read-only lookups a shop's own pages make, such as branch stock."""
        return self._request("POST", url, data=data, headers=headers or {})

    def get_json(self, url: str, **kwargs):
        r = self.get(url, headers={"Accept": "application/json"}, **kwargs)
        r.raise_for_status()
        return r.json()

    def get_text(self, url: str, **kwargs) -> str:
        r = self.get(url, **kwargs)
        r.raise_for_status()
        return r.text
