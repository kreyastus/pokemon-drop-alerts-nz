"""Shared data shapes used across adapters, state tracking and notifiers."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Product:
    """One sellable item as seen at a single retailer during a single scan."""

    store_id: str
    product_id: str            # stable ID from the retailer (Shopify ID, SKU, URL)
    title: str
    url: str
    price: Optional[float]     # NZ$, None if unknown
    available: bool
    preorder: bool = False
    image: Optional[str] = None
    compare_at_price: Optional[float] = None
    tags: list[str] = field(default_factory=list)
    limit: Optional[int] = None       # purchase limit per customer, if the retailer states one
    rrp: Optional[float] = None       # recommended retail price, from rrp.yaml

    @property
    def key(self) -> str:
        return f"{self.store_id}:{self.product_id}"

    def to_dict(self) -> dict:
        return asdict(self)


# Event types, in rough order of how exciting they are.
PREORDER = "preorder"        # a pre-order has opened (new listing or back in stock)
NEW_LISTING = "new"          # brand-new product, available to buy now
RESTOCK = "restock"          # was sold out, now available
PRICE_DROP = "price_drop"    # still available, price fell past the threshold

EVENT_LABELS = {
    PREORDER: "Pre-order open",
    NEW_LISTING: "New listing",
    RESTOCK: "Back in stock",
    PRICE_DROP: "Price drop",
}


@dataclass
class Event:
    type: str
    product: Product
    store_name: str
    old_price: Optional[float] = None
    detected_at: str = ""      # ISO 8601 UTC

    def to_dict(self) -> dict:
        d = self.product.to_dict()
        d.update(
            event_type=self.type,
            event_label=EVENT_LABELS.get(self.type, self.type),
            store_name=self.store_name,
            old_price=self.old_price,
            detected_at=self.detected_at,
            product_key=self.product.key,
        )
        return d
