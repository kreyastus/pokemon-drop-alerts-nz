"""Adapters turn a retailer's website into a list of Product objects.

Each adapter module has: fetch(store: dict, client: PoliteClient) -> list[Product]
and may have branch_stock(...) to fill in stock at physical shops.
"""
from . import html, kmart, shopify, squarespace, whitcoulls, woocommerce

ADAPTERS = {
    "shopify": shopify.fetch,
    "woocommerce": woocommerce.fetch,
    "squarespace": squarespace.fetch,
    "html": html.fetch,
    "whitcoulls": whitcoulls.fetch,
    "kmart": kmart.fetch,
}

# Optional second step for chains that publish stock for each shop.
BRANCH_LOOKUPS = {
    "whitcoulls": whitcoulls.branch_stock,
}
