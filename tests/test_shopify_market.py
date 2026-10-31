"""Shopify prices are asked for in New Zealand dollars, wherever the scanner runs."""
from pokedrop.adapters import shopify


def test_asks_for_nz_market():
    calls = []

    class C:
        def get_json(self, url, headers=None):
            calls.append((url, headers))
            return {"products": [{"id": 1, "title": "Pokemon TCG Chaos Rising Booster Box", "handle": "cr-bb",
                                  "tags": [], "variants": [{"available": True, "price": "300.00"}]}]}

    store = {"id": "s", "url": "https://shop.example", "collections": ["pokemon-sealed"]}
    products = shopify.fetch(store, C())
    url, headers = calls[0]
    assert "currency=NZD" in url and "limit=250" in url
    assert "localization=NZ" in headers["Cookie"] and "cart_currency=NZD" in headers["Cookie"]
    assert products[0].price == 300.0


def test_shop_can_set_its_own_market():
    _, headers = shopify._local_market({"currency": "AUD", "country": "AU"})
    assert headers["Cookie"] == "localization=AU; cart_currency=AUD"
