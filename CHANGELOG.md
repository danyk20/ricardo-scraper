# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-07-06

### Added

- Detail-mode listings now also carry `location_city`/`location_zip`,
  `seller_rating_score`/`seller_ratings_count`, `delivery_options`, and
  `questions_and_answers` -- pulled from the same detail-page load's
  `#__NEXT_DATA__` blob (Next.js's own server-rendered props), alongside
  the existing JSON-LD-derived fields. Missing/unparseable `#__NEXT_DATA__`
  degrades to defaults (`null`/`[]`) rather than dropping the listing,
  since it's supplementary to the JSON-LD record.

## [0.1.0] - 2026-07-06

Initial release.

### Added

- Scraper for ricardo.ch marketplace listings, usable both as a CLI
  (`ricardo-scraper` / `python ricardo_scraper.py`) and as a library
  (`from ricardo_scraper import scrape`).
- Free-text search across any item type (not a fixed taxonomy), with
  optional `locale` (`de`/`fr`/`it`) and client-side price/category
  filters.
- Drives a fingerprint-patched Firefox (`camoufox`) to get past
  ricardo.ch's Cloudflare Managed Challenge, with retry handling for
  Cloudflare's challenge-redirect races and a pinned, verified browser
  build (`pin_camoufox_browser.py`) to avoid a known-broken "latest"
  build camoufox's own installer would otherwise select.
- Full-detail mode (default): visits every matching listing individually
  and parses its schema.org `Product` JSON-LD block for the full record
  (description, condition, seller, brand, category breadcrumbs, images);
  `--no-detail`/`detail=False` for a faster summary-only pass.
- Every listing's raw JSON and flattened CSV row both carry a direct
  `url` back to the original ad.
- `ScrapeResult` dataclass return value (`.rows`, `.listings`,
  `.to_csv()`, `.to_json()`) for library use, with the CLI as a thin
  wrapper around the same `scrape()` function -- modeled directly on
  [`danyk20/autoscout24-scraper`](https://github.com/danyk20/autoscout24-scraper)'s
  interface for drop-in interoperability between the two.
- Console script entry point (`ricardo-scraper`) and `pip install`
  support via `pyproject.toml` packaging metadata; `--version` flag.
- Logging-based output (`-v`/`--verbose`, `-q`/`--quiet`) instead of bare
  `print()`, so library consumers can configure/suppress it via the
  standard `logging` module.
- Full type hints throughout, checked with mypy; linted and formatted
  with Ruff.
- Unit test suite (100% coverage, the browser layer fully mocked via
  `FakeBrowserSession`) plus a smaller end-to-end suite against the real
  live site.
- CI (GitHub Actions) running lint, type-check, and the unit suite on
  every push/PR across Python 3.11 and 3.12.
- MIT license with an explicit statement welcoming AI agents/bots to use
  the project under the same terms as a human developer.
- Project governance docs: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`,
  `SECURITY.md`, issue/PR templates.
