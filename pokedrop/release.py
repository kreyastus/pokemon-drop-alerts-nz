"""Release dates for the calendar, read from retailers' own pre-order pages.

Nobody publishes an official New Zealand release feed, but retailers state
dates on their pre-order listings, for example:
  JB Hi-Fi:   "Release date 11 Dec 26"
  Otakumart:  "fulfillment currently scheduled for on or after 6th November 2026"
              "Initial Release Date: November 2026"

Pages are only opened for pre-order products, and each one at most once a
day (the answer is remembered in the scan state), so this adds very little
traffic.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone

from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_CUE = r"(?:release(?:s|d)?(?:\s+date)?|releasing|street\s+date|expected(?:\s+(?:release|arrival|date))?|available(?:\s+from)?|on\s+or\s+after|due|eta|ships?|dispatch(?:es)?|launch(?:es)?)"

# "11 Dec 26", "6th November 2026", "14 November"
_DAY_MON = re.compile(_CUE + r"[^0-9a-z]{0,20}(?:on\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+" + _MON + r"\.?(?:,?\s+(\d{2,4}))?", re.I)
# "November 14, 2026"
_MON_DAY = re.compile(_CUE + r"[^0-9a-z]{0,20}" + _MON + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", re.I)
# "14/11/2026" (NZ day-first)
_NUMERIC = re.compile(_CUE + r"[^0-9]{0,20}(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})", re.I)
# "Release Date: November 2026" (month only)
_MON_YEAR = re.compile(_CUE + r"[^0-9a-z]{0,20}" + _MON + r"\.?\s+(\d{4})", re.I)


def _year(y: str | None, month: int, day: int, today: date) -> int:
    if not y:
        guess = date(today.year, month, min(day, 28))
        return today.year + 1 if guess < today - timedelta(days=60) else today.year
    y = int(y)
    return 2000 + y if y < 100 else y


def _valid(y: int, m: int, d: int, today: date):
    try:
        found = date(y, m, d)
    except ValueError:
        return None
    # Ignore dates far in the past (old news on the page) or absurdly far ahead.
    if found < today - timedelta(days=45) or found > today + timedelta(days=730):
        return None
    return found


def parse_release_date(text: str, today: date | None = None) -> tuple[str, str] | None:
    """Returns (ISO date, 'day') or ('YYYY-MM', 'month'), or None.

    Exact days win over month-only mentions; the earliest exact day wins."""
    today = today or datetime.now(timezone.utc).date()
    text = re.sub(r"\s+", " ", text or "")
    days = []
    for m in _DAY_MON.finditer(text):
        mon = MONTHS[m.group(2)[:3].lower()]
        d = _valid(_year(m.group(3), mon, int(m.group(1)), today), mon, int(m.group(1)), today)
        if d:
            days.append(d)
    for m in _MON_DAY.finditer(text):
        mon = MONTHS[m.group(1)[:3].lower()]
        d = _valid(int(m.group(3)), mon, int(m.group(2)), today)
        if d:
            days.append(d)
    for m in _NUMERIC.finditer(text):
        dd, mm, yy = int(m.group(1)), int(m.group(2)), m.group(3)
        d = _valid(_year(yy, mm, dd, today), mm, dd, today) if 1 <= mm <= 12 else None
        if d:
            days.append(d)
    if days:
        return min(days).isoformat(), "day"
    for m in _MON_YEAR.finditer(text):
        mon = MONTHS[m.group(1)[:3].lower()]
        if _valid(int(m.group(2)), mon, 28, today):
            return f"{int(m.group(2)):04d}-{mon:02d}", "month"
    return None


def page_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()
    main = soup.find("main") or soup.body or soup
    return main.get_text(" ", strip=True)


# Product line for grouping the calendar: "Delta Reign Elite Trainer Box |
# Pokemon TCG" and "Delta Reign Booster Bundle" both belong to "Delta Reign".
_NOISE = re.compile(r"\|\s*pok[eé]mon(?:\s+tcg)?\s*$|^(?:pre[\s\-]?order\s*[:\-–]?\s*)?pok[eé]mon(?:\s+(?:tcg|trading card game|trading card))?\s*[:\-–]?\s*|^pre[\s\-]?order\s*[:\-–]?\s*", re.I)
_TYPES = re.compile(
    r"\s*[\-–—:,]?\s*\b(elite trainer box|etb|booster bundle|booster box|booster display|booster pack|"
    r"sleeved booster|\d-booster blister|3 booster blister|blisters?|premium collection|ultra-premium collection|"
    r"special collection|collection box|figure collection|mini tins?|tins?|league battle deck|battle deck|"
    r"build & battle|portfolio|binder|deck)\b.*$",
    re.I,
)


def product_line(title: str) -> str:
    t = _NOISE.sub("", (title or "").strip())
    t = _NOISE.sub("", t).strip()
    line = _TYPES.sub("", t).strip(" -–—:,")
    return line or t


# ------------------------------------------------------------------ enrich
RECHECK_HOURS = 24


def _fetcher(store: dict, client):
    """Plain fetch, or the headless browser for shops that need one (JB Hi-Fi)."""
    if not store.get("render"):
        return client.get_text, None
    from .adapters.html import _Renderer  # Playwright only when needed

    renderer = _Renderer(client.user_agent).__enter__()

    def get(url):
        if not client.allowed(url):
            raise RuntimeError(f"robots.txt disallows {url}")
        # JB Hi-Fi fills in "Release date ..." after the page loads; wait for it
        # (pages without one time out after 20 seconds and are retried tomorrow).
        return renderer.get(url, "text=/release date/i", scroll=False)

    return get, renderer


def enrich(store: dict, products: list, cache: dict, client, now: datetime | None = None) -> int:
    """Adds release_date / release_precision to pre-order products.

    `cache` is the scan state's "releases" section: {product_key: {date,
    precision, checked}}. Returns how many pages were opened."""
    now = now or datetime.now(timezone.utc)
    due = []
    for p in products:
        if not p.preorder:
            continue
        rec = cache.get(p.key) or {}
        checked = rec.get("checked")
        fresh = checked and now - datetime.fromisoformat(checked) < timedelta(hours=RECHECK_HOURS)
        if fresh:
            p.release_date, p.release_precision = rec.get("date"), rec.get("precision")
        else:
            due.append(p)
    if not due:
        return 0
    get, renderer = _fetcher(store, client)
    opened = 0
    try:
        for p in due:
            try:
                found = parse_release_date(page_text(get(p.url)), now.date())
            except Exception as exc:  # noqa: BLE001 - try again tomorrow
                log.debug("%s: release date lookup failed for %s (%s)", store["id"], p.url, exc)
                found = None
            opened += 1
            p.release_date, p.release_precision = found if found else (None, None)
            cache[p.key] = {"date": p.release_date, "precision": p.release_precision,
                            "checked": now.replace(microsecond=0).isoformat()}
    finally:
        if renderer:
            renderer.__exit__(None, None, None)
    log.info("%s: checked release dates on %d pre-order pages", store["id"], opened)
    return opened


def format_release(iso: str | None, precision: str | None) -> str | None:
    if not iso:
        return None
    months = ["January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December"]
    if precision == "month":
        y, m = iso.split("-")[:2]
        return f"{months[int(m) - 1]} {y}"
    d = date.fromisoformat(iso)
    return f"{d.day} {months[d.month - 1]} {d.year}"
