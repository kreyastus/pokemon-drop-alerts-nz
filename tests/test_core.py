import json

from pokedrop.adapters import shopify, woocommerce, squarespace, html
from pokedrop.filters import ProductFilter, looks_like_preorder
from pokedrop.models import Product, PREORDER, NEW_LISTING, RESTOCK, PRICE_DROP
from pokedrop.notify.discord import build_embed
from pokedrop.notify.wordpress import sign
from pokedrop.state import State

STORE = {"id": "s", "name": "Shop", "url": "https://shop.example"}


def shopify_payload(available=True, price="89.99", title="Pokémon TCG: Surging Sparks Elite Trainer Box", tags=None):
    return {"products": [{
        "id": 111, "title": title, "handle": "ssp-etb", "tags": tags or ["Pokemon", "Sealed"],
        "product_type": "", "images": [{"src": "https://cdn.example/etb.jpg"}],
        "variants": [{"available": available, "price": price, "compare_at_price": None}],
    }]}


def test_shopify_parse():
    [p] = shopify.parse_products(STORE, shopify_payload())
    assert p.price == 89.99 and p.available and not p.preorder
    assert p.url == "https://shop.example/products/ssp-etb"
    [p] = shopify.parse_products(STORE, shopify_payload(title="PRE-ORDER Mega Evolution Booster Box"))
    assert p.preorder


def test_shopify_string_tags():
    payload = shopify_payload()
    payload["products"][0]["tags"] = "Pokemon, Pre-order"
    [p] = shopify.parse_products(STORE, payload)
    assert p.preorder and p.tags == ["Pokemon", "Pre-order"]


def test_woocommerce_parse():
    items = [{
        "id": 7, "name": "Pok&eacute;mon 151 Booster Bundle", "permalink": "https://w.example/p/151",
        "prices": {"price": "5999", "regular_price": "6999", "currency_minor_unit": 2},
        "is_in_stock": True, "is_purchasable": True, "tags": [], "categories": [{"name": "Pre-orders"}],
        "images": [{"src": "x.jpg"}],
    }]
    [p] = woocommerce.parse_products(STORE, items)
    assert p.title == "Pokémon 151 Booster Bundle"
    assert p.price == 59.99 and p.compare_at_price == 69.99 and p.preorder


def test_squarespace_both_formats():
    payload = {"items": [
        {"id": "a", "title": "Pokemon ETB", "fullUrl": "/shop/p/etb",
         "structuredContent": {"variants": [{"price": 8999, "qtyInStock": 3, "onSale": False}]}},
        {"id": "b", "title": "Pokemon Booster Box", "fullUrl": "/shop/p/bb",
         "structuredContent": {"variants": [{"priceMoney": {"value": "249.00"},
                                             "stock": {"quantity": 0, "unlimited": False}}]}},
    ]}
    a, b = squarespace.parse_items({**STORE, "url": "https://sq.example"}, payload)
    assert a.price == 89.99 and a.available and a.url == "https://sq.example/shop/p/etb"
    assert b.price == 249.0 and not b.available


def test_jsonld_parse():
    page = """<html><script type="application/ld+json">
    {"@context":"https://schema.org","@graph":[{"@type":"ItemList","itemListElement":[
      {"@type":"ListItem","item":{"@type":"Product","name":"Pokemon TCG Prismatic Evolutions ETB",
        "url":"/p/123","sku":"123","image":["/i.jpg"],
        "offers":{"@type":"Offer","price":"99.00","availability":"https://schema.org/PreOrder"}}},
      {"@type":"ListItem","item":{"@type":"Product","name":"Pokemon Booster","url":"/p/456",
        "offers":{"@type":"Offer","price":"7.50","availability":"http://schema.org/OutOfStock"}}}
    ]}]}</script></html>"""
    found = {p.product_id: p for p in html.parse_jsonld(STORE, page, "https://shop.example/c/pokemon")}
    assert found["123"].preorder and found["123"].available and found["123"].price == 99.0
    assert found["123"].url == "https://shop.example/p/123"
    assert not found[next(k for k in found if k != "123")].available


def test_selectors_parse():
    store = {**STORE, "selectors": {"item": ".card", "title": ".t", "price": ".p", "link": "a"}}
    page = """<div class="card"><a href="/x"><span class="t">Pokemon Tin</span></a><span class="p">$29.99</span></div>
              <div class="card"><a href="/y"><span class="t">Pokemon ETB</span></a><span class="p">$1,089.00</span>Sold out</div>"""
    a, b = html.parse_selectors(store, page, "https://shop.example/")
    assert a.price == 29.99 and a.available
    assert b.price == 1089.0 and not b.available


def test_filter():
    f = ProductFilter(min_price=4)
    mk = lambda t, price=50: Product("s", "1", t, "u", price, True)
    assert f.matches(mk("Pokémon Scarlet & Violet Booster Box"))
    assert not f.matches(mk("Pikachu Plush 30cm Pokemon"))
    assert not f.matches(mk("Magic: The Gathering Booster"))
    assert not f.matches(mk("Pokemon single card", price=1.5))
    assert f.matches(mk("Mega Evolution ETB"), assume_pokemon=True)
    assert looks_like_preorder("Pre Order: Phantasmal Flames") and not looks_like_preorder("Booster Box")


def _p(available=True, price=89.99, preorder=False, pid="1", title="Pokemon ETB"):
    return Product("s", pid, title, "https://u", price, available, preorder)


def test_state_lifecycle(tmp_path):
    st = State(str(tmp_path / "state.json"))
    # first scan seeds silently
    assert st.diff(STORE, [_p(available=False)]) == []
    # restock
    [e] = st.diff(STORE, [_p(available=True)])
    assert e.type == RESTOCK
    # no repeat while still in stock
    assert st.diff(STORE, [_p(available=True)]) == []
    # new listing + preorder
    evs = st.diff(STORE, [_p(), _p(pid="2", title="Pokemon New Box"), _p(pid="3", preorder=True)])
    assert sorted(e.type for e in evs) == sorted([NEW_LISTING, PREORDER])
    # price drop of 10%
    evs = st.diff(STORE, [_p(price=80.99), _p(pid="2", title="x"), _p(pid="3", preorder=True)])
    assert [e.type for e in evs] == [PRICE_DROP] and evs[0].old_price == 89.99
    # small drop ignored
    assert st.diff(STORE, [_p(price=79.99), _p(pid="2"), _p(pid="3", preorder=True)]) == []
    st.save()
    assert json.load(open(tmp_path / "state.json"))["stores"]["s"]["seeded"]


def test_missing_then_back_counts_as_restock_but_respects_cooldown(tmp_path):
    st = State(str(tmp_path / "s.json"))
    st.diff(STORE, [_p(), _p(pid="2")])                     # seed
    st.diff(STORE, [_p(pid="2")])                           # item 1 vanishes -> sold out
    assert st.data["products"]["s:1"]["available"] is False
    [e] = st.diff(STORE, [_p(), _p(pid="2")])              # back
    assert e.type == RESTOCK
    st.diff(STORE, [_p(available=False), _p(pid="2")])     # flaps out
    assert st.diff(STORE, [_p(), _p(pid="2")]) == []        # within cooldown: no spam


def test_partial_source_does_not_mark_missing(tmp_path):
    st = State(str(tmp_path / "s.json"))
    st.diff(STORE, [_p(), _p(pid="2")])
    st.diff(STORE, [_p(pid="2")], missing_means_sold_out=False)
    assert st.data["products"]["s:1"]["available"] is True


def test_discord_embed_and_signature():
    from pokedrop.models import Event
    e = Event(PRICE_DROP, _p(price=70.0), "Shop", old_price=90.0, detected_at="2026-10-20T01:00:00+00:00")
    emb = build_embed(e)
    assert emb["fields"][1]["value"] == "NZ$70.00"
    assert "save NZ$20.00" in emb["fields"][2]["value"]
    assert sign("k", "1", b"{}") == sign("k", "1", b"{}") != sign("k2", "1", b"{}")
