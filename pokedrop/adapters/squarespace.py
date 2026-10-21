"""Squarespace Commerce pages return JSON when ?format=json is appended to a
collection (shop page) URL. Handles both the older (cents) and newer
(priceMoney) variant formats."""
from __future__ import annotations

import logging
from urllib.parse import urljoin

from ..filters import looks_like_preorder
from ..http import PoliteClient
from ..models import Product

log = logging.getLogger(__name__)


def _variant_price(v: dict, sale: bool):
    money = v.get("salePriceMoney" if sale else "priceMoney")
    if isinstance(money, dict) and money.get("value") not in (None, ""):
        return float(money["value"])
    cents = v.get("salePrice" if sale else "price")
    if isinstance(cents, (int, float)) and cents > 0:
        return cents / 100
    return None


def _variant_in_stock(v: dict) -> bool:
    stock = v.get("stock")
    if isinstance(stock, dict):
        return bool(stock.get("unlimited")) or (stock.get("quantity") or 0) > 0
    return bool(v.get("unlimited")) or (v.get("qtyInStock") or 0) > 0


def parse_items(store: dict, payload: dict) -> list[Product]:
    base = store["url"].rstrip("/") + "/"
    out = []
    for it in payload.get("items", []):
        sc = it.get("structuredContent") or {}
        variants = sc.get("variants") or it.get("variants") or []
        if not variants:
            continue
        in_stock = [v for v in variants if _variant_in_stock(v)]
        v = (in_stock or variants)[0]
        on_sale = bool(v.get("onSale"))
        price = _variant_price(v, sale=on_sale) or _variant_price(v, sale=False)
        regular = _variant_price(v, sale=False) if on_sale else None
        tags = list(it.get("tags") or []) + list(it.get("categories") or [])
        title = (it.get("title") or "").strip()
        out.append(
            Product(
                store_id=store["id"],
                product_id=str(it.get("id")),
                title=title,
                url=urljoin(base, it.get("fullUrl", "")),
                price=price,
                compare_at_price=regular,
                available=bool(in_stock),
                preorder=looks_like_preorder(title, " ".join(tags), it.get("excerpt", "") or ""),
                image=it.get("assetUrl"),
                tags=tags,
            )
        )
    return out


def fetch(store: dict, client: PoliteClient) -> list[Product]:
    base = store["url"].rstrip("/")
    seen: dict[str, Product] = {}
    for path in store.get("pages", ["/shop"]):
        url = f"{base}/{path.lstrip('/')}"
        params = {"format": "json"}
        for _ in range(int(store.get("max_pages", 10))):
            payload = client.get_json(url, params=params)
            for p in parse_items(store, payload):
                seen[p.key] = p
            pag = payload.get("pagination") or {}
            if not pag.get("nextPage"):
                break
            params = {"format": "json", "offset": pag.get("nextPageOffset")}
    log.info("%s: %d products from Squarespace", store["id"], len(seen))
    return list(seen.values())
