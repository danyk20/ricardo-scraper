#!/usr/bin/env python3
"""Scrape Ricardo.ch listings for a search query and dump them as JSON.

Ricardo's pages sit behind a Cloudflare Managed Challenge that a plain HTTP
client (e.g. cloudscraper) cannot solve. Instead this drives a real,
fingerprint-patched Firefox via camoufox (github.com/daijro/camoufox), which
passes the challenge like a normal browser.

Two passes:
  1. Search pages (ricardo.ch/de/s/<query>?page=N) are walked to collect
     listing URLs, paginating until a page returns zero results.
  2. Each listing's detail page is visited and its embedded JSON-LD
     `Product` block (schema.org) is parsed for the full listing record --
     title, description, price, condition, seller, category, images, etc.
"""

import argparse
import json
import sys
import time

from camoufox.sync_api import Camoufox
from playwright.sync_api import Error as PlaywrightError

from pin_camoufox_browser import ensure_pinned_browser

BASE_URL = "https://www.ricardo.ch"

SEARCH_RESULTS_JS = (
    "Array.from(document.querySelectorAll("
    "'[data-testid=\"regular-results\"] a[href^=\"/de/a/\"]'"
    ")).map(a => a.href)"
)


def goto_with_retry(page, url, attempts=4, settle_ms=2000):
    """Navigate to url, tolerating Cloudflare's challenge redirect.

    Cloudflare occasionally kicks off a second (challenge-solving) navigation
    while the first is still in flight (surfaced by Playwright as an
    "interrupted by another navigation" error), and/or the challenge is still
    resolving after `goto` returns, leaving the page on an interstitial
    "Loading..." state for a few seconds. Both are transient, so poll for the
    page title to move past "Loading" before treating the page as ready.
    """
    for attempt in range(attempts):
        try:
            page.goto(url, timeout=60000)
        except PlaywrightError as e:
            if attempt < attempts - 1 and "interrupted by another navigation" in str(e):
                page.wait_for_timeout(settle_ms)
                continue
            raise

        for _ in range(10):
            page.wait_for_timeout(settle_ms)
            if not page.title().lower().startswith("loading"):
                return

    return


def collect_listing_urls(page, query, max_results, page_delay):
    urls = []
    seen = set()
    page_num = 1
    while len(urls) < max_results:
        search_url = f"{BASE_URL}/de/s/{query}?page={page_num}"
        goto_with_retry(page, search_url)
        hrefs = page.evaluate(SEARCH_RESULTS_JS)
        if not hrefs:
            break
        new = [h for h in hrefs if h not in seen]
        seen.update(hrefs)
        urls.extend(new)
        page_num += 1
        time.sleep(page_delay)
    return urls[:max_results]


def extract_product_jsonld(page):
    """Pull the schema.org Product node out of the detail page's JSON-LD block."""
    raw = page.evaluate(
        "document.getElementById('pdp-json-ld')?.textContent || null"
    )
    if not raw:
        return None
    data = json.loads(raw)
    for node in data.get("@graph", []):
        if node.get("@type") == "Product":
            return node
    return None


def normalize_listing(product, url):
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
        "currency": offer.get("priceCurrency"),
        "condition": (offer.get("itemCondition") or "").rsplit("/", 1)[-1] or None,
        "availability": (offer.get("availability") or "").rsplit("/", 1)[-1] or None,
        "availability_ends": offer.get("availabilityEnds"),
        "seller_name": seller.get("name"),
        "seller_url": seller.get("url"),
        "brand": brand.get("name"),
        "categories": categories,
        "images": product.get("image", []),
    }


def scrape(query, max_results=100, page_delay=1.5, detail_delay=1.0, headless=True):
    if ensure_pinned_browser():
        print("Installed pinned camoufox browser build.", file=sys.stderr)

    listings = []
    with Camoufox(headless=headless, humanize=True) as browser:
        page = browser.new_page()
        urls = collect_listing_urls(page, query, max_results, page_delay)

        for url in urls:
            goto_with_retry(page, url, settle_ms=2500)
            product = extract_product_jsonld(page)
            if product:
                listings.append(normalize_listing(product, url))
            time.sleep(detail_delay)

    return listings


def main():
    parser = argparse.ArgumentParser(description="Scrape Ricardo.ch listings for a search query")
    parser.add_argument("query", help="Search term, e.g. 'laptop'")
    parser.add_argument("-o", "--output", help="Output JSON file (default: stdout)")
    parser.add_argument("-n", "--max-results", type=int, default=50)
    parser.add_argument("--page-delay", type=float, default=1.5, help="Seconds between search-page requests")
    parser.add_argument("--detail-delay", type=float, default=1.0, help="Seconds between listing-detail requests")
    parser.add_argument("--show-browser", action="store_true", help="Run with a visible browser window (debugging)")
    args = parser.parse_args()

    listings = scrape(
        args.query,
        max_results=args.max_results,
        page_delay=args.page_delay,
        detail_delay=args.detail_delay,
        headless=not args.show_browser,
    )

    output = json.dumps(listings, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Wrote {len(listings)} listing(s) to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
