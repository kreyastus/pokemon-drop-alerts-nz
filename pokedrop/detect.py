"""`pokedrop detect <url>`: works out which adapter suits a shop and prints a
ready-to-paste stores.yaml entry."""
from __future__ import annotations

from urllib.parse import urlparse

from .adapters import html as html_adapter
from .http import PoliteClient, RobotsDisallowed


def detect(url: str, client: PoliteClient) -> str:
    p = urlparse(url if "://" in url else f"https://{url}")
    base = f"{p.scheme}://{p.netloc}"
    path = p.path if p.path not in ("", "/") else ""
    if p.query:
        path = f"{path or '/'}?{p.query}"
    sid = p.netloc.replace("www.", "").split(".")[0]
    lines = [f"Checking {base} ..."]
    stub = {"id": sid, "url": base}

    def attempt(label, fn):
        try:
            return fn()
        except RobotsDisallowed:
            lines.append(f"  {label}: blocked by robots.txt (skip it)")
        except Exception as exc:  # noqa: BLE001 - report and keep going
            lines.append(f"  {label}: no ({type(exc).__name__})")
        return None

    # Shopify
    data = attempt("Shopify", lambda: client.get_json(f"{base}/products.json?limit=1"))
    if isinstance(data, dict) and "products" in data:
        lines.append("  Shopify: YES. Best option.")
        lines.append("  Tip: add a 'collections' list (the part after /collections/ in a")
        lines.append("  Pokémon category URL) so you are not downloading the whole shop.")
        return "\n".join(lines) + _yaml(sid, base, "shopify", "    collections: [pokemon]  # check this handle")
    # WooCommerce
    data = attempt("WooCommerce", lambda: client.get_json(f"{base}/wp-json/wc/store/v1/products?per_page=1"))
    if isinstance(data, list):
        lines.append("  WooCommerce Store API: YES.")
        return "\n".join(lines) + _yaml(sid, base, "woocommerce", "    search: pokemon")
    # Squarespace
    if path:
        data = attempt("Squarespace", lambda: client.get_json(f"{base}{path}{'&' if '?' in path else '?'}format=json"))
        if isinstance(data, dict) and "items" in data:
            lines.append("  Squarespace JSON: YES.")
            return "\n".join(lines) + _yaml(sid, base, "squarespace", f"    pages: [{path}]")
    else:
        lines.append("  Squarespace: pass a shop/category URL to test this")
    # JSON-LD on the given page
    target = f"{base}{path}" if path else base
    page = attempt("Page fetch", lambda: client.get_text(target))
    if page:
        found = html_adapter.parse_jsonld(stub, page, target)
        if found:
            lines.append(f"  Structured data (JSON-LD): YES, {len(found)} products on this page.")
            return "\n".join(lines) + _yaml(sid, base, "html", f"    pages: [{path or '/'}]")
        lines.append("  Structured data: none found in the raw HTML.")
        lines.append("  Next step: try `render: true` (JavaScript sites) and/or CSS selectors.")
        return "\n".join(lines) + _yaml(
            sid, base, "html",
            f"    pages: [{path or '/'}]\n    render: true\n    selectors:\n"
            "      item: .product-card      # inspect the page to find these\n"
            "      title: .product-title\n      price: .price\n      link: a[href]",
        )
    return "\n".join(lines) + "\n\nCould not reach the site. It may block automated requests."


def _yaml(sid, base, adapter, extra):
    return (
        "\n\nSuggested stores.yaml entry:\n\n"
        f"  - id: {sid}\n    name: {sid.title()}\n    url: {base}\n    adapter: {adapter}\n{extra}\n"
    )
