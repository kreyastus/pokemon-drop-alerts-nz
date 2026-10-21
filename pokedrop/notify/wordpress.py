"""Sends events to the PokéDrop Feed WordPress plugin.

Requests are signed with HMAC-SHA256 using a shared secret, so nobody else
can post fake drops to your site."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time

import requests

from ..models import Event

log = logging.getLogger(__name__)


def sign(secret: str, timestamp: str, body: bytes) -> str:
    msg = timestamp.encode() + b"." + body
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


class WordPressNotifier:
    def __init__(self, config: dict):
        base = config["url"].rstrip("/")
        self.endpoint = base + "/wp-json/pokedrop/v1/drops"
        # Works even when the site uses "Plain" permalinks.
        self.fallback = base + "/?rest_route=/pokedrop/v1/drops"
        self.secret = config["secret"]

    def _post(self, payload: dict):
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
        ts = str(int(time.time()))
        headers = {
            "Content-Type": "application/json",
            "X-PokeDrop-Timestamp": ts,
            "X-PokeDrop-Signature": sign(self.secret, ts, body),
            # Cloudflare turns away the default "python-requests" user agent.
            "User-Agent": "PokeDropNZ/1.0 (+https://github.com/kreyastus/pokemon-drop-alerts-nz)",
        }
        r = requests.post(self.endpoint, data=body, headers=headers, timeout=30)
        not_api = r.status_code == 404 or "json" not in r.headers.get("Content-Type", "")
        if not_api and self.endpoint != self.fallback:
            log.info("Pretty REST URL not found, switching to ?rest_route=")
            self.endpoint = self.fallback
            r = requests.post(self.endpoint, data=body, headers=headers, timeout=30)
        if r.status_code >= 400:
            log.error("WordPress error %s: %s", r.status_code, r.text[:300])
        return r

    def send(self, events: list[Event]):
        for i in range(0, len(events), 100):
            chunk = [e.to_dict() for e in events[i : i + 100]]
            r = self._post({"drops": chunk})
            if r is not None and r.ok:
                log.info("Sent %d drops to WordPress", len(chunk))

    def send_status(self, stores: list[dict], upcoming: list[dict] | None = None, source: str = "default"):
        """Heartbeat for the site: when each retailer was last checked, plus every
        pre-order currently listed (for the release calendar). `source` keeps
        the GitHub and cPanel scanners from overwriting each other's lists."""
        payload = {"status": stores, "source": source}
        if upcoming is not None:
            payload["upcoming"] = upcoming
        self._post(payload)

    def send_catalogue(self, stores: list[str], items: list[dict], source: str = "default", chunk: int = 250) -> bool:
        """Every product at the given retailers, for price history, best deals and
        the retailer pages. Sent in parts so no single request is too big."""
        parts = [items[i : i + chunk] for i in range(0, len(items), chunk)] or [[]]
        ok = True
        for n, part in enumerate(parts, 1):
            r = self._post({"catalogue": {"stores": stores, "items": part, "part": n, "parts": len(parts)}, "source": source})
            ok = ok and r is not None and r.ok
        if ok:
            log.info("Sent %d products to WordPress for price history", len(items))
        return ok
