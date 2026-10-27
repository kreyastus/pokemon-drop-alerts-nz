"""English-only Discord channel."""
from pokedrop.filters import language, looks_english
from pokedrop.models import Event, Product
from pokedrop.notify import discord as d


def prod(title, tags=()):
    return Product("s", title, title, "https://x/" + title.replace(" ", "-"), 50.0, True, tags=list(tags))


def test_looks_english():
    assert looks_english(prod("Pokemon TCG Ascended Heroes Elite Trainer Box"))
    assert looks_english(prod("Pokémon TCG: Mega Evolution Booster Bundle"))
    assert not looks_english(prod("Pokemon Japanese Mega Dream ex Booster Box"))
    assert not looks_english(prod("Pokemon Gem Vol 6 Booster Box - Simplified Chinese"))
    assert not looks_english(prod("Pokemon Gem Vol 5 Booster Pack"))
    assert not looks_english(prod("[JP] Nullifying Zero Booster Box"))
    assert not looks_english(prod("Pokemon Korean Terastal Festival Box"))
    assert not looks_english(prod("ポケモンカード 拡張パック"))
    assert not looks_english(prod("s4a High Class Pack Shiny Star V Booster Box | Pokemon TCG"))
    assert not looks_english(prod("Pokemon Card Game Sword & Shield S8a 25th Anniversary Collection Booster Box"))
    assert looks_english(prod("Celebrations US Pokemon Center Exclusive Elite Trainer Box"))
    assert looks_english(prod("Pokemon TCG Scarlet & Violet 151 SV3.5 Booster Bundle"))
    assert not looks_english(prod("Mega Dream ex Booster Box", tags=["Japanese"]))


def test_english_channel_gets_copies_without_pings(monkeypatch):
    sent = []
    monkeypatch.setattr(d.DiscordNotifier, "_post", lambda self, url, payload: sent.append((url, payload)))
    monkeypatch.setattr(d.time, "sleep", lambda s: None)
    n = d.DiscordNotifier({"webhook": "MAIN", "english_webhook": "EN", "roles": {"restock": "123"}})
    n.send([
        Event("restock", prod("Pokemon TCG Ascended Heroes Elite Trainer Box"), "Shop", None, "t"),
        Event("restock", prod("Pokemon Japanese Mega Dream ex Booster Box"), "Shop", None, "t"),
    ])
    by_url = {u: p for u, p in sent}
    assert len(by_url["MAIN"]["embeds"]) == 2 and "<@&123>" in by_url["MAIN"]["content"]
    assert len(by_url["EN"]["embeds"]) == 1 and not by_url["EN"]["content"]
    assert by_url["EN"]["allowed_mentions"]["roles"] == []


def test_no_english_channel_by_default(monkeypatch):
    sent = []
    monkeypatch.setattr(d.DiscordNotifier, "_post", lambda self, url, payload: sent.append(url))
    monkeypatch.setattr(d.time, "sleep", lambda s: None)
    d.DiscordNotifier({"webhook": "MAIN", "english_webhook": ""}).send(
        [Event("new", prod("Pokemon TCG Booster Box"), "Shop", None, "t")])
    assert sent == ["MAIN"]


def test_language():
    assert language(prod("Pokemon TCG Ascended Heroes Elite Trainer Box")) == "english"
    assert language(prod("Pokemon Japanese Mega Dream ex Booster Box")) == "japanese"
    assert language(prod("[JP] Nullifying Zero Booster Box")) == "japanese"
    assert language(prod("s4a High Class Pack Shiny Star V Booster Box")) == "japanese"
    assert language(prod("ポケモンカード 拡張パック")) == "japanese"
    assert language(prod("Pokemon Gem Vol 5 Booster Pack")) == "chinese"
    assert language(prod("Pokémon TCG GEM Pack VOL 6 Booster Box (Simplified Chinese)")) == "chinese"
    assert language(prod("Pokemon TCG S-Chinese Collect 151 Gather ex Coin Booster Collection Set")) == "chinese"
    assert language(prod("宝可梦 集换式卡牌")) == "chinese"
    assert language(prod("Pokemon Korean Terastal Festival Box")) == "other"
    assert language(prod("Mega Dream ex Booster Box", tags=["Japanese"])) == "japanese"


def test_language_channels(monkeypatch):
    sent = []
    monkeypatch.setattr(d.DiscordNotifier, "_post", lambda self, url, payload: sent.append((url, len(payload["embeds"]), payload["content"])))
    monkeypatch.setattr(d.time, "sleep", lambda s: None)
    n = d.DiscordNotifier({"webhook": "MAIN", "english_webhook": "EN", "japanese_webhook": "JP",
                           "chinese_webhook": "CN", "roles": {"new": "9"}})
    n.send([Event("new", prod(t), "Shop", None, "t") for t in [
        "Pokemon TCG Booster Box", "Pokemon Japanese Booster Box", "Pokemon Gem Vol 5 Booster Box",
        "Pokemon Korean Booster Box"]])
    got = {u: (k, c) for u, k, c in sent}
    assert got["MAIN"] == (4, "<@&9>")
    assert got["EN"] == (1, None) and got["JP"] == (1, None) and got["CN"] == (1, None)


def test_price_drops_own_channel_not_language_channels(monkeypatch):
    sent = []
    monkeypatch.setattr(d.DiscordNotifier, "_post", lambda self, url, payload: sent.append((url, len(payload["embeds"]))))
    monkeypatch.setattr(d.time, "sleep", lambda s: None)
    n = d.DiscordNotifier({"webhook": "MAIN", "webhooks": {"price_drop": "DROPS"}, "english_webhook": "EN",
                           "language_events": ["preorder", "new", "restock"]})
    n.send([Event("price_drop", prod("Pokemon TCG Booster Box"), "Shop", 99.0, "t"),
            Event("restock", prod("Pokemon TCG Elite Trainer Box"), "Shop", None, "t")])
    assert sorted(sent) == [("DROPS", 1), ("EN", 1), ("MAIN", 1)]
