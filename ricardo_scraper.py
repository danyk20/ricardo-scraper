#!/usr/bin/env python3
"""
Ricardo.ch marketplace listing scraper.

Modeled on `danyk20/autoscout24-scraper` -- same library-and-CLI dual usage,
same ScrapeResult/CSV/JSON shape, same logging convention -- so a project
using one can swap to the other with minimal code changes. See that
project's README for the sibling story of a *different* Swiss marketplace
that turned out to have a much easier path (a public, un-protected JSON
API). Ricardo did not have that option: see below.

ricardo.ch is a Next.js app sitting behind a Cloudflare Managed Challenge
that a plain HTTP client (requests, cloudscraper, etc.) cannot solve -- it
requires real browser JS execution and fingerprinting checks. There is no
separate, unauthenticated JSON API the way api.autoscout24.ch is for
AutoScout24. So instead of talking to an API, this scraper drives a real,
fingerprint-patched Firefox via camoufox (github.com/daijro/camoufox),
which passes the challenge like a normal browser, then parses two things
out of each listing's own page: its embedded schema.org `Product` JSON-LD
block (`<script id="pdp-json-ld">`, rendered server-side for SEO) for
title, description, price, condition, seller, brand, category breadcrumbs,
images; and its `#__NEXT_DATA__` blob (Next.js's own server-rendered props,
a single JSON script tag) for fields Ricardo doesn't put in the SEO data:
location (city/zip), seller rating, structured delivery options, and
questions & answers.

Two-phase scraping, mirroring AutoScout24's search-then-detail split:

1. Search (`search_listings()`): walks `ricardo.ch/<locale>/s/<query>?page=N`,
   extracting a summary per listing (id, title, url, price, thumbnail) from
   the search-results DOM, paginating until a page returns zero results,
   de-duplicated by id (Ricardo can pin a "boosted" listing to the first
   slot of every page).
2. Detail (`visit_all_listings()`, the `detail=True` default): visits each
   listing's own page and parses its `pdp-json-ld` block and `#__NEXT_DATA__`
   blob (see `extract_product_jsonld()`/`extract_next_data()`) for the full
   record. `detail=False` / `--no-detail` skips this and keeps only the
   fast summary fields.

Unlike AutoScout24's search API, ricardo.ch's search does **not** honor
price/category as real server-side filters (verified: identical result
price ranges with and without `price_from`/`price_to` query params --
Ricardo's real filter mechanism is a serialized, per-category facet system
not reverse-engineered here). So `price_from`/`price_to`/`category` are
applied **client-side** instead: price is filtered against the search
summary (before the expensive detail visit, where possible); category is
matched against the JSON-LD category breadcrumbs, which only exist once a
listing has been visited in detail -- passing `category` together with
`detail=False` raises `ValueError` since there is nothing to filter against.

This module can be used two ways:

1. As a standalone CLI script that writes a CSV + JSON file:

    python3 ricardo_scraper.py "laptop"
    python3 ricardo_scraper.py "laptop" --out my_search
    python3 ricardo_scraper.py "laptop" --no-detail   # skip per-listing detail fetch
    python3 ricardo_scraper.py "laptop" --price-to 500

2. As a library, imported from another project, returning data directly
   instead of writing files:

    from ricardo_scraper import scrape

    result = scrape("laptop", price_to=500)
    for row in result.rows:          # flattened dicts, one per listing
        print(row["price"], row["url"])
    result.listings                  # raw (unflattened) per-listing records
    result.to_csv("laptops.csv")     # optional, if you want a file after all
    result.to_json("laptops.json")
"""

import argparse
import csv
import json
import logging
import re
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from camoufox.sync_api import Camoufox
from playwright.sync_api import Error as PlaywrightError

from pin_camoufox_browser import ensure_pinned_browser

__version__ = "0.2.0"

DEFAULT_LOCALE = "de"
BASE_URL = "https://www.ricardo.ch"

# Library code only ever logs through this logger - it never calls
# basicConfig or attaches handlers of its own (that would be rude to a host
# application). The CLI (see _configure_cli_logging(), used by main()) is the
# only place that sets up real handlers, so plain library use is silent
# unless the caller configures logging themselves, e.g.:
#     import logging; logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ricardo_scraper")
logger.addHandler(logging.NullHandler())

# Extracts, per listing card: href, title (from the high-priority thumbnail's
# alt text), thumbnail url, and every numeric-looking price span. Matching on
# numeric text rather than locale-specific labels ("Sofort kaufen"/"Gebote")
# keeps this working across de/fr/it without a translation table. The *last*
# numeric value is always the buy-now/fixed price (auctions render bid price
# first, buy-now price second; a plain fixed-price listing has just the one
# value) -- this holds regardless of locale since it's positional, not
# text-matched.
SEARCH_SUMMARY_JS = """
() => {
  const container = document.querySelector('[data-testid="regular-results"]');
  if (!container) return [];
  const cards = Array.from(container.querySelectorAll('a[href^="/' + LOCALE + '/a/"]'));
  return cards.map(card => {
    const href = card.getAttribute('href');
    const idMatch = href.match(/-(\\d+)\\/?$/);
    const img = card.querySelector('img[fetchpriority="high"]');
    const prices = Array.from(card.querySelectorAll('span'))
      .map(s => s.textContent.trim())
      .filter(t => /^\\d+[.,]\\d{2}$/.test(t))
      .map(t => parseFloat(t.replace(',', '.')));
    return {
      id: idMatch ? idMatch[1] : null,
      title: img ? img.getAttribute('alt') : null,
      url: href,
      price: prices.length ? prices[prices.length - 1] : null,
      image: img ? img.getAttribute('src') : null,
    };
  });
}
"""


class BrowserSession:
    """Wraps one camoufox browser + page for reuse across scrape() calls,
    the direct analog of AutoScout24's requests.Session reuse -- create one
    and pass it via scrape(..., session=...) to avoid relaunching a browser
    per call. A scrape() call that creates its own session (the common case)
    closes it when done; a session you pass in yourself is yours to close.
    """

    def __init__(self, headless: bool = True):
        ensure_pinned_browser()
        self._camoufox = Camoufox(headless=headless, humanize=True)
        browser = self._camoufox.__enter__()
        self.page = browser.new_page()

    # Titles Cloudflare's interstitial is known to use while its challenge is
    # still resolving. Not exhaustive by construction -- if a future variant
    # slips through, the retry loop in extract_product_jsonld() is the
    # second line of defense (this list is a fast-path optimization, not the
    # only thing standing between a caller and a challenge page).
    _INTERSTITIAL_TITLES = ("loading", "just a moment", "please wait", "checking your browser", "attention required")

    def goto(self, url: str, *, attempts: int = 4, settle_ms: int = 2000) -> None:
        """Navigate to url, tolerating Cloudflare's challenge redirect.

        Cloudflare occasionally kicks off a second (challenge-solving)
        navigation while the first is still in flight (surfaced by
        Playwright as an "interrupted by another navigation" error), and/or
        the challenge is still resolving after `goto` returns, leaving the
        page on an interstitial state for a few seconds (observed titles:
        "Loading...", "Just a moment..."). Both are transient, so poll the
        page title past any known interstitial before treating the page as
        ready.
        """
        for attempt in range(attempts):
            try:
                self.page.goto(url, timeout=60000)
            except PlaywrightError as exc:
                if attempt < attempts - 1 and "interrupted by another navigation" in str(exc):
                    self.page.wait_for_timeout(settle_ms)
                    continue
                raise

            for _ in range(10):
                self.page.wait_for_timeout(settle_ms)
                title = self.page.title().lower()
                if not any(title.startswith(t) for t in self._INTERSTITIAL_TITLES):
                    return
        return  # pragma: no cover - all attempts exhausted; page is handed back as-is rather than raising

    def evaluate(self, js: str) -> Any:
        return self.page.evaluate(js)

    def close(self) -> None:
        self._camoufox.__exit__(None, None, None)

    def __enter__(self) -> "BrowserSession":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def search_listings(
    session: BrowserSession,
    query: str,
    locale: str = DEFAULT_LOCALE,
    delay: float = 1.5,
    verbose: bool = True,
    max_results: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch every listing summary for a free-text query, deduplicated by id.

    Ricardo can pin a "boosted" listing into the first slot of every search
    page, which would otherwise make it reappear across pages; de-duplicating
    by id as we paginate handles this automatically.

    Each returned summary has: id, title, url (full ad URL), price (the
    buy-now/fixed price, a float, or None if a listing has no numeric price
    rendered), image (thumbnail URL).
    """
    js = SEARCH_SUMMARY_JS.replace("LOCALE", json.dumps(locale))
    seen_ids: set[str] = set()
    listings: list[dict[str, Any]] = []
    page_num = 1

    while max_results is None or len(listings) < max_results:
        url = f"{BASE_URL}/{locale}/s/{query}?page={page_num}"
        session.goto(url)
        items = session.evaluate(js)
        if not items:
            break

        new_count = 0
        for item in items:
            if not item.get("id") or item["id"] in seen_ids:
                continue
            seen_ids.add(item["id"])
            item["url"] = f"{BASE_URL}{item['url']}"
            listings.append(item)
            new_count += 1

        if verbose:
            logger.info(
                "  page %d: %d listings (%d new, %d total so far)",
                page_num,
                len(items),
                new_count,
                len(listings),
            )

        page_num += 1
        if max_results is None or len(listings) < max_results:
            time.sleep(delay)

    return listings[:max_results] if max_results is not None else listings


def _evaluate_with_retry(session: BrowserSession, js: str, *, attempts: int = 3, retry_wait_ms: int = 1500) -> Any:
    """Evaluate js, retrying a few times on a falsy result.

    The generic "page title past Loading" readiness check in
    BrowserSession.goto() occasionally isn't a tight enough signal for a
    specific script tag to have rendered yet -- the very first navigation in
    a fresh browser session can return before it's there even though the
    title has already moved past "Loading" (observed in testing: reliable
    on a session's 2nd+ navigation, occasionally missing on the 1st). So
    retry a few times with a short wait rather than treating an empty
    result as final immediately.
    """
    for attempt in range(attempts):
        result = session.evaluate(js)
        if result:
            return result
        if attempt < attempts - 1:
            session.page.wait_for_timeout(retry_wait_ms)
    return None


def extract_product_jsonld(session: BrowserSession, **kwargs: Any) -> dict[str, Any] | None:
    """Pull the schema.org Product node out of the current detail page's
    JSON-LD block."""
    raw = _evaluate_with_retry(session, "document.getElementById('pdp-json-ld')?.textContent || null", **kwargs)
    if not raw:
        return None
    data = json.loads(raw)
    for node in data.get("@graph", []):
        if node.get("@type") == "Product":
            return node
    return None


def extract_next_data(session: BrowserSession, **kwargs: Any) -> dict[str, Any] | None:
    """Pull and parse the current detail page's `#__NEXT_DATA__` blob --
    Next.js's own server-rendered props, which (unlike the JSON-LD block)
    carries fields ricardo.ch doesn't put in the SEO data: the listing's
    location, the seller's rating, structured delivery options, and
    questions & answers. Returns the parsed top-level object, or None if
    it's missing/unparseable (e.g. a genuinely different page shape)."""
    raw = _evaluate_with_retry(session, "document.getElementById('__NEXT_DATA__')?.textContent || null", **kwargs)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _extract_extra_fields(next_data: dict[str, Any] | None) -> dict[str, Any]:
    """Pulls location/seller-rating/delivery/Q&A out of a parsed
    #__NEXT_DATA__ blob (see extract_next_data()). Degrades to empty/None
    values rather than raising if any part of the expected shape is
    missing -- this is supplementary data layered on top of the JSON-LD
    record, not something a listing should be dropped over."""
    defaults: dict[str, Any] = {
        "location_city": None,
        "location_zip": None,
        "seller_rating_score": None,
        "seller_ratings_count": None,
        "delivery_options": [],
        "questions_and_answers": [],
    }
    if not next_data:
        return defaults

    try:
        page_props = next_data["props"]["pageProps"]
        article = page_props["article"]
    except (KeyError, TypeError):
        article = {}

    offer = article.get("offer") or {}
    defaults["location_city"] = offer.get("city")
    defaults["location_zip"] = offer.get("zip_code")

    seller = article.get("seller") or {}
    score = seller.get("score")
    defaults["seller_rating_score"] = round(score * 100, 2) if isinstance(score, (int, float)) else None
    defaults["seller_ratings_count"] = seller.get("ratingsCount")

    defaults["delivery_options"] = [
        {
            "id": opt.get("id"),
            "price": (opt["price"] / 100) if isinstance(opt.get("price"), (int, float)) else None,
            "cumulative": opt.get("isCumulativeShipping"),
        }
        for opt in (article.get("deliveryOptions") or [])
    ]

    try:
        queries = page_props["dehydratedState"]["queries"]
    except (KeyError, TypeError):
        queries = []
    for query in queries:
        if query.get("queryKey", [None])[0] == "get-questions-and-answers":
            qa_data = query.get("state", {}).get("data") or []
            defaults["questions_and_answers"] = [
                {
                    "question": (qa.get("question") or {}).get("text"),
                    "question_date": (qa.get("question") or {}).get("date"),
                    "answer": (qa.get("answer") or {}).get("text"),
                    "answer_date": (qa.get("answer") or {}).get("date"),
                }
                for qa in qa_data
            ]
            break

    return defaults


def _listing_from_product(product: dict[str, Any], url: str, extra: dict[str, Any]) -> dict[str, Any]:
    offer = product.get("offers", {}) or {}
    seller = offer.get("seller", {}) or {}
    brand = product.get("brand", {}) or {}
    categories = [
        c.get("url", "").rstrip("/").rsplit("/", 1)[-1]
        for c in product.get("category", [])
        if isinstance(c, dict) and c.get("url")
    ]
    return {
        "id": product.get("sku"),
        "title": product.get("name"),
        "description": product.get("description"),
        "url": url,
        "price": offer.get("price"),
        "currency": offer.get("priceCurrency", "CHF"),
        "condition": (offer.get("itemCondition") or "").rsplit("/", 1)[-1] or None,
        "availability": (offer.get("availability") or "").rsplit("/", 1)[-1] or None,
        "availability_ends": offer.get("availabilityEnds"),
        "seller_name": seller.get("name"),
        "seller_url": seller.get("url"),
        "brand": brand.get("name"),
        "categories": categories,
        "images": product.get("image", []),
        **extra,
    }


def visit_all_listings(
    session: BrowserSession,
    listings: list[dict[str, Any]],
    delay: float = 1.5,
    verbose: bool = True,
) -> list[dict[str, Any]]:
    """Visit each listing's own page one by one and replace its summary
    record with the full record: the JSON-LD-derived fields (title,
    description, price, condition, seller, brand, categories, images) plus
    location, seller rating, delivery options, and questions & answers
    pulled from the same page's `#__NEXT_DATA__` blob (see
    extract_next_data()) -- no extra navigation needed for the latter.

    A listing whose detail page doesn't yield a parseable JSON-LD block
    (rare in testing, but not impossible -- e.g. a listing that ended
    between the search and detail phase) is skipped with a warning rather
    than included with inconsistent fields. A missing/unparseable
    `#__NEXT_DATA__` blob is not fatal -- the listing is still included,
    just with the location/rating/delivery/Q&A fields left as their
    defaults (None/empty), since that data is supplementary to the core
    JSON-LD record.
    """
    visited = []
    total = len(listings)
    for i, item in enumerate(listings, 1):
        session.goto(item["url"])
        product = extract_product_jsonld(session)
        if product is None:
            logger.warning("  no product data found for %s -- skipping", item["url"])
        else:
            next_data = extract_next_data(session)
            extra = _extract_extra_fields(next_data)
            visited.append(_listing_from_product(product, item["url"], extra))
        if verbose and (i % 10 == 0 or i == total):
            logger.info("  visited %d/%d listings", i, total)
        if i < total:
            time.sleep(delay)
    return visited


def _category_matches(categories: Iterable[str], category: str) -> bool:
    category = str(category)
    return any(c == category or c.endswith(f"-{category}") for c in categories)


# Fields worth pulling to the front of the CSV; everything else discovered on
# the listing objects is appended afterwards, sorted alphabetically, so no
# field is ever silently dropped.
PRIORITY_FIELDS = [
    "id",
    "title",
    "price",
    "currency",
    "condition",
    "brand",
    "location_city",
    "location_zip",
    "seller_name",
    "seller_rating_score",
    "seller_ratings_count",
    "categories",
    "url",
]


def _scalarize(value: Any) -> Any:
    """Turn a nested dict/list value into something that fits one CSV cell."""
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, list):
        return "; ".join(str(_scalarize(v)) for v in value)
    return str(value)


def flatten_listing(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten a listing into one flat dict covering every field it has, so
    nothing is lost when writing a CSV row."""
    flat: dict[str, Any] = {}
    for key, value in item.items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                flat[f"{key}_{sub_key}"] = _scalarize(sub_value)
            continue
        flat[key] = _scalarize(value)
    return flat


def order_fieldnames(all_keys: Iterable[str]) -> list[str]:
    ordered = [f for f in PRIORITY_FIELDS if f in all_keys]
    remaining = sorted(k for k in all_keys if k not in ordered)
    return ordered + remaining


def save_csv(rows: list[dict[str, Any]], path: str) -> None:
    if not rows:
        logger.warning("no rows to write")
        return
    all_keys: set[str] = set()
    for row in rows:
        all_keys.update(row.keys())
    fieldnames = order_fieldnames(all_keys)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, restval="")
        writer.writeheader()
        writer.writerows(rows)


def save_json(rows: list[dict[str, Any]], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


@dataclass
class ScrapeResult:
    """Everything a scrape() call produced, ready to use in-memory or save to disk."""

    query: str
    locale: str
    category: str | None
    total_elements: int
    listings: list[dict[str, Any]] = field(default_factory=list)  # raw per-listing records
    rows: list[dict[str, Any]] = field(default_factory=list)  # flattened dicts, one per listing, CSV-ready

    def to_csv(self, path: str) -> None:
        save_csv(self.rows, path)

    def to_json(self, path: str) -> None:
        save_json(self.listings, path)


def scrape(
    query: str,
    *,
    locale: str = DEFAULT_LOCALE,
    category: str | None = None,
    detail: bool = True,
    price_from: float | None = None,
    price_to: float | None = None,
    delay: float = 1.5,
    max_results: int | None = None,
    verbose: bool = True,
    headless: bool = True,
    session: BrowserSession | None = None,
) -> ScrapeResult:
    """Search ricardo.ch for a free-text query and return the results in memory.

    This is the library entry point: it does the same work as the CLI but
    returns a ScrapeResult instead of writing files. The CLI (main(), below)
    is a thin wrapper around this function.

    Args:
        query: Free-text search term, e.g. "laptop" or "iphone 13".
        locale: Ricardo locale ("de"/"fr"/"it"), default "de".
        category: Optional Ricardo category id (e.g. "39272" for
            "Notebooks"). Matched client-side against each listing's JSON-LD
            category breadcrumbs -- see the module docstring for why this
            isn't a real server-side filter, and why it requires
            detail=True.
        detail: If True (default), visit every listing's own page to
            extract the full record (description, condition, seller, brand,
            images, ...). If False, keep only the fast summary fields
            (id, title, url, price, image) -- much faster, no per-listing
            browser navigation.
        price_from/price_to: Optional price range in CHF (inclusive).
            Applied client-side against the search summary, before the
            (optional) detail visit.
        delay: Seconds to wait between requests.
        max_results: Optional cap on how many listings to collect.
        verbose: If True, emit progress via the "ricardo_scraper" logger.
        headless: If True (default), run the browser with no window.
        session: Optional BrowserSession to reuse (e.g. across repeated
            calls). A new one is created -- and closed at the end of this
            call -- if not given.

    Returns:
        A ScrapeResult with `.listings` (raw per-listing records) and
        `.rows` (flattened dicts, one per listing, sorted by price).

    Raises:
        ValueError: if price_from > price_to, or if category is given with
            detail=False (category data only exists after a detail visit).
    """
    if price_from is not None and price_to is not None and price_from > price_to:
        raise ValueError(f"price_from ({price_from}) cannot be greater than price_to ({price_to})")
    if category is not None and not detail:
        raise ValueError("category filtering requires detail=True (category isn't in the search summary)")

    owns_session = session is None
    session = session or BrowserSession(headless=headless)
    try:
        if verbose:
            logger.info("Searching ricardo.ch/%s for %r ...", locale, query)
        listings = search_listings(session, query, locale=locale, delay=delay, verbose=verbose, max_results=max_results)
        total_elements = len(listings)

        if price_from is not None or price_to is not None:
            before = len(listings)
            listings = [
                item
                for item in listings
                if item.get("price") is not None
                and (price_from is None or item["price"] >= price_from)
                and (price_to is None or item["price"] <= price_to)
            ]
            if verbose:
                logger.info("  price filter: %d/%d listings kept", len(listings), before)

        if detail:
            if verbose:
                logger.info("Visiting each of %d listings for full details ...", len(listings))
            listings = visit_all_listings(session, listings, delay=delay, verbose=verbose)

            if category is not None:
                before = len(listings)
                listings = [item for item in listings if _category_matches(item.get("categories", []), category)]
                if verbose:
                    logger.info("  category filter: %d/%d listings kept", len(listings), before)
    finally:
        if owns_session:
            session.close()

    rows = [flatten_listing(item) for item in listings]
    rows.sort(key=lambda r: (r.get("price") in (None, ""), r.get("price")))

    return ScrapeResult(
        query=query,
        locale=locale,
        category=category,
        total_elements=total_elements,
        listings=listings,
        rows=rows,
    )


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug or "query"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scrape ricardo.ch listings for a free-text search query.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("query", help="Free-text search term, e.g. 'laptop' or 'iphone 13'")
    parser.add_argument(
        "--locale", default=DEFAULT_LOCALE, choices=["de", "fr", "it"], help="Ricardo locale (default: de)"
    )
    parser.add_argument(
        "--category",
        default=None,
        help="Ricardo category id, e.g. '39272'. Matched client-side against each listing's "
        "category breadcrumbs; requires detail mode (incompatible with --no-detail).",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output file base name (without extension). Defaults to a slugified version of the query.",
    )
    parser.add_argument(
        "--no-detail",
        action="store_true",
        help="Skip visiting each listing's own page; keep only the summary fields "
        "from search results (faster, fewer fields).",
    )
    parser.add_argument("--delay", type=float, default=1.5, help="Delay in seconds between requests.")
    parser.add_argument("--max-results", type=int, default=None, help="Cap on how many listings to collect.")
    parser.add_argument("--price-from", type=float, default=None, help="Minimum price in CHF (inclusive).")
    parser.add_argument("--price-to", type=float, default=None, help="Maximum price in CHF (inclusive).")
    parser.add_argument(
        "--show-browser", action="store_true", help="Show the browser window instead of running headless (debugging)."
    )
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "-v", "--verbose", action="store_true", help="Show debug-level detail, including every navigation made."
    )
    verbosity.add_argument(
        "-q", "--quiet", action="store_true", help="Suppress progress output; only warnings/errors are shown."
    )
    return parser


def _configure_cli_logging(*, verbose: bool, quiet: bool) -> None:
    """Set up console logging for CLI use: progress (INFO, or DEBUG with -v)
    goes to stdout, warnings/errors (-q still shows these) go to stderr.
    Only main() calls this - plain library use of scrape() never touches
    logging config, since that would be rude to whatever application
    imported it."""
    level = logging.DEBUG if verbose else logging.WARNING if quiet else logging.INFO
    plain = logging.Formatter("%(message)s")

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(level)
    stdout_handler.addFilter(lambda record: record.levelno < logging.WARNING)
    stdout_handler.setFormatter(plain)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.setFormatter(plain)

    logger.handlers.clear()
    logger.addHandler(stdout_handler)
    logger.addHandler(stderr_handler)
    logger.setLevel(level)
    logger.propagate = False


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Parses argv (defaults to sys.argv[1:]), scrapes, and
    writes CSV + JSON files. Returns 0 on success; lets exceptions propagate
    (see run_cli() for the error-handling / exit-code wrapper used by the
    __main__ guard below)."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    _configure_cli_logging(verbose=args.verbose, quiet=args.quiet)

    result = scrape(
        args.query,
        locale=args.locale,
        category=args.category,
        detail=not args.no_detail,
        price_from=args.price_from,
        price_to=args.price_to,
        delay=args.delay,
        max_results=args.max_results,
        verbose=True,
        headless=not args.show_browser,
    )

    out_base = args.out or _slugify(result.query)
    csv_path = f"{out_base}.csv"
    json_path = f"{out_base}.json"
    result.to_csv(csv_path)
    result.to_json(json_path)

    logger.info("\nDone. %d unique listings found.", len(result.rows))
    logger.info("  CSV:  %s", csv_path)
    logger.info("  JSON: %s", json_path)
    return 0


def run_cli(argv: list[str] | None = None) -> int:
    """Run main() and translate exceptions into (message, exit code) the way
    the command line expects. Factored out from the __main__ guard so it can
    be unit-tested directly without spawning a subprocess."""
    try:
        return main(argv) or 0
    except ValueError as exc:
        logger.error("Error: %s", exc)
        return 1
    except PlaywrightError as exc:
        logger.error("Browser/navigation error talking to ricardo.ch: %s", exc)
        return 1
    except KeyboardInterrupt:
        logger.error("\nInterrupted.")
        return 130


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess in test_e2e.py
    sys.exit(run_cli())
