"""Command line entry point.

  python -m pokedrop scan                 # one pass over every enabled store
  python -m pokedrop loop --every 5       # keep scanning every 5 minutes (VPS / Raspberry Pi)
  python -m pokedrop detect <url>         # work out how to watch a new shop
  python -m pokedrop test-discord         # send a sample alert to check your webhook
  python -m pokedrop list <store-id>      # show what the scanner sees at one store
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

from . import config as config_mod
from .adapters import ADAPTERS, BRANCH_LOOKUPS
from . import release
from .detect import detect
from .filters import ProductFilter, RRPTable, clean_title, purchase_limit
from .http import PoliteClient
from .models import Event, Product, PREORDER, PRICE_DROP
from .notify import DiscordNotifier, WordPressNotifier
from .state import State, now_iso

log = logging.getLogger("pokedrop")

FULL_FEED_ADAPTERS = {"shopify", "woocommerce", "squarespace"}


def _client(settings: dict) -> PoliteClient:
    kwargs = dict(
        min_delay=float(settings.get("min_delay_seconds", 2)),
        respect_robots=bool(settings.get("respect_robots_txt", True)),
    )
    if settings.get("user_agent"):
        kwargs["user_agent"] = settings["user_agent"]
    return PoliteClient(**kwargs)


def _filter_for(store: dict, settings: dict) -> ProductFilter:
    f = {**(settings.get("filter") or {}), **(store.get("filter") or {})}
    return ProductFilter(
        include=f.get("include"),
        exclude=f.get("exclude"),
        min_price=f.get("min_price"),
        max_price=f.get("max_price"),
        drop=f.get("drop"),
    )


def fetch_store(store: dict, settings: dict) -> tuple[dict, list[Product] | None, str | None]:
    adapter = ADAPTERS.get(store.get("adapter", ""))
    if adapter is None:
        return store, None, f"unknown adapter '{store.get('adapter')}'"
    try:
        products = adapter(store, _client(settings))
    except Exception as exc:  # noqa: BLE001 - one bad store must not stop the rest
        return store, None, f"{type(exc).__name__}: {exc}"
    pf = _filter_for(store, settings)
    assume = bool(store.get("pokemon_only"))  # whole collection is Pokémon already
    kept = [p for p in products if pf.matches(p, assume_pokemon=assume)]
    rrp = settings.get("_rrp_table")
    for p in kept:
        p.limit = purchase_limit(p.title, *p.tags)
        if p.limit:
            p.title = clean_title(p.title)
        if rrp:
            p.rrp = rrp.lookup(p.title)
    return store, kept, None


def _prepare(cfg: dict) -> dict:
    """Builds the RRP table once per run and keeps it with the settings."""
    rrp = cfg.get("rrp") or {}
    cfg["settings"]["_rrp_table"] = RRPTable(rrp.get("rules"), rrp.get("exclude"))
    cfg["settings"]["_rrp_flag_percent"] = float(rrp.get("flag_over_percent", 15))
    return cfg


def run_scan(cfg: dict, state_path: str, dry_run: bool = False) -> list[Event]:
    settings = _prepare(cfg)["settings"]
    stores = [s for s in cfg["stores"] if s.get("enabled", True)]
    state = State(state_path)
    all_events: list[Event] = []
    health: list[str] = []
    status_rows = []
    upcoming: list[dict] = []   # every pre-order we can see, for the release calendar
    catalogue: list[dict] = []  # every product we can see, for price history and the retailer pages
    catalogue_stores: list[str] = []

    # Shops with `every_minutes` are scanned less often; in between, their last
    # results are reported again so the website and calendar keep showing them.
    skipped = [s for s in stores if _resting(s, state)]
    stores = [s for s in stores if s not in skipped]
    for s in stores:
        s["_cache"] = state.data.setdefault("pages", {}).setdefault(s["id"], {})
    for s in skipped:
        st = state.data["stores"].get(s["id"], {})
        log.info("%s: resting (scanned at %s, every %s minutes)", s["id"], st.get("last_run"), s.get("every_minutes"))
        if st.get("last_status"):
            status_rows.append(st["last_status"])
        upcoming.extend(st.get("last_upcoming") or [])
        if st.get("last_items") is not None:
            catalogue_stores.append(s["id"])
            catalogue.extend(st["last_items"])

    # Different shops run in parallel; requests to the same shop stay sequential.
    with ThreadPoolExecutor(max_workers=int(settings.get("parallel_stores", 6))) as pool:
        results = list(pool.map(lambda s: fetch_store(s, settings), stores))

    for store, products, error in results:
        sid = store["id"]
        st = state.data["stores"].setdefault(sid, {})
        if error:
            st["failures"] = st.get("failures", 0) + 1
            st["last_error"] = error
            log.warning("%s: failed (%s) [%d in a row]", sid, error, st["failures"])
            if st["failures"] == int(settings.get("alert_after_failures", 6)):
                health.append(f"⚠️ **{store.get('name', sid)}** has failed {st['failures']} scans in a row: `{error[:150]}`")
            status_rows.append({"store_id": sid, "store_name": store.get("name", sid), "ok": False, "checked_at": now_iso()})
            continue
        if store.get("release_dates", settings.get("release_dates", True)):
            try:
                release.enrich(store, products, state.data.setdefault("releases", {}), _client(settings))
            except Exception as exc:  # noqa: BLE001 - never let the calendar stop alerts
                log.warning("%s: release dates skipped (%s)", sid, exc)
        add_branches(store, products, state, settings)
        store_upcoming = [
            {
                "store_id": sid, "store_name": store.get("name", sid), "title": p.title, "url": p.url,
                "price": p.price, "available": p.available, "image": p.image, "limit": p.limit, "rrp": p.rrp,
                "release_date": p.release_date, "release_precision": p.release_precision,
                "line": release.product_line(p.title),
            }
            for p in products if p.preorder
        ]
        upcoming.extend(store_upcoming)
        if st.get("failures", 0) >= int(settings.get("alert_after_failures", 6)):
            health.append(f"✅ **{store.get('name', sid)}** is scanning again.")
        st["failures"] = 0
        st.pop("last_error", None)
        catalogue_stores.append(sid)
        catalogue.extend(_catalogue_item(store, p) for p in products)
        events = state.diff(
            store,
            products,
            price_drop_pct=float(settings.get("price_drop_percent", 5)),
            cooldown_minutes=int(settings.get("cooldown_minutes", 60)),
            missing_means_sold_out=store.get(
                "missing_means_sold_out", store.get("adapter") in FULL_FEED_ADAPTERS
            ),
        )
        log.info("%s: %d Pokémon products, %d new events", sid, len(products), len(events))
        all_events.extend(events)
        row = {
            "store_id": sid, "store_name": store.get("name", sid), "ok": True,
            "checked_at": now_iso(), "products": len(products),
            "in_stock": sum(1 for p in products if p.available),
        }
        status_rows.append(row)
        if store.get("every_minutes"):
            st.update(last_run=row["checked_at"], last_status=row, last_upcoming=store_upcoming,
                      last_items=[_catalogue_item(store, p) for p in products])

    # Most exciting first: pre-orders, then new, restock, price drops.
    order = {PREORDER: 0, "new": 1, "restock": 2, "price_drop": 3}
    all_events.sort(key=lambda e: order.get(e.type, 9))

    if dry_run:
        for e in all_events:
            extra = f" limit {e.product.limit}" if e.product.limit else ""
            extra += f" RRP {e.product.rrp}" if e.product.rrp else ""
            print(f"[{e.type}] {e.store_name}: {e.product.title} ({e.product.price}){extra} {e.product.url}")
    else:
        due = catalogue_stores and _catalogue_due(state, settings)
        sent = _deliver(cfg, all_events, health, status_rows, upcoming,
                        (catalogue_stores, catalogue) if due else None)
        if sent:
            state.data["catalogue_sent"] = now_iso()
    state.prune(int(settings.get("forget_after_days", 45)))
    state.save()
    return all_events


def _resting(store: dict, state: State) -> bool:
    """True if a shop with `every_minutes` was scanned recently enough to skip this run."""
    minutes = store.get("every_minutes")
    last = state.data["stores"].get(store["id"], {}).get("last_run")
    if not minutes or not last:
        return False
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(last)
    except ValueError:
        return False
    return age.total_seconds() < float(minutes) * 60 - 90


def add_branches(store: dict, products: list[Product], state: State, settings: dict) -> None:
    """Stock at physical shops, for the region pages.

    Chains with a branch stock lookup (Whitcoulls) are asked branch by branch.
    A shop with one physical store (`location:` in its entry) sells from the
    same shelves as its website, so its website stock stands in for the shop."""
    lookup = BRANCH_LOOKUPS.get(store.get("adapter", ""))
    if lookup and store.get("branch_zones"):
        try:
            lookup(store, products, _client(settings), state.data.setdefault("branches", {}),
                   datetime.now(timezone.utc))
        except Exception as exc:  # noqa: BLE001 - never let this stop alerts
            log.warning("%s: branch stock skipped (%s)", store["id"], exc)
    loc = store.get("location")
    if loc and loc.get("name"):
        for p in products:
            p.branches = [{
                "id": store["id"], "name": loc["name"], "region": loc.get("region"),
                "address": loc.get("address"), "units": None, "in_stock": bool(p.available) and not p.preorder,
                "message": None, "basis": "website",
            }]


def _catalogue_item(store: dict, p: Product) -> dict:
    item = {
        "store_id": store["id"], "store_name": store.get("name", store["id"]), "key": p.key,
        "title": p.title, "url": p.url, "image": p.image, "price": p.price,
        "compare_at_price": p.compare_at_price, "available": p.available, "preorder": p.preorder,
        "limit": p.limit, "rrp": p.rrp,
    }
    if p.branches is not None:
        item["branches"] = p.branches
    return item


def _catalogue_due(state: State, settings: dict) -> bool:
    """The full product list goes to the website once an hour (catalogue_minutes),
    which is plenty for price history and keeps each scan light."""
    minutes = int(settings.get("catalogue_minutes", 60))
    last = state.data.get("catalogue_sent")
    if not last:
        return True
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(last)
    except ValueError:
        return True
    return age.total_seconds() >= minutes * 60 - 90  # a little slack for scans that run a few seconds early


def _deliver(cfg, events, health, status_rows, upcoming=None, catalogue=None) -> bool:
    """Sends alerts and the website reports. Returns True if the product list went out."""
    sent = False
    dcfg = cfg.get("discord") or {}
    if dcfg.get("webhook") or dcfg.get("webhooks"):
        if events:
            DiscordNotifier({**dcfg, "rrp_flag_percent": cfg["settings"].get("_rrp_flag_percent", 15)}).send(events)
        hook = dcfg.get("health_webhook")
        if hook and health:
            import requests
            requests.post(hook, json={"content": "\n".join(health)[:1900]}, timeout=20)
    wcfg = cfg.get("wordpress") or {}
    if wcfg.get("url") and wcfg.get("secret"):
        wp = WordPressNotifier(wcfg)
        try:
            if events:
                wp.send(events)
            if wcfg.get("send_status", True):
                wp.send_status(status_rows, upcoming or [], cfg["settings"].get("source", "default"))
            if catalogue:
                sent = wp.send_catalogue(catalogue[0], catalogue[1], cfg["settings"].get("source", "default"))
        except Exception as exc:  # noqa: BLE001
            log.error("WordPress delivery failed: %s", exc)
    return sent


# ------------------------------------------------------------------- commands
def cmd_scan(args):
    cfg = config_mod.load(args.config)
    events = run_scan(cfg, args.state, dry_run=args.dry_run)
    log.info("Done: %d alerts", len(events))


def cmd_loop(args):
    while True:
        started = time.monotonic()
        try:
            cmd_scan(args)
        except Exception:  # noqa: BLE001
            log.exception("Scan crashed; trying again next round")
        wait = max(30, args.every * 60 - (time.monotonic() - started))
        log.info("Sleeping %.0fs", wait)
        time.sleep(wait)


def cmd_detect(args):
    cfg = config_mod.load(args.config) if args.config else {"settings": {}}
    print(detect(args.url, _client(cfg.get("settings", {}))))


def cmd_list(args):
    cfg = config_mod.load(args.config)
    _prepare(cfg)
    store = next((s for s in cfg["stores"] if s["id"] == args.store), None)
    if not store:
        sys.exit(f"No store with id '{args.store}' in {args.config}")
    _, products, error = fetch_store(store, cfg["settings"])
    if error:
        sys.exit(f"Failed: {error}")
    for p in sorted(products, key=lambda p: (not p.available, p.title)):
        flag = "PRE " if p.preorder else ("IN  " if p.available else "OUT ")
        price = f"${p.price:,.2f}" if p.price is not None else "   ?"
        badges = (f"  [limit {p.limit}]" if p.limit else "") + (f"  [RRP ${p.rrp:,.2f}]" if p.rrp else "")
        print(f"{flag} {price:>10}  {p.title[:70]}{badges}")
    print(f"\n{len(products)} Pokémon products, {sum(p.available for p in products)} available")


def cmd_test_discord(args):
    cfg = config_mod.load(args.config)
    # One sample per language, so the English, Japanese and Chinese channels
    # each get one and the main channel gets all three.
    titles = [
        ("1", "Test alert: Pokémon TCG Elite Trainer Box", 89.99),
        ("2", "Test alert: Pokémon TCG Japanese Booster Box", 120.00),
        ("3", "Test alert: Pokémon TCG Gem Pack Booster Box (Simplified Chinese)", 140.00),
    ]
    events = []
    for pid, title, price in titles:
        sample = Product(store_id="test", product_id=pid, title=title,
                         url=f"https://example.com/{pid}", price=price, available=True, preorder=True)
        sample.limit = 2
        sample.rrp = price
        events.append(Event(PREORDER, sample, "PokéDrop test", None, now_iso()))
    # And a price drop, which goes to the price drop channel (if set) and not
    # to the language channels.
    drop = Product(store_id="test", product_id="4", title="Test alert: Pokémon TCG Booster Bundle",
                   url="https://example.com/4", price=45.00, available=True)
    events.append(Event(PRICE_DROP, drop, "PokéDrop test", 59.99, now_iso()))
    DiscordNotifier(cfg.get("discord") or {}).send(events)
    print("Sent. Check your Discord channels.")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pokedrop", description="NZ Pokémon TCG drop alerts")
    ap.add_argument("-c", "--config", default="stores.yaml")
    ap.add_argument("-s", "--state", default="data/state.json")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("scan", help="scan once")
    p.add_argument("--dry-run", action="store_true", help="print alerts instead of sending them")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("loop", help="scan forever")
    p.add_argument("--every", type=float, default=5, help="minutes between scans")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_loop)

    p = sub.add_parser("detect", help="work out how to watch a shop")
    p.add_argument("url")
    p.set_defaults(func=cmd_detect)

    p = sub.add_parser("list", help="show products found at one store")
    p.add_argument("store")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("test-discord", help="send a sample alert")
    p.set_defaults(func=cmd_test_discord)

    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    args.func(args)


if __name__ == "__main__":
    main()
