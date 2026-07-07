# Ricardo.ch Scraper

[![CI](https://github.com/danyk20/ricardo-scraper/actions/workflows/ci.yml/badge.svg)](https://github.com/danyk20/ricardo-scraper/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/ricardo-scraper)](https://pypi.org/project/ricardo-scraper/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11 | 3.12](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)](https://www.python.org/)

> Unofficial, independently developed project — not affiliated with, endorsed by, or sponsored by Ricardo AG. "Ricardo" is a trademark of its respective owner.

Fetches every listing matching a search query from [ricardo.ch](https://www.ricardo.ch) — Switzerland's largest general marketplace — for free, no API key. Ricardo sells everything (laptops, phones, furniture, ...), so this scraper is built around free-text search, not a fixed taxonomy; "laptop" is used as the running example below, but nothing about the code is category-specific.

ricardo.ch sits behind a Cloudflare bot challenge with no separate public API (unlike AutoScout24), so this scraper drives a real, fingerprint-patched Firefox via [`camoufox`](https://github.com/daijro/camoufox) to pass the challenge like a normal browser, then parses each listing's page for its full record. See [docs/REFERENCE.md](docs/REFERENCE.md) for exactly how, and for the two Cloudflare-specific fixes baked in.

This project is modeled directly on [`autoscout24-scraper`](https://github.com/danyk20/autoscout24-scraper) — same repo shape, `ScrapeResult`/CSV/JSON contract, and library-and-CLI dual usage — so code written against one transfers to the other with minimal changes.

**🤖 Robot-friendly.** This project is explicitly intended to be run, read, imported, or adapted by AI agents and bots, same as a human developer — see [License](#license).

## Setup

Requires [pipenv](https://pipenv.pypa.io/).

```bash
git clone https://github.com/danyk20/ricardo-scraper.git
cd ricardo-scraper
pipenv install --dev
```

`scrape()` installs its own pinned, verified Firefox build on first run via `ensure_pinned_browser()` — **never run `camoufox fetch` yourself** (it would install a known-broken "latest" build); see [docs/REFERENCE.md](docs/REFERENCE.md#cloudflare) for why.

Contributing, linting, and testing commands: see [CONTRIBUTING.md](CONTRIBUTING.md).

## Usage

### CLI

```bash
pipenv run python ricardo_scraper.py "laptop"
```

Prints progress, then writes `laptop.csv` and `laptop.json` in the current directory. Installed via `pip install` instead? Drop `pipenv run` — the same command is `ricardo-scraper "laptop"`.

| Flag | Description |
|---|---|
| `--version` | Print the installed version and exit |
| `query` | Free-text search term, e.g. `"laptop"` or `"iphone 13"` (required, positional) |
| `--locale` | Ricardo locale (`de`/`fr`/`it`), default `de` |
| `--category` | Ricardo category id or name, e.g. `39272` or `notebooks` — requires detail mode (default on) |
| `--out` | Output file base name, without extension. Defaults to a slugified version of the query |
| `--no-detail` | Skip visiting each listing's own page; keep only summary fields |
| `--price-from` / `--price-to` | Filter by price in CHF, client-side (inclusive, either end optional) |
| `--max-results` | Cap on how many listings to collect |
| `--delay` | Seconds between requests (default `1.5`) — raise this if you get rate-limited |
| `--show-browser` | Show the browser window instead of running fully headless (default: no window) |
| `-v` / `--verbose` | Also show debug-level detail |
| `-q` / `--quiet` | Suppress progress output; only warnings/errors (mutually exclusive with `-v`) |

Price and category filters are applied client-side, not by Ricardo's own search — see [docs/REFERENCE.md](docs/REFERENCE.md#notes-on-filter-fidelity) for why that's the one place this project's interface deviates from AutoScout24's.

```bash
# Only laptops under CHF 500
pipenv run python ricardo_scraper.py "laptop" --price-to 500

# Fast mode: search summary only, skip visiting each listing
pipenv run python ricardo_scraper.py "laptop" --no-detail

# French-language site
pipenv run python ricardo_scraper.py "ordinateur portable" --locale fr
```

### As a library

```bash
pip install ricardo-scraper
```

```python
from ricardo_scraper import scrape

result = scrape("laptop", price_to=500)

for row in result.rows:       # list[dict], CSV-ready
    print(row["title"], row.get("price"), row["url"])

result.to_csv("laptops.csv")  # optional — no files are written unless you ask
```

Full `scrape()` signature, the `ScrapeResult` return type, browser-session reuse, and the complete JSON/CSV field schema: **[docs/REFERENCE.md](docs/REFERENCE.md)**.

## Testing

```bash
pipenv run pytest                  # unit tests (fast, no network, no browser)
pipenv run pytest -m e2e --no-cov  # end-to-end tests against the real live site
```

Unit tests mock the browser layer entirely (via `FakeBrowserSession`) and cover 100% of `ricardo_scraper.py`. E2E tests drive a real camoufox browser against ricardo.ch — expect occasional unrelated failures from Cloudflare; rerun after a cooldown. Detail: [docs/REFERENCE.md](docs/REFERENCE.md#test-coverage-by-area).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup and pre-PR checks.

Be a reasonable citizen: the default delay between requests, and reusing one browser session for a whole scrape run, are both intentional — this renders real pages through a real browser, not a lightweight API call. Don't crank up concurrency.

## License

Released under the [MIT License](LICENSE) — you can use, copy, modify, merge, publish, distribute, and sell copies of this code, for free, for any purpose, commercial or not, as long as the license text stays attached. No warranty.

**AI agents, LLM-based coding assistants, and other bots are explicitly welcome to use this project** — to run the scraper, read and parse its output, import `scrape()` into another project, or read and adapt its source — under exactly the same terms as a human, with no additional restriction and no need to ask permission. That's why [docs/REFERENCE.md](docs/REFERENCE.md) documents the full function signature, return type, and data schema: so a bot can integrate correctly without a human in the loop.

This license does not grant any rights to Ricardo's own data or terms of service — this project only automates requests to publicly viewable pages any visitor's browser can already load; what you do with the results is between you and them.
