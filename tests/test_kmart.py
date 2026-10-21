import json
from datetime import datetime, timedelta, timezone

from pokedrop import cli
from pokedrop.adapters import kmart

BASE = "https://www.kmart.co.nz/product/"
URLS = [BASE + "pokemon-tcg:-30th-celebration-booster-bundle-43818617/",
        BASE + "pokemon-tcg:-30th-celebration-binder-collection-43818594/"]
STORE = {"id": "kmart", "name": "Kmart NZ", "url": "https://www.kmart.co.nz", "adapter": "kmart",
         "pages": ["/category/toys/pokemon-trading-cards/"], "max_details": 1}


def page(props):
    return '<html><script id="__NEXT_DATA__" type="application/json">' + json.dumps({"props": {"pageProps": props}}) + "</script></html>"


CATEGORY = page({"itemListSchema": {"@type": "ItemList", "itemListElement": [{"url": u} for u in URLS]}})


def product(title, price, online, sku):
    return page({"productDetail": {"products": [{"item": {"value": title, "data": {
        "price": price, "image_url": "https://assets.kmart.com.au/x.jpg", "nationalInventory": online, "variation_id": sku}}}]}})


class Client:
    def __init__(self):
        self.calls = []

    def get_text(self, url):
        self.calls.append(url)
        if "category" in url:
            return CATEGORY
        if "43818617" in url:
            return product("Pokemon TCG: 30th Celebration Booster Bundle", 65, False, "43818617")
        return product("Pokemon TCG: 30th Celebration Binder Collection", 80, True, "43818594")


def test_category_urls():
    assert kmart.category_urls(CATEGORY) == URLS


def test_reads_new_products_within_budget_and_caches():
    store, c = {**STORE, "_cache": {}}, Client()
    first = kmart.fetch(store, c)
    assert len(first) == 1 and len(c.calls) == 2          # category + one product page (budget 1)
    second = kmart.fetch(store, Client())
    assert {p.product_id for p in second} == {"43818617", "43818594"}
    bundle = next(p for p in second if p.product_id == "43818617")
    assert not bundle.available and bundle.price == 65 and "Not sold online right now" in bundle.tags
    third = Client()
    assert len(kmart.fetch(store, third)) == 2 and len(third.calls) == 1   # both cached: category only


def test_resting_store_is_skipped_until_due():
    class S:
        data = {"stores": {"kmart": {"last_run": datetime.now(timezone.utc).isoformat()}}}

    assert cli._resting({"id": "kmart", "every_minutes": 30}, S())
    S.data["stores"]["kmart"]["last_run"] = (datetime.now(timezone.utc) - timedelta(minutes=31)).isoformat()
    assert not cli._resting({"id": "kmart", "every_minutes": 30}, S())
    assert not cli._resting({"id": "kmart"}, S())


def test_run_scan_reuses_last_results_while_resting(tmp_path, monkeypatch):
    from pokedrop.adapters import ADAPTERS
    from pokedrop.models import Product
    calls = []

    def fake(store, client):
        calls.append(store["id"])
        return [Product(store["id"], "1", "Pokemon TCG Booster Box", "https://x/1", 99.0, True)]

    monkeypatch.setitem(ADAPTERS, "fake", fake)
    sent = {}
    monkeypatch.setattr(cli, "_deliver", lambda cfg, ev, h, rows, up=None, cat=None: sent.update(rows=rows, cat=cat) or True)
    cfg = {"settings": {"release_dates": False}, "stores": [{"id": "slow", "name": "Slow", "url": "https://x", "adapter": "fake", "every_minutes": 30}]}
    state = str(tmp_path / "s.json")
    cli.run_scan(cfg, state)
    cli.run_scan(cfg, state)
    assert calls == ["slow"]                                  # second run rested
    assert sent["rows"][0]["store_id"] == "slow"             # but its status was reported again


def test_blocked_listing_page_counts_as_failed_check():
    import pytest
    from pokedrop.adapters import html

    class Blocked:
        def get_text(self, url):
            return "<html><title>Farmers</title><body>Farmers.co.nz is temporarily down</body></html>"

    store = {"id": "farmers", "url": "https://www.farmers.co.nz", "pages": ["/toys"], "selectors": {"item": ".product-tile"}}
    with pytest.raises(RuntimeError, match="no products found"):
        html.fetch(store, Blocked())
