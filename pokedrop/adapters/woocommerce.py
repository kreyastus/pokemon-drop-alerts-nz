"""WooCommerce stores (WordPress) expose a public, read-only Store API at
/wp-json/wc/store/v1/products. No keys needed."""
from __future__ import annotations

import html as htmllib
import logging

from ..filters import looks_like_preorder
from ..http import PoliteClient
from ..models import Product

log = logging.getLogger(__name__)


def _price(prices: dict, key: str):
    raw = prices.get(key)
    if raw in (None, ""):
        return None
    minor = int(prices.get("currency_minor_unit", 2))
    try:
        return int(raw) / (10 ** minor)
    except (TypeError, ValueError):
        return None


def parse_products(store: dict, items: list) -> list[Product]:
    out = []
    for it in items:
        prices = it.get("prices") or {}
        price = _price(prices, "price")
        regular = _price(prices, "regular_price")
        tags = [t.get("name", "") for t in it.get("tags", [])] + [
            c.get("name", "") for c in it.get("categories", [])
        ]
        title = htmllib.unescape(it.get("name", "")).strip()
        stock_text = (it.get("stock_availability") or {}).get("text", "")
        out.append(
            Product(
                store_id=store["id"],
                product_id=str(it["id"]),
                title=title,
                url=it.get("permalink", ""),
                price=price,
                compare_at_price=regular if regular and price and regular > price else None,
                available=bool(it.get("is_in_stock")) and bool(it.get("is_purchasable", True)),
                preorder=looks_like_preorder(title, " ".join(tags), stock_text)
                or bool(it.get("is_on_backorder")),
                image=(it.get("images") or [{}])[0].get("src"),
                tags=tags,
            )
        )
    return out


def fetch(store: dict, client: PoliteClient) -> list[Product]:
    base = store["url"].rstrip("/")
    search = store.get("search", "pokemon")
    category = store.get("category")  # optional category slug or ID
    max_pages = int(store.get("max_pages", 5))
    seen: dict[str, Product] = {}
    for page in range(1, max_pages + 1):
        params = {"per_page": 100, "page": page, "orderby": "date", "order": "desc"}
        if category:
            params["category"] = category
        elif search:
            params["search"] = search
        r = client.get(f"{base}/wp-json/wc/store/v1/products", params=params)
        r.raise_for_status()
        items = r.json()
        for p in parse_products(store, items):
            seen[p.key] = p
        if len(items) < 100:
            break
    log.info("%s: %d products from WooCommerce Store API", store["id"], len(seen))
    return list(seen.values())
