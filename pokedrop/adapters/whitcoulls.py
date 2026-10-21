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


# ------------------------------------------------------------ branch stock
# The "Check store stock" button on each product page posts the product's style
# number and a region to this address. Whitcoulls updates the figures once a
# day (about 8 am), so each product is looked up at most once an hour.
STOCK_API = "/api/product/checkstorestock"


def _branch(row: dict, region: str) -> dict | None:
    name = (row.get("SITE_NAME") or row.get("name") or "").strip()
    if not name:
        return None
    units = _float(row.get("UNRESTRICTED")) or 0.0
    on_order = _float(row.get("ON_ORDER")) or 0.0
    return {
        "id": str(row.get("SITE") or row.get("storeid") or name),
        "name": name,
        "region": region,
        "units": int(units),
        "in_stock": units > 0,
        "message": (row.get("SOH_MESSAGE") or "").strip() or None,
        "on_order": int(on_order) if on_order else None,
        "basis": "branch",
    }


def branch_stock(store: dict, products: list[Product], client: PoliteClient, cache: dict, now) -> int:
    """Fills p.branches for each product with stock at every branch in the
    regions listed under `branch_zones` (e.g. {ZONE11: Canterbury}).
    Returns how many lookups were made this run."""
    from datetime import datetime, timedelta

    zones = store.get("branch_zones") or {}
    if not zones:
        return 0
    minutes = int(store.get("branch_minutes", 60))
    budget = int(store.get("max_branch_lookups", 80))
    url = store["url"].rstrip("/") + STOCK_API
    headers = {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json",
               "Referer": store["url"].rstrip("/") + "/"}
    made = 0
    for p in products:
        branches: list[dict] = []
        known = False
        for zone, region in zones.items():
            ck = f"{p.key}|{zone}"
            rec = cache.get(ck)
            fresh = False
            if rec:
                try:
                    fresh = now - datetime.fromisoformat(rec["checked"]) < timedelta(minutes=minutes - 2)
                except (KeyError, ValueError):
                    fresh = False
            if not fresh and made < budget:
                made += 1
                try:
                    r = client.post_form(url, {"barcode": p.product_id, "zone": zone}, headers)
                    r.raise_for_status()
                    body = r.json()
                    rows = body.get("data") if isinstance(body, dict) and body.get("status") else []
                    rec = {"checked": now.replace(microsecond=0).isoformat(),
                           "branches": [b for b in (_branch(x, region) for x in rows or []) if b]}
                    cache[ck] = rec
                except Exception as exc:  # noqa: BLE001 - keep the last answer we had
                    log.debug("%s: branch stock for %s in %s failed (%s)", store["id"], p.title, region, exc)
            if rec and "branches" in rec:
                known = True
                branches.extend(rec["branches"])
        if known:
            p.branches = branches
    # forget lookups older than two days (products that have gone)
    cutoff = now - timedelta(days=2)
    for ck in [k for k, v in cache.items() if k.startswith(store["id"] + ":")]:
        try:
            if datetime.fromisoformat(cache[ck]["checked"]) < cutoff:
                del cache[ck]
        except (KeyError, ValueError):
            del cache[ck]
    if made:
        log.info("%s: checked branch stock %d times", store["id"], made)
    return made
