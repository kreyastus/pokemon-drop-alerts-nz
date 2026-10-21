"""Posts events to Discord channels via webhooks.

Each event type can go to its own channel, and can ping a role, for example
@Pre-orders. Messages are batched (up to 10 embeds each) and Discord's rate
limits are respected."""
from __future__ import annotations

import logging
import time

import requests

from ..models import Event, EVENT_LABELS, PREORDER, NEW_LISTING, RESTOCK, PRICE_DROP

log = logging.getLogger(__name__)

COLOURS = {
    PREORDER: 0x8E44AD,     # purple
    NEW_LISTING: 0x2ECC71,  # green
    RESTOCK: 0x3498DB,      # blue
    PRICE_DROP: 0xF1C40F,   # yellow
}
EMOJI = {PREORDER: "🗓️", NEW_LISTING: "🆕", RESTOCK: "📦", PRICE_DROP: "💸"}


def _money(v):
    return f"NZ${v:,.2f}" if v is not None else "Price not listed"


def rrp_note(price, rrp, flag_percent: float = 15):
    """'NZ$89.99' at or near RRP; 'NZ$89.99 · 67% over RRP' when it's well above."""
    if not rrp:
        return None
    if price is not None and price >= rrp * (1 + flag_percent / 100):
        return f"{_money(rrp)} · {round((price - rrp) / rrp * 100)}% over RRP"
    if price is not None and price < rrp:
        return f"{_money(rrp)} · {round((rrp - price) / rrp * 100)}% under RRP"
    return _money(rrp)


def build_embed(e: Event, flag_percent: float = 15) -> dict:
    p = e.product
    fields = [
        {"name": "Retailer", "value": e.store_name, "inline": True},
        {"name": "Price", "value": _money(p.price), "inline": True},
    ]
    note = rrp_note(p.price, p.rrp, flag_percent)
    if note:
        name = "⚠️ Well above RRP" if "over RRP" in note else "RRP"
        fields.append({"name": name, "value": note, "inline": True})
    if p.limit:
        fields.append({"name": "Purchase limit", "value": f"{p.limit} per customer", "inline": True})
    if e.type == PRICE_DROP and e.old_price:
        saved = e.old_price - (p.price or 0)
        fields.append({"name": "Was", "value": f"{_money(e.old_price)} (save {_money(saved)})", "inline": True})
    elif p.compare_at_price and p.price and p.compare_at_price > p.price:
        fields.append({"name": "Usually", "value": _money(p.compare_at_price), "inline": True})
    embed = {
        "title": p.title[:256],
        "url": p.url,
        "color": COLOURS.get(e.type, 0x95A5A6),
        "author": {"name": f"{EVENT_LABELS.get(e.type, e.type)} {EMOJI.get(e.type, '')}".strip()},
        "fields": fields,
        "footer": {"text": "PokéDrop NZ · check the retailer's page before you buy"},
        "timestamp": e.detected_at,
    }
    if p.image:
        img = p.image if p.image.startswith("http") else f"https:{p.image}"
        embed["thumbnail"] = {"url": img}
    return embed


class DiscordNotifier:
    def __init__(self, config: dict):
        """config example:
        {
          "webhook": "https://discord.com/api/webhooks/...",   # default channel
          "webhooks": {"preorder": "https://...", ...},       # optional per type
          "roles": {"preorder": "123456789012345678"},        # optional role pings
          "store_roles": {"jbhifi": "2345..."},               # optional per store
          "events": ["preorder", "new", "restock", "price_drop"],
          "username": "PokéDrop NZ"
        }
        """
        self.default = config.get("webhook")
        self.by_type = config.get("webhooks") or {}
        self.roles = config.get("roles") or {}
        self.store_roles = config.get("store_roles") or {}
        self.enabled_events = set(config.get("events") or [PREORDER, NEW_LISTING, RESTOCK, PRICE_DROP])
        self.username = config.get("username", "PokéDrop NZ")
        self.avatar = config.get("avatar_url")
        self.flag_percent = float(config.get("rrp_flag_percent", 15))

    def _post(self, url: str, payload: dict):
        for _ in range(5):
            r = requests.post(url, json=payload, params={"wait": "true"}, timeout=20)
            if r.status_code == 429:
                retry = float((r.json() or {}).get("retry_after", 2))
                log.info("Discord rate limit, waiting %.1fs", retry)
                time.sleep(retry + 0.25)
                continue
            if r.status_code >= 400:
                log.error("Discord webhook error %s: %s", r.status_code, r.text[:300])
            return r
        log.error("Gave up posting to Discord after repeated rate limits")

    def send(self, events: list[Event]):
        groups: dict[tuple[str, str], list[Event]] = {}
        for e in events:
            if e.type not in self.enabled_events:
                continue
            url = self.by_type.get(e.type) or self.default
            if not url:
                continue
            groups.setdefault((url, e.type), []).append(e)

        for (url, etype), evs in groups.items():
            for i in range(0, len(evs), 10):
                chunk = evs[i : i + 10]
                role_ids = {self.roles[etype]} if self.roles.get(etype) else set()
                role_ids |= {self.store_roles[e.product.store_id] for e in chunk if e.product.store_id in self.store_roles}
                mentions = " ".join(f"<@&{r}>" for r in sorted(role_ids))
                payload = {
                    "username": self.username,
                    "content": mentions or None,
                    "embeds": [build_embed(e, self.flag_percent) for e in chunk],
                    "allowed_mentions": {"parse": [], "roles": sorted(role_ids)},
                }
                if self.avatar:
                    payload["avatar_url"] = self.avatar
                self._post(url, payload)
                time.sleep(1)  # stay comfortably under 30 messages a minute
