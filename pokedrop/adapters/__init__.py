"""Adapters turn a retailer's website into a list of Product objects.

Each adapter module has: fetch(store: dict, client: PoliteClient) -> list[Product]
"""
from . import html, shopify, squarespace, whitcoulls, woocommerce

ADAPTERS = {
    "shopify": shopify.fetch,
    "woocommerce": woocommerce.fetch,
    "squarespace": squarespace.fetch,
    "html": html.fetch,
    "whitcoulls": whitcoulls.fetch,
}
