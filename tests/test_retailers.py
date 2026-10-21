"""Parsing tests built from the real page structure of JB Hi-Fi NZ and Farmers
(captured 20 October 2026, trimmed)."""
import os

import yaml

from pokedrop.adapters import html

HERE = os.path.dirname(__file__)
STORES = {s["id"]: s for s in yaml.safe_load(open(os.path.join(HERE, "..", "stores.yaml")))["stores"]}

JB_CARDS = """
<div class="collection-results-loop">
<div class="ProductCard _10ipotx2f">
  <div><span data-testid="product-card-banner-tag">Pre-Order</span><span data-testid="product-card-promo-tag-0">Online Only</span></div>
  <div class="ProductCard_content" data-testid="product-card-content">
    <a href="/products/pokemon-tcg-pokemon-tcg-mega-greninja-ex-league-battle-deck" class="ProductCard_imageLink" data-testid="product-card-content-link">
      <img alt="Pokemon TCG: Mega Greninja ex League Battle Deck" src="https://cdn.shopify.com/s/files/1/0566/7120/7498/files/487933-Product-0-I-639264271201993394_32x32.jpg?v=1790830386">
      <div data-testid="product-card-title">Pokemon TCG: Mega Greninja ex League Battle Deck</div><div>POKEMON TRADING CARD GAME</div>
    </a>
    <div class="ProductCard_priceContainer"><a href="/products/pokemon-tcg-pokemon-tcg-mega-greninja-ex-league-battle-deck">
      <span>$</span><span data-testid="ticket-price">72</span><span>+ Delivery from $5.99</span></a></div>
    <div class="ProductCard_actionsContainer"><button type="button" data-testid="product-card-actions"><span>Pre-order</span><span>Added</span></button></div>
  </div>
</div>
<div class="ProductCard _10ipotx2f">
  <div><span data-testid="product-card-banner-tag">New at JB!</span></div>
  <div class="ProductCard_content" data-testid="product-card-content">
    <a href="/products/trading-card-game-pokemon-tcg-mini-portfolio-october-2026" data-testid="product-card-content-link">
      <img alt="" src="https://cdn.shopify.com/s/files/1/0566/7120/7498/files/483602-Product-0-I-639228691204067302_32x32.jpg?v=1787272386">
      <div data-testid="product-card-title">Pokémon TCG: Mini Portfolio (October 2026)</div>
    </a>
    <div class="ProductCard_priceContainer"><a href="#"><span>$</span><span data-testid="ticket-price">14</span></a></div>
    <div class="ProductCard_actionsContainer"><button type="button" data-testid="product-card-actions"><span>Add to cart</span><span>Added</span></button></div>
  </div>
</div>
<div class="ProductCard _10ipotx2f">
  <div><span data-testid="product-card-banner-tag">Pre-Order</span></div>
  <div class="ProductCard_content">
    <a href="/products/pokemon-tcg-sold-out-etb" data-testid="product-card-content-link">
      <div data-testid="product-card-title">Pokemon TCG: Sold Out ETB</div></a>
    <div class="ProductCard_priceContainer"><span data-testid="ticket-price">99</span></div>
    <div class="ProductCard_actionsContainer"><button type="button" data-testid="product-card-actions" disabled><span>Sold out</span></button></div>
  </div>
</div>
</div>"""

FARMERS_LISTING = """
<div class="product-list row">
<div class="product-list-item col-md-4 col-xs-6 grid-view">
 <div class="product-tile" data-cnstrc-item-id="7052751" data-dynamic-block-product-sku="7052751">
  <div class="product-image-container"><a href="https://www.farmers.co.nz/toys/games-cards-puzzles/trading-cards/pokemon-trading-card-me5-pitch-black-blisters-assorted-7052751">
   <img src="/INTERSHOP/static/WFS/Farmers-Shop-Site/-/Farmers-Shop/en_NZ/product/70/52/751/7052751_00_W350_H456.jpg" class="product-image" alt="Pokemon Trading Card ME5 Pitch Black Blisters, Assorted product photo"></a></div>
  <a class="product-title" href="https://www.farmers.co.nz/toys/games-cards-puzzles/trading-cards/pokemon-trading-card-me5-pitch-black-blisters-assorted-7052751" data-gtin="196214142756">
   <span class="product-title-span">Pokemon Trading Card ME5 Pitch Black Blisters, Assorted</span>
   <div class="price-container"><div class="current-price" data-testing-id="current-price"><!-- Condition 3: one (sale) price -->$10.99 </div></div></a>
 </div></div>
<div class="product-list-item col-md-4 col-xs-6 grid-view">
 <div class="product-tile" data-cnstrc-item-id="111">
  <a class="product-title" href="https://www.farmers.co.nz/toys/games-cards-puzzles/trading-cards/uefa-champions-league-blister-111">
   <span class="product-title-span">UEFA Champions League 25/26 Blister, Assorted</span>
   <div class="price-container"><div class="current-price">$8.99</div></div></a>
 </div></div>
</div>"""

FARMERS_PRODUCT = """<script type="application/ld+json">
{ "@context": "https://schema.org/", "@type": "Product", "brand": {"@type": "Brand", "name": "Pokemon Trading Card"},
  "name": "Pokemon Trading Card ME5 Pitch Black Blisters, Assorted", "sku": "7052751",
  "offers": {"@type": "Offer", "availability": "https://schema.org/OutOfStock", "price": "9.99", "priceCurrency": "NZD",
  "url": "https://www.farmers.co.nz/toys/games-cards-puzzles/trading-cards/pokemon-trading-card-me5-pitch-black-blisters-assorted-7052751"}}
</script>"""


def test_jbhifi_cards():
    store = STORES["jbhifi"]
    url = "https://www.jbhifi.co.nz/collections/collectibles-merchandise/pokemon-trading-cards"
    assert html.parse_jsonld(store, JB_CARDS, url) == []
    greninja, portfolio, sold_out = html.parse_selectors(store, JB_CARDS, url)
    assert greninja.title == "Pokemon TCG: Mega Greninja ex League Battle Deck"
    assert greninja.url == "https://www.jbhifi.co.nz/products/pokemon-tcg-pokemon-tcg-mega-greninja-ex-league-battle-deck"
    assert greninja.price == 72 and greninja.available and greninja.preorder
    assert greninja.image.endswith("_300x300.jpg?v=1790830386")
    assert portfolio.price == 14 and portfolio.available and not portfolio.preorder
    assert not sold_out.available  # banner says Pre-Order, but the button says Sold out


class FakeClient:
    def __init__(self, pages):
        self.pages = pages
        self.hits = []

    def get_text(self, url):
        self.hits.append(url)
        return self.pages[url]


def test_farmers_listing_then_detail():
    store = STORES["farmers"]
    listing_url = "https://www.farmers.co.nz/toys/games-cards-puzzles/trading-cards"
    product_url = "https://www.farmers.co.nz/toys/games-cards-puzzles/trading-cards/pokemon-trading-card-me5-pitch-black-blisters-assorted-7052751"
    client = FakeClient({listing_url: FARMERS_LISTING, product_url: FARMERS_PRODUCT})
    [p] = html.fetch(store, client)
    assert client.hits == [listing_url, product_url]  # football cards were not opened
    assert p.title.startswith("Pokemon Trading Card ME5")
    assert p.available is False and p.price == 9.99
    assert p.image.startswith("https://www.farmers.co.nz/INTERSHOP/")


def test_farmers_detail_failure_skips_item():
    store = STORES["farmers"]
    listing_url = "https://www.farmers.co.nz/toys/games-cards-puzzles/trading-cards"
    client = FakeClient({listing_url: FARMERS_LISTING})  # product page missing -> KeyError
    assert html.fetch(store, client) == []


def test_toyworld_is_collection_scoped():
    tw = STORES["toyworld"]
    assert tw["adapter"] == "shopify" and set(tw["collections"]) == {"trading-cards", "pokemon"}
