# Ricardo Scraper

Scrapes ricardo.ch listings for a search query and outputs JSON with full
listing details (title, description, price, condition, seller, brand,
categories, images).

## Setup

Dependencies are managed with [pipenv](https://pipenv.pypa.io/).

```
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
verify it against ricardo.ch before trusting it (see that script's
docstring for the full explanation).

## Usage

```
pipenv run python scraper.py "laptop" -o results.json
pipenv run python scraper.py "laptop" -n 20 --show-browser   # visible browser, fewer results, for debugging
```

Options:
- `-n / --max-results` -- how many listings to fetch (default 50)
- `-o / --output` -- write JSON to a file instead of stdout
- `--page-delay` / `--detail-delay` -- seconds to wait between requests (be polite, avoid rate limits)
- `--show-browser` -- run with a visible window instead of headless

## How it works

Ricardo's site (`ricardo.ch/de/s/...` and `/de/a/...`) sits behind a modern
Cloudflare Managed Challenge that plain HTTP clients (e.g. `cloudscraper`,
`requests`) cannot solve -- it requires real browser JS execution and
fingerprinting checks. This project instead uses
[camoufox](https://github.com/daijro/camoufox), a fingerprint-patched
Firefox build driven via Playwright, which passes the challenge like a
normal browser.

The scraper works in two passes:

1. **Search**: walks `ricardo.ch/de/s/<query>?page=N`, extracting listing
   URLs from `[data-testid="regular-results"] a[href^="/de/a/"]` until a
   page returns zero results.
2. **Detail**: visits each listing URL and parses the embedded
   `<script id="pdp-json-ld">` block -- a standard schema.org `Product`
   JSON-LD object Ricardo's own frontend renders for SEO -- which contains
   the full listing record (name, description, offers/price/condition,
   seller, brand, category breadcrumbs, and full-resolution images).

Promoted/"Boost" listings may appear pinned at the top of every search page;
duplicate listing URLs are naturally deduplicated during the search pass.
