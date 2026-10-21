"""Decides whether a product is a Pokémon TCG item worth alerting on, and
whether it looks like a pre-order."""
from __future__ import annotations

import re
import unicodedata

from .models import Product


def _fold(text: str) -> str:
    """Lower-case and strip accents so 'Pokémon' matches 'pokemon'."""
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


DEFAULT_INCLUDE = ["pokemon"]

# Things that mention Pokémon but are not cards. Override in stores.yaml.
DEFAULT_EXCLUDE = [
    "plush", "figure", "figurine", "t-shirt", "tee", "hoodie", "lego",
    "nintendo switch", "video game", "lunch box", "backpack", "costume",
    "puzzle", "colouring", "coloring", "sticker book", "book", "cushion",
    "mega construx", "funko",
]

PREORDER_PATTERNS = [
    r"\bpre[\s\-]?order",
    r"\bpre[\s\-]?sale\b",
    r"\bpreorder",
    r"\bcoming soon\b",
]
_PREORDER_RE = re.compile("|".join(PREORDER_PATTERNS), re.I)


def looks_like_preorder(*texts: str) -> bool:
    return any(_PREORDER_RE.search(t or "") for t in texts)


class ProductFilter:
    def __init__(
        self,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
    ):
        self.include = [_fold(k) for k in (include or DEFAULT_INCLUDE)]
        self.exclude = [_fold(k) for k in (exclude if exclude is not None else DEFAULT_EXCLUDE)]
        self.min_price = min_price
        self.max_price = max_price

    def matches(self, p: Product, assume_pokemon: bool = False) -> bool:
        haystack = _fold(" ".join([p.title, *p.tags]))
        if not assume_pokemon and not any(k in haystack for k in self.include):
            return False
        title = _fold(p.title)
        if any(re.search(rf"\b{re.escape(k)}\b", title) for k in self.exclude):
            return False
        if p.price is not None:
            if self.min_price is not None and p.price < self.min_price:
                return False
            if self.max_price is not None and p.price > self.max_price:
                return False
        return True
