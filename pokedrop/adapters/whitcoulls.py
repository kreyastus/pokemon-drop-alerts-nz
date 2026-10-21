"""Whitcoulls category pages carry their product data as JSON in the page:
`window.category = { ...{"items": [...], "pagination": {...}} }`. Reading that
is quicker and steadier than the product tiles, which are drawn by JavaScript.

Statuses seen: "" or "limitedstock" (buy online), "instore" (in store only),
"outofstock". In-store-only stock still counts as available, because most of
Whitcoulls' trading cards are only sold in store.
"""
from __future__ import annotations

import json
import logging
from urllib.parse import urljoin

from ..filters import looks_like_preorder
from ..http import PoliteClient
from ..models import Product

log = logging.getLogger(__name__)

UNAVAILABLE = {"outofstock", "soldout", "unavailable", "discontinued", "notavailable"}


def extract(html: str) -> dict | None:
    """Pulls the JSON object out of `window.category = { ...{...} }`."""
    start = html.find("window.category = {")
    if start < 0:
        return None
    s = html.find("...{", start)
    if s < 0:
        return None
    s += 3
    depth, in_str, esc = 0, False, False
    for i in range(s, len(html)):
        c = html[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[s : i + 1])
                except ValueError:
                    return None
    return None


def _float(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def parse(store: dict, data: dict) -> list[Product]:
    base = store["url"].rstrip("/")
    out: list[Product] = []
    for it in data.get("items") or []:
        sc = it.get("stylecolour") or {}
        variants = sc.get("variants") or [{}]
        v = variants[0]
        style = sc.get("stylecolourid") or it.get("style")
        title = (it.get("description") or "").strip()
        if not style or not title or not sc.get("urlkey"):
            continue
        status = (v.get("status") or "").lower()
        price = _float(v.get("unitprice"))
        was = _float(v.get("baseunitprice"))
        attrs = it.get("attributes") or {}
        tags = [t for t in (attrs.get("filterrange"), (v.get("gadata") or {}).get("category")) if t]
        if status == "instore":
            tags.append("In store only")
        out.append(
            Product(
                store_id=store["id"],
                product_id=str(style),
                title=title,
                url=f"{base}/{sc['urlkey']}",
                price=price,
                available=status not in UNAVAILABLE,
                preorder=bool(v.get("preordereta")) or "preorder" in status or looks_like_preorder(title),
                image=f"{base}/content/products/{style}_MAIN.jpg",
                compare_at_price=was if was and price and was > price else None,
                tags=tags,
            )
        )
    return out


def fetch(store: dict, client: PoliteClient) -> list[Product]:
    products: list[Product] = []
    max_pages = int(store.get("max_pages", 5))
    for path in store.get("pages", []):
        for page in range(1, max_pages + 1):
            url = urljoin(store["url"], path) + (f"?p={page}" if page > 1 else "")
            data = extract(client.get_text(url))
            if data is None:
                raise RuntimeError(f"no product data found on {url} (page layout may have changed)")
            found = parse(store, data)
            products.extend(found)
            pg = data.get("pagination") or {}
            per, total = int(pg.get("itemsPerPage") or 24), int(pg.get("totalItems") or 0)
            if not found or page * per >= total:
                break
    log.info("%s: %d products read from page data", store["id"], len(products))
    return products
