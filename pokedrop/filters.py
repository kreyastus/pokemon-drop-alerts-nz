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
    "mega construx", "funko", "watch", "clock", "lamp", "mug", "drink bottle",
    "keyring", "key chain", "pyjamas", "socks", "slippers", "wallet", "pencil case",
    # toys and games
    "toy", "toys", "figures", "plushie", "plushies", "squishmallow", "squishmallows",
    "clip n go", "clip 'n' go", "poke ball", "pokeball", "nanoblock", "model kit",
    "battle figure", "surprise attack", "guess who", "monopoly", "board game",
    "jigsaw", "bag charm", "keychain", "night light", "torch", "bubble",
    "water bottle", "action figure", "blaster", "kendama", "yo-yo", "plush toy",
    "key ring", "key rings", "keyrings", "key chains", "keychains",
]

# Always removed, even when the title also has card words: graded cards
# ("Charizard ex Special Illustration Rare - PSA 10") are one-off collectables,
# not stock drops.
DEFAULT_DROP = ["psa", "cgc", "bgs", "beckett", "graded", "slab", "slabbed"]

# Words that mean "this is a card product", which beat the exclude list:
# "30th Celebration Figure Collection" is a TCG box, not a figure.
TCG_WORDS = [
    "tcg", "trading card", "booster", "elite trainer", "etb", "premium collection",
    "figure collection", "special collection", "battle deck", "league battle", "tin",
    "blister", "card game",
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


# Signs that a product isn't an English-language print. Used for the optional
# English-only Discord channel; anything not marked otherwise counts as English.
NON_ENGLISH_WORDS = [
    "japanese", "japan", "jp", "jpn", "chinese", "simplified chinese", "traditional chinese",
    "s-chinese", "t-chinese", "chn", "cn", "korean", "korea", "kr", "kor", "thai",
    "indonesian", "indonesia", "german", "deutsch", "french", "francais", "italian",
    "italiano", "spanish", "espanol", "portuguese", "gem pack", "gem vol", "high class pack",
]
# Japanese-only set codes: s4a, s8a, sv2a, sv8a, m2a, sm12a.
_JP_SET_CODES = r"s\d{1,2}a|sv\d{1,2}a|sm\d{1,2}a|m\d{1,2}a"
_NON_ENGLISH_RE = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in NON_ENGLISH_WORDS) + "|" + _JP_SET_CODES + r")\b")
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\u0e00-\u0e7f]")


def looks_english(p: Product) -> bool:
    """False when the title or tags say the product is Japanese, Chinese, Korean
    and so on ("Pokemon Japanese Mega Dream ex Booster Box", "[CN] Gem Pack")."""
    text = " ".join([p.title or "", *(p.tags or [])])
    return not (_CJK_RE.search(text) or _NON_ENGLISH_RE.search(_fold(text)))


class ProductFilter:
    def __init__(
        self,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        drop: list[str] | None = None,
    ):
        # `drop` words always remove a product, even a card product
        # (event tickets: "Pokémon TCG Prerelease Ticket"). DEFAULT_DROP is
        # always included.
        self.drop = [_fold(k) for k in [*DEFAULT_DROP, *(drop or [])]]
        self.include = [_fold(k) for k in (include or DEFAULT_INCLUDE)]
        self.exclude = [_fold(k) for k in (exclude if exclude is not None else DEFAULT_EXCLUDE)]
        self.min_price = min_price
        self.max_price = max_price

    def matches(self, p: Product, assume_pokemon: bool = False) -> bool:
        haystack = _fold(" ".join([p.title, *p.tags]))
        if not assume_pokemon and not any(k in haystack for k in self.include):
            return False
        title = _fold(p.title)
        if any(re.search(rf"\b{re.escape(k)}\b", title) for k in self.drop):
            return False
        is_cards = any(re.search(rf"\b{re.escape(k)}\b", title) for k in TCG_WORDS)
        if not is_cards and any(re.search(rf"\b{re.escape(k)}\b", title) for k in self.exclude):
            return False
        if p.price is not None:
            if self.min_price is not None and p.price < self.min_price:
                return False
            if self.max_price is not None and p.price > self.max_price:
                return False
        return True


# ------------------------------------------------------------ purchase limits
# Matches "LIMIT 10 PER CUSTOMER", "Limit 2 per person", "Max 2 per order",
# "(Limit 1)", "limited to 4 per household".
_LIMIT_RE = re.compile(
    r"[\(\[\-–,]*\s*\b(?:limit(?:ed)?(?:\s+to)?|max(?:imum)?)\s*[:\-]?\s*(?:of\s*)?(\d{1,3})"
    r"(?:\s*(?:per|each|/)\s*(?:customer|person|order|household|transaction))?\b\s*[\)\]]*",
    re.I,
)


def purchase_limit(*texts: str) -> int | None:
    for t in texts:
        m = _LIMIT_RE.search(t or "")
        if m:
            return int(m.group(1))
    return None


def clean_title(title: str) -> str:
    """Takes the purchase-limit wording out of a title, since it's shown as a badge."""
    cleaned = _LIMIT_RE.sub(" ", title or "")
    return re.sub(r"\s{2,}", " ", cleaned).strip(" -–,") or title


# ------------------------------------------------------------------- RRP
class RRPTable:
    """Recommended retail prices by product type, from rrp.yaml.

    Rules are checked in order and the first match wins, so list specific
    products before general ones ("mini tin" before "tin")."""

    def __init__(self, rules: list[dict] | None = None, exclude: list[str] | None = None):
        self.rules = [
            {**r, "_match": [_fold(m) for m in (r["match"] if isinstance(r["match"], list) else [r["match"]])]}
            for r in (rules or [])
            if r.get("match") and isinstance(r.get("rrp"), (int, float))
        ]
        self.exclude = [_fold(e) for e in (exclude or [])]

    def lookup(self, title: str) -> float | None:
        t = _fold(title)
        if any(e in t for e in self.exclude):
            return None
        for r in self.rules:
            if any(m in t for m in r["_match"]):
                return float(r["rrp"])
        return None


def over_rrp_percent(price: float | None, rrp: float | None) -> float | None:
    if price is None or not rrp:
        return None
    return round((price - rrp) / rrp * 100, 1)
