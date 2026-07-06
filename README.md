# Ricardo.ch Scraper

> Unofficial, independently developed project. Not affiliated with,
> endorsed by, or sponsored by Ricardo AG. "Ricardo" is a trademark of its
> respective owner.

Fetches full listing details matching a free-text search query from
[ricardo.ch](https://www.ricardo.ch) -- Switzerland's largest general
marketplace -- and outputs them as JSON. Ricardo sells everything (laptops,
phones, furniture, ...), so this is built around a free-text search, not a
fixed taxonomy; "laptop" is used as the running example throughout this
README, but nothing about the code is category-specific.

## How it works

ricardo.ch is a Next.js app sitting behind Cloudflare. Each listing's own
page renders a standard `schema.org` `Product` JSON-LD block server-side
(`<script id="pdp-json-ld">`) for SEO -- name, description, price,
condition, seller, brand, category breadcrumbs, and full-resolution images,
all in one place. So rather than scraping visible DOM text, this scraper
walks the search-results pages to collect listing URLs, then visits each
listing and parses that one embedded JSON block straight out of the
rendered HTML -- no separate detail mode, every listing already gets the
full record.

1. **Search**: walks `ricardo.ch/de/s/<query>?page=N`, extracting listing
   URLs from `[data-testid="regular-results"] a[href^="/de/a/"]` until a
   page returns zero results.
2. **Detail**: visits each listing URL and parses its `pdp-json-ld` block
   for the full listing record.

**De-duplication.** Like other marketplaces, Ricardo can pin a "boosted"
listing into the first slot of every search page, which would otherwise
make it reappear across pages. The search pass de-duplicates by listing URL
as it paginates, so this is handled automatically.

### Cloudflare

ricardo.ch's search and listing pages sit behind a Cloudflare Managed
Challenge -- a JS-execution/fingerprinting check, not the older
five-second `jschl` challenge. A plain HTTP client (`requests`,
`cloudscraper`, etc.) cannot solve it; it genuinely requires a real browser.

This project uses [`camoufox`](https://github.com/daijro/camoufox) -- a
fingerprint-patched Firefox build driven through
[Playwright](https://playwright.dev/) -- to render real pages and pass the
challenge like a normal browser would. `scraper.py` runs it headless with
`humanize=True` (synthetic, human-like cursor movement) and retries through
Cloudflare's occasional mid-navigation challenge redirect (`goto_with_retry`
in `scraper.py`).

One sharp edge worth knowing about: camoufox's own installer (`camoufox
fetch`) resolves "latest" using a version check that happens to skip every
current browser release and fall back to a ~1.5-year-old build with a bug
that crashes on ricardo.ch's pages. This project pins a specific, verified
browser build instead and reinstalls it automatically if it's ever missing
or wrong -- see [Setup](#setup) and `pin_camoufox_browser.py`'s docstring
for the full story.

If you hit persistent challenges, wait a few minutes before retrying --
repeated rapid attempts from the same IP appear to raise Cloudflare's risk
score, and a cooldown reliably clears it.

## Setup

Dependencies are managed with [pipenv](https://pipenv.pypa.io/).

```bash
pipenv install
```

That's it -- `scraper.py` calls `ensure_pinned_browser()` itself at the
start of every run, which checks the cached Firefox build against a known
tested version and (re)installs it if it's missing or wrong. You don't
need to run anything else, and it won't re-download once the pin is
already in place (adds well under a second to startup).

**Never run `camoufox fetch`** (camoufox's own installer). It picks the
newest release its installed pip package considers "supported", but that
check compares release labels as plain strings (`"alpha" < "beta"`), so it
skips every current `alpha.N` release and falls back to a ~1.5-year-old
`beta`-labeled build (`v135.0.1-beta.24`). That build crashes the Playwright
Node driver on any page with an uncaught JS error missing a `location`
field -- which ricardo.ch's frontend triggers, reproducible with a bare
`page.goto(...)`, nothing scraper-specific. If you (or a stray
`camoufox fetch`) ever clobber the cache with that build, just run
`pipenv run python scraper.py ...` again (or `pipenv run python
pin_camoufox_browser.py --force`) and it self-heals back to the pinned one.

Two things intentionally pinned in the `Pipfile` so this stays reproducible
-- don't `pipenv update` them without re-verifying against ricardo.ch first:
- `camoufox==0.4.11` -- a newer pip package could change the version-range
  logic that `pin_camoufox_browser.py`'s `RELEASE` label ("zeta.1") is
  crafted to satisfy (see that script's docstring).
- `playwright==1.60.0` -- 1.61.0+ speaks a browser protocol the pinned
  Firefox build doesn't support (`Browser.setDefaultViewport` error).

If you deliberately want to move to a newer camoufox browser build, update
`VERSION`/`RELEASE`/`ASSET_URLS` in `pin_camoufox_browser.py` together, and
verify it against ricardo.ch before trusting it.

## Usage

```bash
pipenv run python scraper.py "laptop" -o results.json
```

### Options

| Flag | Description |
|---|---|
| `query` | Free-text search term, e.g. `"laptop"` or `"iphone 13"` (required, positional) |
| `-o` / `--output` | Output JSON file. Defaults to printing to stdout |
| `-n` / `--max-results` | How many listings to fetch (default `50`) |
| `--page-delay` | Seconds between search-page requests (default `1.5`) |
| `--detail-delay` | Seconds between listing-detail requests (default `1.0`) |
| `--show-browser` | Show the browser window instead of running headless -- for debugging a future Cloudflare or site-structure change |

### Examples

```bash
# 50 laptop listings (the default), printed to stdout
pipenv run python scraper.py "laptop"

# 200 results, written to a file
pipenv run python scraper.py "laptop" -n 200 -o laptops.json

# Any query works -- not just electronics
pipenv run python scraper.py "iphone 13 pro max"

# Watch it run in a visible browser window, fewer results, for debugging
pipenv run python scraper.py "laptop" -n 3 --show-browser

# Slower and more polite, e.g. if you're getting rate-limited
pipenv run python scraper.py "laptop" --page-delay 3 --detail-delay 2
```

## Data structure

The output is a JSON array of listing objects, one per matching listing,
each with:

| Field | Type | Description |
|---|---|---|
| `id` | `string` | Ricardo's internal listing id (`sku` in the source JSON-LD) |
| `title` | `string` | Listing title |
| `description` | `string` | Full listing description |
| `url` | `string` | Canonical listing URL |
| `price` | `number \| null` | Price in `currency` |
| `currency` | `string` | e.g. `"CHF"` |
| `condition` | `string \| null` | e.g. `"NewCondition"`, `"UsedCondition"`, `"DamagedCondition"` (schema.org `itemCondition`, suffix only) |
| `availability` | `string \| null` | e.g. `"InStock"` (schema.org `availability`, suffix only) |
| `availability_ends` | `string \| null` | ISO 8601 timestamp -- auction/listing end time |
| `seller_name` | `string \| null` | Seller's Ricardo username |
| `seller_url` | `string \| null` | Seller's shop/offers page |
| `brand` | `string \| null` | Free-form brand name, when Ricardo has one for the category |
| `categories` | `list[string]` | Category breadcrumb slugs, e.g. `["notebooks-39272", "computer-netzwerk-39091", "de"]` |
| `images` | `list[string]` | Full-resolution image URLs |

There is no fixed/versioned schema published by Ricardo for this JSON-LD
block -- the table above reflects fields observed in practice as of this
writing. Treat unknown/missing fields defensively (`.get(...)`), and expect
this to need a small update if Ricardo changes what it renders.

## Notes

- Be a reasonable citizen: the default delays between requests, and reusing
  one browser session for a whole scrape run, are both intentional -- this
  renders real pages through a real browser, not a lightweight API call;
  don't crank up concurrency.
- If ricardo.ch changes its page structure, `SEARCH_RESULTS_JS` (the search
  results selector) and `extract_product_jsonld`/`normalize_listing` (the
  detail-page parsing) in `scraper.py` are the places to look.
