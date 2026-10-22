from datetime import datetime, timedelta, timezone

from pokedrop import cli
from pokedrop.adapters import whitcoulls
from pokedrop.models import Product

STORE = {"id": "whitcoulls", "name": "Whitcoulls", "url": "https://www.whitcoulls.co.nz",
         "adapter": "whitcoulls", "branch_zones": {"ZONE11": "Canterbury"}}

ROWS = [
    {"SITE": "W012", "SITE_NAME": "Whitcoulls Hornby", "UNRESTRICTED": "3.000", "IN_TRANSIT": "0.000",
     "ON_ORDER": "0.000", "SOH_MESSAGE": "Low stock, phone store", "name": "Hornby", "storeid": "12"},
    {"SITE": "W020", "SITE_NAME": "Whitcoulls Riccarton", "UNRESTRICTED": "0.000", "IN_TRANSIT": "0.000",
     "ON_ORDER": "6.000", "SOH_MESSAGE": "Sorry, not in stock", "name": "Riccarton", "storeid": "20"},
]


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


class FakeClient:
    def __init__(self, body=None, fail=False):
        self.calls = []
        self.body = body if body is not None else {"status": True, "data": ROWS}
        self.fail = fail

    def post_form(self, url, data, headers=None):
        self.calls.append((url, data))
        if self.fail:
            raise RuntimeError("boom")
        return FakeResponse(self.body)


def prod(pid="7100001", available=True, preorder=False):
    return Product("whitcoulls", pid, "Pokemon TCG: Delta Reign Booster Bundle", "u", 59.99, available, preorder)


def test_branch_stock_reads_each_branch():
    now = datetime(2026, 10, 22, 9, tzinfo=timezone.utc)
    p, client, cache = prod(), FakeClient(), {}
    assert whitcoulls.branch_stock(STORE, [p], client, cache, now) == 1
    url, data = client.calls[0]
    assert url == "https://www.whitcoulls.co.nz/api/product/checkstorestock"
    assert data == {"barcode": "7100001", "zone": "ZONE11"}
    hornby, ricc = p.branches
    assert hornby["name"] == "Whitcoulls Hornby" and hornby["units"] == 3 and hornby["in_stock"]
    assert hornby["region"] == "Canterbury" and hornby["message"] == "Low stock, phone store"
    assert not ricc["in_stock"] and ricc["on_order"] == 6


def test_branch_stock_is_cached_for_an_hour():
    now = datetime(2026, 10, 22, 9, tzinfo=timezone.utc)
    cache = {}
    whitcoulls.branch_stock(STORE, [prod()], FakeClient(), cache, now)
    again = FakeClient()
    p = prod()
    assert whitcoulls.branch_stock(STORE, [p], again, cache, now + timedelta(minutes=30)) == 0
    assert not again.calls and len(p.branches) == 2
    assert whitcoulls.branch_stock(STORE, [prod()], again, cache, now + timedelta(minutes=61)) == 1


def test_failed_lookup_keeps_last_answer_or_leaves_unknown():
    now = datetime(2026, 10, 22, 9, tzinfo=timezone.utc)
    p = prod()
    whitcoulls.branch_stock(STORE, [p], FakeClient(fail=True), {}, now)
    assert p.branches is None  # unknown, so the website keeps what it had
    cache = {}
    whitcoulls.branch_stock(STORE, [prod()], FakeClient(), cache, now)
    p = prod()
    whitcoulls.branch_stock(STORE, [p], FakeClient(fail=True), cache, now + timedelta(hours=2))
    assert len(p.branches) == 2


def test_location_store_uses_website_stock():
    store = {"id": "cmchch", "name": "Card Merchant Christchurch", "adapter": "shopify",
             "location": {"name": "Card Merchant Christchurch", "region": "Canterbury",
                          "address": "7/300 Lincoln Road, Addington, Christchurch 8024"}}
    a = Product("cmchch", "1", "Pokemon ETB", "u", 99.0, True)
    b = Product("cmchch", "2", "Pokemon ETB pre-order", "u", 99.0, True, preorder=True)

    class S:
        data = {}

    cli.add_branches(store, [a, b], S(), {})
    assert a.branches[0]["in_stock"] and a.branches[0]["basis"] == "website"
    assert not b.branches[0]["in_stock"]  # a pre-order isn't on the shelf yet
    assert cli._catalogue_item(store, a)["branches"][0]["address"].startswith("7/300")
    assert "branches" not in cli._catalogue_item(store, Product("x", "3", "t", "u", 1.0, True))


def test_drop_words_beat_card_words():
    store = {"id": "cmchch", "filter": {"drop": ["ticket", "entry"]}}
    pf = cli._filter_for(store, {"filter": {"include": ["pokemon"], "min_price": 4}})
    assert not pf.matches(Product("cmchch", "1", "Pokemon TCG Prerelease Ticket - Saturday", "u", 30.0, True))
    assert pf.matches(Product("cmchch", "2", "Pokemon TCG Mega Evolution Booster Box", "u", 250.0, True))
    assert not pf.matches(Product("cmchch", "3", "Pokemon plush Pikachu", "u", 30.0, True))  # built-in list still applies


def test_pokemon_toys_are_left_out_but_tins_stay():
    from pokedrop.filters import ProductFilter
    pf = ProductFilter(include=["pokemon"], min_price=4)
    toys = ["Pokemon Clip N Go Ball, Assorted", "Guess Who Pokemon Edition", "Nanoblock Pokemon - Gengar",
            "Pokemon Select 3 Inch Battle Figure Gengar", "POKEMON - MODEL KIT QUICK!! 28 MEOWTH"]
    cards = ["Pokemon TCG Poke Ball Tin Series 9", "Pokemon TCG 30th Celebration Figure Collection"]
    assert not any(pf.matches(Product("t", "1", t, "u", 30.0, True)) for t in toys)
    assert all(pf.matches(Product("t", "1", t, "u", 30.0, True)) for t in cards)


def test_key_rings_and_graded_cards_removed():
    from pokedrop.filters import ProductFilter
    from pokedrop.models import Product

    f = ProductFilter()
    def ok(title):
        return f.matches(Product("s", "1", title, "https://x/1", 20.0, True))
    assert not ok("Pokemon Key Rings")
    assert not ok("Pokemon Pikachu Key Ring")
    assert not ok("2023 POKEMON MEW EN-151 #199 CHARIZARD ex SPECIAL ILLUSTRATION RARE - PSA 10")
    assert not ok("2025 Pokemon Japanese M2A-Mega Dream Ex #226 Mega Gardevoir Ex Mega Attack Rare PSA 10")
    assert not ok("Pokemon TCG Umbreon VMAX CGC 9.5")
    assert ok("Pokemon TCG Ascended Heroes Elite Trainer Box")
    assert ok("Pokemon TCG Poke Ball Tin")
