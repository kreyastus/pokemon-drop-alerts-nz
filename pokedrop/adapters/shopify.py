"""Shopify stores publish /products.json (and /collections/<handle>/products.json).
It includes price, compare-at price, availability and tags for every variant,
so it is the most reliable source we have."""
from __future__ import annotations

import logging

from ..filters import looks_like_preorder
from ..http import PoliteClient
from ..models import Product

log = logging.getLogger(__name__)

PAGE_SIZE = 250


def _to_float(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def parse_products(store: dict, payload: dict) -> list[Product]:
    base = store["url"].rstrip("/")
    out: list[Product] = []
    for p in payload.get("products", []):
        tags = p.get("tags") or []
        if isinstance(tags, str):  # older stores return a comma-separated string
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        variants = p.get("variants") or []
        if not variants:
            continue
        available = [v for v in variants if v.get("available")]
        chosen = min(available or variants, key=lambda v: _to_float(v.get("price")) or 0)
        images = p.get("images") or []
        preorder = looks_like_preorder(p.get("title", ""), " ".join(tags), p.get("product_type", ""))
        out.append(
            Product(
                store_id=store["id"],
                product_id=str(p["id"]),
                title=p.get("title", "").strip(),
                url=f"{base}/products/{p.get('handle')}",
                price=_to_float(chosen.get("price")),
                compare_at_price=_to_float(chosen.get("compare_at_price")),
                available=bool(available),
                preorder=preorder,
                image=images[0].get("src") if images else None,
                tags=list(tags),
            )
        )
    return out


def fetch(store: dict, client: PoliteClient) -> list[Product]:
    base = store["url"].rstrip("/")
    collections = store.get("collections") or [None]
    max_pages = int(store.get("max_pages", 10))
    seen: dict[str, Product] = {}
    for handle in collections:
        path = f"/collections/{handle}/products.json" if handle else "/products.json"
        for page in range(1, max_pages + 1):
            url = f"{base}{path}?limit={PAGE_SIZE}&page={page}"
            payload = client.get_json(url)
            batch = parse_products(store, payload)
            for prod in batch:
                seen[prod.key] = prod
            if len(payload.get("products", [])) < PAGE_SIZE:
                break
    log.info("%s: %d products from Shopify feed", store["id"], len(seen))
    return list(seen.values())
