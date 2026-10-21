"""General-purpose adapter for custom-built shops (big-box retailers etc.).

Strategy, in order:
1. Read schema.org JSON-LD (Product / ItemList / Offer) that most shops embed
   for Google Shopping. This gives price and availability without guesswork.
2. Fall back to CSS selectors you provide in stores.yaml.

Set `render: true` for shops that build their product grid with JavaScript.
That uses Playwright (headless Chromium), which is slower but sees what a
shopper sees. Install with:  pip install playwright && playwright install chromium
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..filters import looks_like_preorder
from ..http import PoliteClient
from ..models import Product

log = logging.getLogger(__name__)

IN_STOCK = ("instock", "limitedavailability", "onlineonly", "instoreonly")
PREORDER = ("preorder", "presale", "backorder")


# ---------------------------------------------------------------- utilities
def _num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"\d[\d,]*(?:\.\d+)?", str(v))
    return float(m.group(0).replace(",", "")) if m else None


def _stable_id(url: str) -> str:
    return hashlib.sha1(url.split("?")[0].rstrip("/").encode()).hexdigest()[:16]


def _first(v):
    return v[0] if isinstance(v, list) and v else v


def _walk(node):
    """Yield every dict inside a JSON-LD blob, including @graph members."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _types(d: dict) -> set[str]:
    t = d.get("@type", [])
    return {x.lower() for x in (t if isinstance(t, list) else [t]) if isinstance(x, str)}


# ---------------------------------------------------------------- JSON-LD
def _product_from_ld(store: dict, d: dict, page_url: str, fallback_url: str = "") -> Product | None:
    name = (d.get("name") or "").strip()
    offers = d.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    url = d.get("url") or d.get("@id") or offers.get("url") or fallback_url
    if not name or not url:
        return None
    url = urljoin(page_url, url)
    if "aggregateoffer" in _types(offers) and isinstance(offers.get("offers"), list):
        offers = offers["offers"][0] if offers["offers"] else offers
    availability = str(offers.get("availability", "")).rsplit("/", 1)[-1].lower()
    price = _num(offers.get("price") or offers.get("lowPrice"))
    preorder = availability in PREORDER or looks_like_preorder(name)
    image = _first(d.get("image"))
    if isinstance(image, dict):
        image = image.get("url")
    return Product(
        store_id=store["id"],
        product_id=str(d.get("sku") or d.get("productID") or _stable_id(url)),
        title=name,
        url=url,
        price=price,
        available=availability in IN_STOCK or availability in PREORDER,
        preorder=preorder,
        image=image,
    )


def parse_jsonld(store: dict, html: str, page_url: str, single_product: bool = False) -> list[Product]:
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, Product] = {}
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            blob = json.loads(tag.string or tag.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for d in _walk(blob):
            if "product" in _types(d):
                p = _product_from_ld(store, d, page_url, page_url if single_product else "")
                if p:
                    out[p.key] = p
    return list(out.values())


# ---------------------------------------------------------------- selectors
def parse_selectors(store: dict, html: str, page_url: str) -> list[Product]:
    sel = store.get("selectors") or {}
    if not sel.get("item"):
        return []
    soup = BeautifulSoup(html, "html.parser")
    sold_out_words = [w.lower() for w in sel.get("sold_out_text", ["sold out", "out of stock", "unavailable"])]
    out: dict[str, Product] = {}
    for card in soup.select(sel["item"]):
        link_el = card.select_one(sel.get("link", "a[href]"))
        title_el = card.select_one(sel["title"]) if sel.get("title") else link_el
        if not link_el or not title_el:
            continue
        href = urljoin(page_url, link_el.get("href", ""))
        title = title_el.get_text(" ", strip=True)
        price_el = card.select_one(sel["price"]) if sel.get("price") else None
        img_el = card.select_one(sel.get("image", "img"))
        text = card.get_text(" ", strip=True).lower()
        if sel.get("in_stock"):
            available = card.select_one(sel["in_stock"]) is not None
        elif sel.get("available_text"):
            # e.g. JB Hi-Fi: buyable only if the card's button says "Add to cart" or "Pre-order"
            btn = card.select_one(sel["buy_button"]) if sel.get("buy_button") else None
            btn_text = btn.get_text(" ", strip=True).lower() if btn else ("" if sel.get("buy_button") else text)
            available = any(w.lower() in btn_text for w in sel["available_text"])
        else:
            available = not any(w in text for w in sold_out_words)
        image = (img_el.get("src") or img_el.get("data-src")) if img_el else None
        p = Product(
            store_id=store["id"],
            product_id=_stable_id(href),
            title=title,
            url=href,
            price=_num(price_el.get_text(" ", strip=True)) if price_el else None,
            available=available,
            preorder=looks_like_preorder(title, text),
            image=_clean_image(urljoin(page_url, image)) if image else None,
        )
        out[p.key] = p
    return list(out.values())


def _clean_image(url: str) -> str:
    """Shopify thumbnails often load as a blurry 32x32 placeholder; ask for a usable size."""
    if "cdn.shopify.com" in url:
        url = re.sub(r"_\d+x\d+(?=\.(?:jpe?g|png|webp)\b)", "_300x300", url)
    return url


# ---------------------------------------------------------------- detail pages
def check_details(store: dict, client: PoliteClient, products: list[Product]) -> list[Product]:
    """For shops whose listing tiles don't show stock (e.g. Farmers), open each
    matching product page and read its schema.org availability and price.
    Items whose page can't be read are left out of this scan, so a hiccup
    never looks like a restock."""
    pattern = re.compile(store.get("detail_match", r"pok[eé]mon"), re.I)
    checked = []
    wanted = [p for p in products if pattern.search(p.title)]
    failures: list[str] = []
    for p in wanted:
        try:
            page = client.get_text(p.url)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{type(exc).__name__}: {exc}")
            continue
        found = parse_jsonld(store, page, p.url, single_product=True)
        if not found:
            failures.append(f"no product data on page ({_describe(page)})")
            continue
        d = found[0]
        p.available = d.available
        p.preorder = p.preorder or d.preorder
        if d.price is not None:
            p.price = d.price
        checked.append(p)
    if failures:
        log.warning("%s: %d of %d product pages unreadable, e.g. %s",
                    store["id"], len(failures), len(wanted), failures[0][:200])
    return checked


def _describe(html: str) -> str:
    """Short summary of a page, to spot bot-check or error pages in the logs."""
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.I | re.S)
    title = re.sub(r"\s+", " ", m.group(1)).strip()[:80] if m else "no title"
    return f"{len(html or '')} bytes, title '{title}'"


# ---------------------------------------------------------------- fetching
class _Renderer:
    """One headless Chromium shared by every page of a store, so opening a
    listing plus a dozen product pages stays quick."""

    def __init__(self, user_agent: str):
        self.user_agent = user_agent

    def __enter__(self):
        from playwright.sync_api import sync_playwright  # optional dependency

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        self._page = self._browser.new_page(user_agent=self.user_agent, locale="en-NZ")
        return self

    def __exit__(self, *exc):
        self._browser.close()
        self._pw.stop()

    def get(self, url: str, wait_selector: str | None = None, scroll: bool = True) -> str:
        page = self._page
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        if wait_selector:
            page.wait_for_selector(wait_selector, state="attached", timeout=20000)
        else:
            page.wait_for_load_state("networkidle", timeout=20000)
        if scroll:
            # Scroll down in steps so lazily loaded product cards appear.
            for _ in range(6):
                page.mouse.wheel(0, 2500)
                page.wait_for_timeout(600)
            page.wait_for_timeout(1500)
        return page.content()


class _RenderedClient:
    """Looks like PoliteClient.get_text, but loads pages in the headless browser."""

    def __init__(self, renderer: _Renderer, client: PoliteClient):
        self.renderer = renderer
        self.client = client

    def get_text(self, url: str) -> str:
        if not self.client.allowed(url):
            raise RuntimeError(f"robots.txt disallows {url}")
        return self.renderer.get(url, 'script[type="application/ld+json"]', scroll=False)


def fetch(store: dict, client: PoliteClient) -> list[Product]:
    if store.get("render"):
        with _Renderer(client.user_agent) as renderer:
            return _fetch(store, client, renderer)
    return _fetch(store, client, None)


def _fetch(store: dict, client: PoliteClient, renderer: _Renderer | None) -> list[Product]:
    base = store["url"].rstrip("/")
    seen: dict[str, Product] = {}
    for path in store.get("pages", []):
        url = path if path.startswith("http") else f"{base}/{path.lstrip('/')}"
        if renderer:
            if not client.allowed(url):
                log.warning("%s: robots.txt disallows %s, skipping", store["id"], url)
                continue
            html = renderer.get(url, (store.get("selectors") or {}).get("item"))
        else:
            html = client.get_text(url)
        found = parse_jsonld(store, html, url)
        if not found or store.get("prefer_selectors"):
            found = parse_selectors(store, html, url) or found
        if not found:
            # A listing page with nothing on it is almost always a block or error
            # page, so it counts as a failed check rather than an empty shop.
            raise RuntimeError(f"no products found on {url} ({_describe(html)})")
        for p in found:
            seen[p.key] = p
    products = list(seen.values())
    if store.get("detail_pages"):
        detail_client = _RenderedClient(renderer, client) if renderer else client
        products = check_details(store, detail_client, products)
    log.info("%s: %d products parsed from HTML", store["id"], len(products))
    return products
