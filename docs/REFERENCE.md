# Reference

Full API surface, return types, and data schema for anyone integrating with
this project as a library — a human developer or an AI agent — without
reading the source. See [README.md](../README.md) for the pitch, install,
and CLI usage.

## How it works

ricardo.ch is a Next.js app sitting behind a Cloudflare Managed Challenge —
a JS-execution/fingerprinting check that a plain HTTP client (`requests`,
`cloudscraper`, etc.) cannot solve, and there is no separate, unauthenticated
JSON API the way `api.autoscout24.ch` is for AutoScout24. So instead of
talking to an API, this scraper drives a real, fingerprint-patched Firefox
via [`camoufox`](https://github.com/daijro/camoufox) — a drop-in
[Playwright](https://playwright.dev/) browser build patched against the
CDP-level fingerprints Cloudflare's challenge platform uses to detect plain
automation — which passes the challenge like a normal browser. This runs
fully headless by default (`--show-browser` shows the window, for
debugging a future Cloudflare or site-structure change).

Two-phase scraping, mirroring AutoScout24's search-then-detail split:

1. **Search** (`search_listings()`): walks `ricardo.ch/<locale>/s/<query>?page=N`,
   extracting a summary per listing (id, title, url, price, thumbnail) from
   the search-results page DOM, paginating until a page returns zero
   results. Ricardo can pin a "boosted" listing into the first slot of
   every page, which would otherwise make it reappear across pages;
   de-duplicating by id as it paginates handles this automatically.
2. **Detail** (`visit_all_listings()`, the `detail=True` default): visits
   each listing's own page and parses two things out of the same page load:
   its embedded schema.org `Product` JSON-LD block (`<script
   id="pdp-json-ld">`, rendered server-side for SEO) for description,
   condition, seller, brand, category breadcrumbs, and full-resolution
   images; and its `#__NEXT_DATA__` blob (Next.js's own server-rendered
   props — a single JSON script tag, not the SEO data) for fields Ricardo
   doesn't put in the JSON-LD: the listing's location (city/zip), the
   seller's rating, structured delivery options, and questions & answers.

### Detail mode

The search-results page alone already carries id, title, price, and a
thumbnail — that's what `detail=False` (`--no-detail` on the CLI) returns:
fast, no per-listing browser navigation. `detail=True` (the default)
additionally visits every listing's own page for the full record described
above. Unlike AutoScout24's detail fetch (a second HTTP call against a
reliable JSON API), this one drives an actual browser navigation per
listing, so it's the slower, heavier path — reach for `--no-detail` when
you only need the summary fields for many listings quickly.

One consequence: **`category` filtering requires `detail=True`** —
category breadcrumbs only exist in the JSON-LD block, not the search
summary — `scrape(..., category=..., detail=False)` raises `ValueError`
immediately rather than silently ignoring the filter.

`category` matches against each listing's breadcrumb slugs (e.g.
`"notebooks-39272"`), and accepts either Ricardo's numeric category id
(`"39272"`) or a case-insensitive name (`"notebooks"`, `"Notebooks"`, or a
multi-word slug like `"computer-netzwerk"`) — Ricardo's JSON-LD doesn't
expose a separate human-readable category name, only the slug, so the name
match works off the slug's non-numeric part (`_category_matches()` in
`ricardo_scraper.py`).

### Cloudflare

Getting `camoufox` to reliably render ricardo.ch pages took two fixes
beyond a plain `Camoufox()` launch, both baked into this project rather
than left for a caller to discover:

- **Challenge-redirect races.** Cloudflare occasionally kicks off a second
  (challenge-solving) navigation while the first is still in flight, and/or
  the challenge is still resolving after a navigation call returns, leaving
  the page on an interstitial state for a few seconds (observed titles:
  `"Loading..."`, `"Just a moment..."`). `BrowserSession.goto()` retries
  through the first and polls the page title past any known interstitial
  before treating a page as ready.
- **A pinned, verified browser build.** camoufox's own installer
  (`camoufox fetch`) resolves "latest" using a version-support check that
  happens to skip every current browser release and fall back to a
  ~1.5-year-old build with a real bug: it crashes on any ricardo.ch page
  with an uncaught JS error missing a `location` field. `scrape()` calls
  `pin_camoufox_browser.ensure_pinned_browser()` itself before launching a
  browser, which installs a specific, verified-working build instead —
  see that module's docstring for the full story. You never need to run
  `camoufox fetch` yourself, and shouldn't — it would reintroduce the bug.

If you hit persistent challenges, wait a few minutes before retrying —
repeated rapid attempts from the same IP appear to raise Cloudflare's risk
score, and a cooldown reliably clears it.

## Locale

Every function and the CLI accept a `locale` (default `"de"`), matching
`ricardo.ch/<locale>/s/...` and `/<locale>/a/...`. `"de"`, `"fr"`, and
`"it"` are Ricardo's three real site locales — unlike AutoScout24's
`domain` (which selects an entirely different country's site, and mostly
isn't confirmed to work), Ricardo's locales are the same Swiss marketplace
and inventory, just presented in a different language. Price/category
filtering logic doesn't depend on locale-specific text (see
`SEARCH_SUMMARY_JS`'s comment in `ricardo_scraper.py` for how the price
extraction stays locale-agnostic), so all three are expected to work
equally well.

## `scrape()` signature

```python
def scrape(
    query: str,                        # e.g. "laptop" or "iphone 13" -- required
    *,
    locale: str = "de",                # "de" / "fr" / "it"
    category: str | None = None,       # optional Ricardo category id or name; requires detail=True
    detail: bool = True,                # visit every listing individually for full fields (slower)
    price_from: float | None = None,   # CHF, inclusive, filtered client-side
    price_to: float | None = None,     # CHF, inclusive, filtered client-side
    delay: float = 1.5,                # seconds between requests
    max_results: int | None = None,    # optional cap on listings collected
    verbose: bool = True,              # emit progress via the "ricardo_scraper" logger
    headless: bool = True,             # no window at all by default -- see Cloudflare section
    session: BrowserSession | None = None,  # reuse a browser session across calls if given
) -> ScrapeResult: ...
```

Raises `ValueError` immediately (before launching a browser) if `price_from
> price_to`, or if `category` is given with `detail=False`. Raises
`playwright.sync_api.Error` if Cloudflare's challenge never clears for a
required page after retrying, or on other navigation failures — the
direct analog of `requests.RequestException` in AutoScout24's interface,
for a browser-driven transport instead of an HTTP one.

**Logging.** Library code never configures logging itself (no
`basicConfig`, no handlers) — it only emits through
`logging.getLogger("ricardo_scraper")`, same as any well-behaved library.
To see progress when calling `scrape()` from your own script:

```python
import logging
logging.basicConfig(level=logging.INFO)
```

The CLI is the one place that *does* configure real handlers automatically
(via `-v`/`-q`) — that's the only difference between running this as a
script versus importing it.

**Reusing a browser session.** `session` is the analog of AutoScout24's
`requests.Session` reuse — same purpose (avoid the overhead of tearing
down and relaunching per call), different concrete type since this scrapes
through a real browser rather than an HTTP client:

```python
from ricardo_scraper import BrowserSession, scrape

with BrowserSession() as session:
    laptops = scrape("laptop", session=session)
    phones = scrape("iphone 13", session=session)
# session closes here; a scrape() call that creates its own session (the
# common case, when session=None) closes it automatically instead.
```

## `ScrapeResult` — the return value

```python
@dataclass
class ScrapeResult:
    query: str               # the query that was searched
    locale: str
    category: str | None     # the category filter used, if any
    total_elements: int      # number of unique listings found by the search phase
    listings: list[dict]     # raw per-listing records -- see "Data structure" below
    rows: list[dict]         # flattened dicts, one per listing, CSV-ready, sorted by price ascending

    def to_csv(self, path: str) -> None: ...   # writes self.rows
    def to_json(self, path: str) -> None: ...  # writes self.listings
```

`len(result.rows) == len(result.listings)` always holds. `total_elements`
counts every listing the search phase found *before* any price/category
filtering — `len(result.listings)` reflects the post-filter count.

## Data structure

### JSON (`result.listings` / the `.json` file)

A JSON array of listing objects, one per matching listing. The shape
depends on whether detail mode ran (see [Detail mode](#detail-mode)):

**Summary shape** (`detail=False` / `--no-detail`):

| Field | Type | Description |
|---|---|---|
| `id` | `string` | Ricardo's internal listing id |
| `title` | `string` | Listing title |
| `url` | `string` | Canonical listing URL |
| `price` | `number \| null` | The buy-now/fixed price, or `null` if none was rendered |
| `image` | `string` | Thumbnail URL |

**Detail shape** (`detail=True`, the default) — everything above except
`image`, plus:

| Field | Type | Description |
|---|---|---|
| `description` | `string` | Full listing description |
| `currency` | `string` | e.g. `"CHF"` |
| `condition` | `string \| null` | e.g. `"NewCondition"`, `"UsedCondition"`, `"DamagedCondition"` (schema.org `itemCondition`, suffix only) |
| `availability` | `string \| null` | e.g. `"InStock"` (schema.org `availability`, suffix only) |
| `availability_ends` | `string \| null` | ISO 8601 timestamp — auction/listing end time |
| `seller_name` | `string \| null` | Seller's Ricardo username |
| `seller_url` | `string \| null` | Seller's shop/offers page |
| `brand` | `string \| null` | Free-form brand name, when Ricardo has one for the category |
| `categories` | `list[string]` | Category breadcrumb slugs, e.g. `["notebooks-39272", "computer-netzwerk-39091", "de"]` |
| `images` | `list[string]` | Full-resolution image URLs |
| `location_city` | `string \| null` | Listing's town/village, e.g. `"Biberist"` |
| `location_zip` | `string \| null` | Listing's postal code, e.g. `"4562"` |
| `seller_rating_score` | `number \| null` | Seller's positive-rating percentage (0-100), e.g. `98.94`. `null` if the seller has zero ratings yet (not `0`) |
| `seller_ratings_count` | `int \| null` | Number of ratings the percentage above is based on |
| `delivery_options` | `list[object]` | One entry per shipping/pickup option: `{"id": string, "price": number, "cumulative": bool}` — `price` in CHF (converted from the raw Rappen/cents value), `id` e.g. `"parcel_b_2kg"`/`"get_by_buyer"` |
| `questions_and_answers` | `list[object]` | One entry per public Q&A thread on the listing: `{"question": string, "question_date": string, "answer": string \| null, "answer_date": string \| null}` — `answer`/`answer_date` are `null` for an unanswered question |

Location/seller-rating/delivery/Q&A come from a different source than the
rest of the detail shape (the page's `#__NEXT_DATA__` blob, not the JSON-LD
block — see [How it works](#how-it-works)) and degrade independently: a
listing missing this data (e.g. a genuinely different page shape) still
gets included with these fields left at their defaults (`null`/`[]`) rather
than being dropped, since the JSON-LD-derived fields are the ones that
actually make a record usable.

There is no fixed/versioned schema published by Ricardo for either shape —
the tables above reflect fields observed in practice as of this writing.
Treat unknown/missing fields defensively (`.get(...)`, not `[...]`).

### CSV (`result.rows` / the `.csv` file)

A **flattened** version of the same data — one row per listing, same
rows/listings correspondence and order (sorted by price ascending).
Flattening rules (also available programmatically as `flatten_listing()`):

- Lists are joined into one semicolon-separated cell, e.g. `categories` →
  `"notebooks-39272; computer-netzwerk-39091; de"`; a list of objects (like
  `delivery_options`/`questions_and_answers`) becomes one JSON-per-entry
  cell joined the same way, e.g. `{"id": "get_by_buyer", "price": 0.0,
  "cumulative": false}; {"id": "parcel_b_2kg", "price": 9.0, "cumulative":
  false}`.
- Nested objects become `parent_child` columns (no top-level field is
  nested in the current shape, but this is handled generically).
- Columns are the union of every field seen across all rows (heterogeneous
  rows — e.g. mixing summary- and detail-shape listings — don't crash the
  writer; missing values are an empty string), with `id, title, price,
  currency, condition, brand, location_city, location_zip, seller_name,
  seller_rating_score, seller_ratings_count, categories, url` pinned first
  and everything else sorted alphabetically after them.

## Test coverage by area

Unit tests mock the browser layer entirely via `FakeBrowserSession`
(implements the same `goto()`/`evaluate()` interface `BrowserSession`
does, returning canned search/detail payloads instead of driving a real
browser), gated at 100% coverage of `ricardo_scraper.py`
(`--cov-fail-under=95` in `pyproject.toml`; the two lines excluded via
`# pragma: no cover` are a defensive "all retries exhausted" fallback in
the Cloudflare-retry loop, and the `if __name__ == "__main__":` guard
itself, exercised for real by the e2e suite's CLI subprocess tests
instead).

E2E tests make real calls against ricardo.ch through a real camoufox
browser. A small `max_results` (rather than a small-inventory query, the
trick AutoScout24's e2e suite uses) keeps these fast regardless of how many
listings actually match on any given day. Expect occasional failures
unrelated to a real regression — see [How it works](#cloudflare) — rerun
after a cooldown rather than assuming the code broke.

## Notes on filter fidelity

`price_from`/`price_to`/`category` are **client-side** filters, not real
server-side ones — verified by comparing ricardo.ch's own result price
ranges with and without `price_from`/`price_to` query params (identical
either way). Ricardo's real filter mechanism (`range_filters`,
`attribute_groups.*` per its `robots.txt`) is a serialized, per-category
facet system not reverse-engineered here. This is the one place this
project's interface deviates from AutoScout24's (whose price/mileage/year
filters are real server-side ones, cutting down what the detail phase
even has to visit) — documented here rather than silently different.

If ricardo.ch changes its page structure, `SEARCH_SUMMARY_JS` (the search
results selector) and `extract_product_jsonld`/`_listing_from_product`
(the detail-page parsing) in `ricardo_scraper.py` are the places to look.
