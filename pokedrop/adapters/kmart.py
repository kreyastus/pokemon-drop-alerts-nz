"""Kmart NZ. The Pokémon cards page lists its products (schema.org ItemList in the
page data) and each product page carries the product's details, including
`nationalInventory`, which is true while it can be bought online.

Kmart's pages are large (about 1.5 MB each), so each product page is read at
most every `detail_hours` (default 6) and at most `max_details` (default 12)
pages are read per scan. New products are read first. The category page itself
is read every scan, so new listings are spotted straight away.

Kmart turns away cloud and hosting servers, so this only works from a home
connection (the Docker set-up in docker/).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

from ..filters import looks_like_preorder
from ..http import PoliteClient
from ..models import Product

log = logging.getLogger(__name__)

_NEXT = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_PRODUCT_URL = re.compile(r'https://www\.kmart\.co\.nz/product/[^"\\\s<>]+?-(\d{6,})/')


def next_data(html: str) -> dict | None:
    m = _NEXT.search(html or "")
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None


def category_urls(html: str) -> list[str]:
    """Product URLs on a category page, in page order."""
    nd = next_data(html) or {}
    items = (((nd.get("props") or {}).get("pageProps") or {}).get("itemListSchema") or {}).get("itemListElement") or []
    urls = [i.get("url") for i in items if isinstance(i, dict) and i.get("url")]
    if not urls:
        urls = [m.group(0) for m in _PRODUCT_URL.finditer(html or "")]
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def product_record(html: str) -> dict | None:
    """The few fields we keep from a product page."""
    nd = next_data(html) or {}
    try:
        item = nd["props"]["pageProps"]["productDetail"]["products"][0]["item"]
    except (KeyError, IndexError, TypeError):
        return None
    d = item.get("data") or {}
    title = (item.get("value") or "").strip()
    if not title:
        return None
    return {
        "title": title,
        "price": _num(d.get("price")),
        "image": d.get("image_url"),
        "online": bool(d.get("nationalInventory")),
        "sku": str(d.get("variation_id") or d.get("id") or ""),
    }


def _product(store: dict, url: str, rec: dict) -> Product:
    m = _PRODUCT_URL.search(url)
    pid = rec.get("sku") or (m.group(1) if m else url)
    return Product(
        store_id=store["id"],
        product_id=str(pid),
        title=rec["title"],
        url=url,
        price=rec.get("price"),
        available=bool(rec.get("online")),
        preorder=looks_like_preorder(rec["title"]),
        image=rec.get("image"),
        tags=[] if rec.get("online") else ["Not sold online right now"],
    )


def fetch(store: dict, client: PoliteClient) -> list[Product]:
    cache: dict = store.get("_cache") if isinstance(store.get("_cache"), dict) else {}
    hours = float(store.get("detail_hours", 6))
    budget = int(store.get("max_details", 12))
    now = datetime.now(timezone.utc)

    urls: list[str] = []
    for path in store.get("pages", []):
        page = urljoin(store["url"], path)
        found = category_urls(client.get_text(page))
        if not found:
            raise RuntimeError(f"no products found on {page} (page layout may have changed)")
        urls.extend(u for u in found if u not in urls)

    def age(u):
        try:
            return now - datetime.fromisoformat(cache[u]["checked"])
        except (KeyError, TypeError, ValueError):
            return timedelta.max

    # New products first, then the longest-unchecked.
    due = sorted((u for u in urls if age(u) >= timedelta(hours=hours)), key=lambda u: (u in cache, -age(u).total_seconds()))
    read = 0
    for u in due[:budget]:
        try:
            rec = product_record(client.get_text(u))
        except Exception as exc:  # noqa: BLE001 - try again next scan
            log.debug("%s: product page %s failed (%s)", store["id"], u, exc)
            continue
        read += 1
        if rec:
            cache[u] = {**rec, "checked": now.replace(microsecond=0).isoformat()}
    for u in list(cache):
        if u not in urls:
            del cache[u]   # no longer listed

    products = [_product(store, u, cache[u]) for u in urls if u in cache and cache[u].get("title")]
    log.info("%s: %d products listed, %d known, %d product pages read", store["id"], len(urls), len(products), read)
    return products
