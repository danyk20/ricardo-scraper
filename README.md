# Ricardo.ch Scraper

[![CI](https://github.com/danyk20/ricardo-scraper/actions/workflows/ci.yml/badge.svg)](https://github.com/danyk20/ricardo-scraper/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11 | 3.12](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)](https://www.python.org/)

> Unofficial, independently developed project. Not affiliated with,
> endorsed by, or sponsored by Ricardo AG. "Ricardo" is a trademark of its
> respective owner.

Fetches every listing matching a search query from
[ricardo.ch](https://www.ricardo.ch) -- Switzerland's largest general
marketplace -- for free, no API key, no token. Unlike a structured vehicle
site, Ricardo sells everything (laptops, phones, furniture, ...), so this
scraper is built around a free-text search, not a fixed taxonomy; "laptop"
is used as the running example throughout this README, but nothing about
the code is category-specific.

**🤖 This project is robot-friendly.** It is explicitly intended to be used
by AI agents and bots exactly as a human developer would: to run it, read
its output, import it into another project, or adapt its code. It's
released under the very permissive [MIT license](LICENSE) specifically so
there is no ambiguity about that -- see [License](#license) below.

This project is modeled directly on
[`danyk20/autoscout24-scraper`](https://github.com/danyk20/autoscout24-scraper)
(same repo shape, same library-and-CLI dual usage, same `ScrapeResult`/CSV/
JSON contract) so that code written against one can swap to the other with
minimal changes -- read that project's README for the sibling story of
scraping a *different* Swiss marketplace that turned out to have a much
easier path (a public, un-protected JSON API). Ricardo did not have that
option; see [How it works](#how-it-works) below for what it took instead,
and see that project's `scrape()`/`ScrapeResult` reference alongside this
one's [Usage](#usage) section for exactly where the two interfaces line up
and where they inherently differ (a general marketplace has no
make/model/mileage/year to filter on).

## How it works

ricardo.ch is a Next.js app sitting behind a Cloudflare Managed Challenge --
a JS-execution/fingerprinting check that a plain HTTP client (`requests`,
`cloudscraper`, etc.) cannot solve, and there is no separate, unauthenticated
JSON API the way `api.autoscout24.ch` is for AutoScout24. So instead of
talking to an API, this scraper drives a real, fingerprint-patched Firefox
via [`camoufox`](https://github.com/daijro/camoufox) -- a drop-in
[Playwright](https://playwright.dev/) browser build patched against the
CDP-level fingerprints Cloudflare's challenge platform uses to detect plain
automation -- which passes the challenge like a normal browser. This runs
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
   each listing's own page and parses its embedded schema.org `Product`
   JSON-LD block (`<script id="pdp-json-ld">`, rendered server-side for
   SEO) for the full record -- description, condition, seller, brand,
   category breadcrumbs, full-resolution images.

### Detail mode

The search-results page alone already carries id, title, price, and a
thumbnail -- that's what `detail=False` (`--no-detail` on the CLI) returns:
fast, no per-listing browser navigation. `detail=True` (the default)
additionally visits every listing's own page for the full record described
above. Unlike AutoScout24's detail fetch (a second HTTP call against a
reliable JSON API), this one drives an actual browser navigation per
listing, so it's the slower, heavier path -- reach for `--no-detail` when
you only need the summary fields for many listings quickly.

One consequence: **`category` filtering requires `detail=True`** --
category breadcrumbs only exist in the JSON-LD block, not the search
summary -- `scrape(..., category=..., detail=False)` raises `ValueError`
immediately rather than silently ignoring the filter.

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
  browser, which installs a specific, verified-working build instead --
  see that module's docstring for the full story. You never need to run
  `camoufox fetch` yourself, and shouldn't -- it would reintroduce the bug.

If you hit persistent challenges, wait a few minutes before retrying --
repeated rapid attempts from the same IP appear to raise Cloudflare's risk
score, and a cooldown reliably clears it.

## Locale

Every function and the CLI accept a `locale` (default `"de"`), matching
`ricardo.ch/<locale>/s/...` and `/<locale>/a/...`. `"de"`, `"fr"`, and
`"it"` are Ricardo's three real site locales -- unlike AutoScout24's
`domain` (which selects an entirely different country's site, and mostly
isn't confirmed to work), Ricardo's locales are the same Swiss marketplace
and inventory, just presented in a different language. Price/category
filtering logic doesn't depend on locale-specific text (see
`SEARCH_SUMMARY_JS`'s comment in `ricardo_scraper.py` for how the price
extraction stays locale-agnostic), so all three are expected to work
equally well.

## Setup

Dependencies are managed with [pipenv](https://pipenv.pypa.io/).

```bash
pipenv install --dev
```

(`--dev` also installs the test/lint tooling -- pytest, pytest-cov, ruff,
mypy. Leave it off if you only want to run the scraper.)

That's it for the browser -- `scrape()` calls `ensure_pinned_browser()`
itself at the start of every run, which checks the cached Firefox build
against a known-good version and (re)installs it if it's missing or wrong.
**Never run `camoufox fetch`** -- see [Cloudflare](#cloudflare) above for
why; if it (or anything else) ever clobbers the cache with a different
build, just run the scraper again and it self-heals back to the pinned one.

```bash
pipenv run ruff check .            # lint
pipenv run ruff format --check .   # formatting (drop --check to auto-format)
pipenv run mypy ricardo_scraper.py # type-check
```

These are exactly the checks the CI workflow (`.github/workflows/ci.yml`)
runs on every push/PR, across Python 3.11 and 3.12.

## Usage

The scraper works two ways: as a standalone CLI script that writes files,
or as a library you import into another project to get the data back
directly.

### As a CLI script

```bash
pipenv run python ricardo_scraper.py "laptop"
```

(If you installed the package via `pip install` instead, the same command
is just `ricardo-scraper "laptop"` -- no `pipenv run` needed.)

This prints progress per search page, then visits every matching listing
one by one to pull full details, and writes two output files in the
current directory: `laptop.csv` and `laptop.json`.

### Options

| Flag | Description |
|---|---|
| `--version` | Print the installed version and exit |
| `query` | Free-text search term, e.g. `"laptop"` or `"iphone 13"` (required, positional) |
| `--locale` | Ricardo locale (`de`/`fr`/`it`), default `de` -- see [Locale](#locale) |
| `--category` | Ricardo category id, e.g. `39272`. Client-side filter -- see [Detail mode](#detail-mode) |
| `--out` | Output file base name, without extension. Defaults to a slugified version of the query |
| `--no-detail` | Skip visiting each listing's own page; keep only the summary fields -- see [Detail mode](#detail-mode) |
| `--price-from` / `--price-to` | Filter by price in CHF (inclusive, either end optional). Client-side -- see [Data structure](#data-structure) |
| `--max-results` | Cap on how many listings to collect |
| `--delay` | Seconds between requests (default `1.5`) -- raise this if you get rate-limited |
| `--show-browser` | Show the browser window instead of running fully headless (default: no window at all) -- see [Cloudflare](#cloudflare) |
| `-v` / `--verbose` | Also show debug-level detail |
| `-q` / `--quiet` | Suppress progress output; only warnings/errors are shown (mutually exclusive with `-v`) |

### Examples

```bash
# Full run: every laptop listing, full detail (default)
pipenv run python ricardo_scraper.py "laptop"

# Any query works -- not just electronics
pipenv run python ricardo_scraper.py "iphone 13 pro max"

# Custom output filename
pipenv run python ricardo_scraper.py "laptop" --out my_search

# Only laptops under CHF 500
pipenv run python ricardo_scraper.py "laptop" --price-to 500

# Fast mode: search summary only, skip visiting each listing
pipenv run python ricardo_scraper.py "laptop" --no-detail

# French-language site
pipenv run python ricardo_scraper.py "ordinateur portable" --locale fr
```

### As a library, from another project

Import `scrape()` and call it directly -- it does the same work as the CLI
but returns a `ScrapeResult` object instead of writing files. No files are
written unless you explicitly ask for them.

```python
from ricardo_scraper import scrape

result = scrape("laptop", price_to=500)

result.rows       # list[dict]: one flattened dict per listing, CSV-ready
result.listings   # list[dict]: raw (unflattened) per-listing records, each with a "url" field
result.query, result.locale, result.category, result.total_elements

for row in result.rows:
    print(row["title"], row.get("price"), row["url"])

# Optional: write to disk anyway, e.g. for a one-off export
result.to_csv("laptops.csv")
result.to_json("laptops.json")
```

Install it into your own project's environment with:

```bash
pip install git+https://github.com/danyk20/ricardo-scraper.git
```

(Not yet published to PyPI.)

#### `scrape()` signature

```python
def scrape(
    query: str,                        # e.g. "laptop" or "iphone 13" -- required
    *,
    locale: str = "de",                # "de" / "fr" / "it"
    category: str | None = None,       # optional Ricardo category id; requires detail=True
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
required page after retrying, or on other navigation failures -- the
direct analog of `requests.RequestException` in AutoScout24's interface,
for a browser-driven transport instead of an HTTP one.

**Logging.** Library code never configures logging itself (no
`basicConfig`, no handlers) -- it only emits through
`logging.getLogger("ricardo_scraper")`, same as any well-behaved library.
To see progress when calling `scrape()` from your own script:

```python
import logging
logging.basicConfig(level=logging.INFO)
```

The CLI is the one place that *does* configure real handlers automatically
(via `-v`/`-q`) -- that's the only difference between running this as a
script versus importing it.

**Reusing a browser session.** `session` is the analog of AutoScout24's
`requests.Session` reuse -- same purpose (avoid the overhead of tearing
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

#### `ScrapeResult` -- the return value

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
filtering -- `len(result.listings)` reflects the post-filter count.

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

**Detail shape** (`detail=True`, the default) -- everything above except
`image`, plus:

| Field | Type | Description |
|---|---|---|
| `description` | `string` | Full listing description |
| `currency` | `string` | e.g. `"CHF"` |
| `condition` | `string \| null` | e.g. `"NewCondition"`, `"UsedCondition"`, `"DamagedCondition"` (schema.org `itemCondition`, suffix only) |
| `availability` | `string \| null` | e.g. `"InStock"` (schema.org `availability`, suffix only) |
| `availability_ends` | `string \| null` | ISO 8601 timestamp -- auction/listing end time |
| `seller_name` | `string \| null` | Seller's Ricardo username |
| `seller_url` | `string \| null` | Seller's shop/offers page |
| `brand` | `string \| null` | Free-form brand name, when Ricardo has one for the category |
| `categories` | `list[string]` | Category breadcrumb slugs, e.g. `["notebooks-39272", "computer-netzwerk-39091", "de"]` |
| `images` | `list[string]` | Full-resolution image URLs |

There is no fixed/versioned schema published by Ricardo for either shape --
the tables above reflect fields observed in practice as of this writing.
Treat unknown/missing fields defensively (`.get(...)`, not `[...]`).

### CSV (`result.rows` / the `.csv` file)

A **flattened** version of the same data -- one row per listing, same
rows/listings correspondence and order (sorted by price ascending).
Flattening rules (also available programmatically as `flatten_listing()`):

- Lists are joined into one semicolon-separated cell, e.g. `categories` →
  `"notebooks-39272; computer-netzwerk-39091; de"`.
- Nested objects (none in the current shape, but handled generically)
  become `parent_child` columns.
- Columns are the union of every field seen across all rows (heterogeneous
  rows -- e.g. mixing summary- and detail-shape listings -- don't crash the
  writer; missing values are an empty string), with `id, title, price,
  currency, condition, brand, seller_name, categories, url` pinned first
  and everything else sorted alphabetically after them.

## Testing

The test suite lives in `tests/` and is split into two kinds of tests:

- **Unit tests** (`tests/test_*.py`, excluding `test_e2e.py`) -- the
  browser layer is fully mocked via `FakeBrowserSession` (implements the
  same `goto()`/`evaluate()` interface `BrowserSession` does, returning
  canned search/detail payloads instead of driving a real browser), so
  they run in well under a second, need no network access, and never touch
  the real site or download the camoufox browser binary. This is the
  default `pytest` run, gated at 100% coverage of `ricardo_scraper.py`
  (`--cov-fail-under=95` in `pyproject.toml`; the two lines excluded via
  `# pragma: no cover` are a defensive "all retries exhausted" fallback in
  the Cloudflare-retry loop, and the `if __name__ == "__main__":` guard
  itself, exercised for real by the e2e suite's CLI subprocess tests
  instead).
- **End-to-end tests** (`tests/test_e2e.py`) -- make real calls against
  ricardo.ch, through a real camoufox browser. They're marked
  `@pytest.mark.e2e` and excluded by default; run them explicitly when you
  want to confirm the scraper still works against the live site. A small
  `max_results` (rather than a small-inventory query, the trick
  AutoScout24's e2e suite uses) keeps these fast regardless of how many
  listings actually match on any given day. Expect occasional failures
  unrelated to a real regression -- see [Cloudflare](#cloudflare) -- rerun
  after a cooldown rather than assuming the code broke.

```bash
# Unit tests only (fast, no network) -- this is what `pytest` runs by default.
pipenv run pytest

# End-to-end tests only (real network calls, real browser, slower)
pipenv run pytest -m e2e --no-cov

# HTML coverage report you can open in a browser
pipenv run pytest --cov-report=html && open htmlcov/index.html
```

## Notes

- Be a reasonable citizen: the default delay between requests, and reusing
  one browser session for a whole scrape run, are both intentional -- this
  renders real pages through a real browser, not a lightweight API call;
  don't crank up concurrency.
- `price_from`/`price_to`/`category` are **client-side** filters, not real
  server-side ones -- verified by comparing ricardo.ch's own result price
  ranges with and without `price_from`/`price_to` query params (identical
  either way). Ricardo's real filter mechanism (`range_filters`,
  `attribute_groups.*` per its `robots.txt`) is a serialized, per-category
  facet system not reverse-engineered here. This is the one place this
  project's interface deviates from AutoScout24's (whose price/mileage/year
  filters are real server-side ones, cutting down what the detail phase
  even has to visit) -- documented here rather than silently different.
- If ricardo.ch changes its page structure, `SEARCH_SUMMARY_JS` (the search
  results selector) and `extract_product_jsonld`/`_listing_from_product`
  (the detail-page parsing) in `ricardo_scraper.py` are the places to look.

## License

This project is released under the [MIT License](LICENSE) -- one of the
most permissive open-source licenses that exist. In plain terms: you can
use, copy, modify, merge, publish, distribute, and even sell copies of this
code, for free, for any purpose, commercial or not, as long as the license
text stays attached. There is no warranty.

**AI agents, LLM-based coding assistants, and other bots are explicitly
welcome to use this project** -- to run the scraper, to read and parse its
output, to import `scrape()` into another project, or to read and adapt
its source code -- under exactly the same terms as a human would, with no
additional restriction and no need to ask permission.

The one thing this permissive license does *not* do is grant any rights to
Ricardo's own data or terms of service -- this project only automates
requests to publicly viewable pages any visitor's browser can already load;
what you do with the results is between you and them.
