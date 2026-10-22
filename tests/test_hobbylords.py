"""Hobby Lords product tiles (layout from their Pokémon category page)."""
import yaml

from pokedrop.adapters.html import parse_selectors
from pokedrop.filters import ProductFilter

TILE = """
<div class="product-card-container">
  <a class="text-decoration-none" href="/nz/products/single/{slug}">
    <img class="lozad" src="data:image/gif;base64,R0lGOD" data-src="https://cdn.example/{slug}.jpg">
    <p class="gb-pc-name">{name}</p>
  </a>
  <span class="gb-pc-price">{price}</span>
  <button class="gb-pc-cta gb-btn-add-to-cart" data-sku-id="1">{button}</button>
</div>"""

PAGE = "https://hobbylords.com/nz/shop/category/2/pokemon?pc_level_1=&pc_level_2=120"


def store():
    with open("stores.yaml") as f:
        cfg = yaml.safe_load(f)
    return next(s for s in cfg["stores"] if s["id"] == "hobbylords")


def test_tiles():
    html = "".join([
        TILE.format(slug="ascended-heroes-etb", name="Pokemon TCG Ascended Heroes Elite Trainer Box", price="$129.99", button="+ Add to Cart"),
        TILE.format(slug="phantasmal-booster", name="Pokemon TCG Phantasmal Flames Booster Pack", price="$9.00", button="Sold Out"),
    ])
    s = store()
    assert s.get("enabled", True)
    items = parse_selectors(s, html, PAGE)
    assert len(items) == 2
    etb, pack = items
    assert etb.title == "Pokemon TCG Ascended Heroes Elite Trainer Box"
    assert etb.url == "https://hobbylords.com/nz/products/single/ascended-heroes-etb"
    assert etb.price == 129.99 and etb.available
    assert etb.image == "https://cdn.example/ascended-heroes-etb.jpg"
    assert not pack.available


def test_accessories_dropped():
    f = ProductFilter(drop=store()["filter"]["drop"])
    html = TILE.format(slug="x", name="Ultra Pro Pokemon Pikachu Deck Box", price="$20.00", button="+ Add to Cart")
    assert not f.matches(parse_selectors(store(), html, PAGE)[0])
