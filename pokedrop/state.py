"""Remembers what each store looked like last time, and turns the difference
into events (new listing, pre-order, restock, price drop)."""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone

from .models import Event, Product, NEW_LISTING, PREORDER, RESTOCK, PRICE_DROP

log = logging.getLogger(__name__)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse(ts: str | None):
    try:
        return datetime.fromisoformat(ts) if ts else None
    except ValueError:
        return None


class State:
    def __init__(self, path: str):
        self.path = path
        self.data = {"stores": {}, "products": {}}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                self.data = json.load(fh)
        self.data.setdefault("stores", {})
        self.data.setdefault("products", {})

    def save(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(self.path)))
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=1, sort_keys=True, ensure_ascii=False)
        os.replace(tmp, self.path)

    def prune(self, days: int = 45):
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        prods = self.data["products"]
        stale = [k for k, v in prods.items() if (_parse(v.get("last_seen")) or cutoff) < cutoff]
        for k in stale:
            del prods[k]
        releases = self.data.get("releases", {})
        for k in [k for k in releases if k not in prods]:
            del releases[k]
        if stale:
            log.info("Pruned %d products not seen for %d days", len(stale), days)

    # ------------------------------------------------------------------ diff
    def diff(
        self,
        store: dict,
        products: list[Product],
        price_drop_pct: float = 5.0,
        cooldown_minutes: int = 60,
        missing_means_sold_out: bool = True,
    ) -> list[Event]:
        sid = store["id"]
        ts = now_iso()
        now = _parse(ts)
        prods = self.data["products"]
        store_state = self.data["stores"].setdefault(sid, {})
        seeding = not store_state.get("seeded")
        events: list[Event] = []

        def recently_alerted(rec, etype) -> bool:
            last = _parse((rec.get("last_alert") or {}).get(etype))
            return bool(last and now - last < timedelta(minutes=cooldown_minutes))

        def emit(etype, p, rec, old_price=None):
            if recently_alerted(rec, etype):
                return
            events.append(Event(etype, p, store.get("name", sid), old_price, ts))
            rec.setdefault("last_alert", {})[etype] = ts

        current_keys = set()
        for p in products:
            current_keys.add(p.key)
            rec = prods.get(p.key)
            if rec is None:
                rec = prods[p.key] = {"first_seen": ts, "store_id": sid}
                if not seeding and p.available:
                    emit(PREORDER if p.preorder else NEW_LISTING, p, rec)
            else:
                was_available = rec.get("available", False)
                old_price = rec.get("price")
                if p.available and not was_available:
                    emit(PREORDER if p.preorder else RESTOCK, p, rec)
                elif (
                    p.available
                    and was_available
                    and p.price is not None
                    and old_price
                    and p.price < old_price
                    and (old_price - p.price) / old_price * 100 >= price_drop_pct
                ):
                    emit(PRICE_DROP, p, rec, old_price=old_price)
            rec.update(
                title=p.title,
                url=p.url,
                price=p.price,
                available=p.available,
                preorder=p.preorder,
                last_seen=ts,
            )

        # Products that vanished from a full feed are treated as sold out, so we
        # alert again when they come back. Skipped for partial sources.
        if missing_means_sold_out and products:
            for key, rec in prods.items():
                if rec.get("store_id") == sid and key not in current_keys and rec.get("available"):
                    rec["available"] = False

        # Stay unseeded until a scan actually finds products, so a shop that was
        # briefly unreadable doesn't flood the channel with "new" alerts later.
        # alert_from_start: for shops that stock no Pokémon cards yet, so the first
        # ones they list are alerted rather than recorded silently.
        seeded = bool(products) or not seeding or bool(store.get("alert_from_start"))
        store_state.update(seeded=seeded, last_ok=ts, product_count=len(products))
        if seeding:
            log.info("%s: first scan, recorded %d products silently", sid, len(products))
        return events
