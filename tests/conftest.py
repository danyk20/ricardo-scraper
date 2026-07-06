"""Shared fixtures for the unit test suite.

The mocking seam is `BrowserSession` (the class ricardo_scraper.py's
functions call `.goto()`/`.evaluate()`/`.page` on), not an HTTP layer --
there is no separate JSON API here to mock the way AutoScout24's tests mock
`requests.Session` with the `responses` library. `FakeBrowserSession`
implements the same three-method interface and returns canned data,
mirroring that project's mocked-HTTP-payload approach one layer up the
stack (real browser navigation replaced by a dict lookup).
"""

import json

import pytest

import ricardo_scraper as scraper


class _FakePage:
    """Stands in for the Playwright Page object -- only the bits
    extract_product_jsonld()'s retry loop touches directly."""

    def wait_for_timeout(self, _ms):
        pass

    def title(self):
        return "Fake Page"


class FakeBrowserSession:
    """Fake BrowserSession for unit tests: no real browser, no network.

    `search_responses`: dict mapping an exact search URL to the list of
    summary dicts SEARCH_SUMMARY_JS would have returned for it.
    `detail_responses`: dict mapping an exact detail-page URL to the raw
    JSON-LD string `document.getElementById('pdp-json-ld')` would have
    returned for it (or None, simulating a listing with no parseable
    JSON-LD block).

    `.evaluate()` routes between the two based on which JS snippet is being
    evaluated (the only two shapes ricardo_scraper.py ever asks for), since
    there's no separate URL-vs-URL distinction visible to a mocked
    `evaluate()` call the way there is for a mocked HTTP request.
    """

    def __init__(self, search_responses=None, detail_responses=None):
        self.search_responses = search_responses or {}
        self.detail_responses = detail_responses or {}
        self.current_url = None
        self.goto_log = []
        self.closed = False
        self.page = _FakePage()

    def goto(self, url, **_kwargs):
        self.current_url = url
        self.goto_log.append(url)

    def evaluate(self, js):
        if "regular-results" in js:
            return self.search_responses.get(self.current_url, [])
        if "pdp-json-ld" in js:
            return self.detail_responses.get(self.current_url)
        raise AssertionError(f"FakeBrowserSession.evaluate() got unexpected JS: {js[:80]!r}")

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info):
        self.close()


def make_product_jsonld(
    listing_id="1234567890",
    title="Test Laptop",
    description="A fine laptop.",
    price=100.0,
    currency="CHF",
    condition="UsedCondition",
    availability="InStock",
    seller_name="test_seller",
    brand="TestBrand",
    categories=("notebooks-39272", "computer-netzwerk-39091", "de"),
    images=("https://img.ricardostatic.ch/images/example/t_1800x1350/test-laptop",),
):
    """A raw JSON-LD `<script id="pdp-json-ld">` payload, in the real shape
    observed on live ricardo.ch listing pages (schema.org @graph with a
    Product node alongside WebPage/BreadcrumbList nodes)."""
    return json.dumps(
        {
            "@context": "https://schema.org",
            "@graph": [
                {"@type": "WebPage", "name": title},
                {
                    "@type": "Product",
                    "sku": listing_id,
                    "name": title,
                    "description": description,
                    "category": [{"url": f"https://www.ricardo.ch/de/c/{c}/"} for c in categories],
                    "image": list(images),
                    "brand": {"@type": "Brand", "name": brand} if brand else None,
                    "offers": {
                        "@type": "Offer",
                        "price": price,
                        "priceCurrency": currency,
                        "itemCondition": f"https://schema.org/{condition}",
                        "availability": f"https://schema.org/{availability}",
                        "availabilityEnds": "2026-08-01T00:00:00Z",
                        "seller": {
                            "@type": "Person",
                            "name": seller_name,
                            "url": f"https://www.ricardo.ch/de/shop/{seller_name}/offers/",
                        },
                    },
                },
            ],
        }
    )


def make_summary_item(listing_id="1234567890", title="Test Laptop", price=100.0, slug="test-laptop"):
    """A search-results-shaped summary dict, matching SEARCH_SUMMARY_JS's
    return value (the "url" field holds a relative href at this stage, same
    as the raw browser-evaluated value before search_listings() makes it
    absolute)."""
    return {
        "id": listing_id,
        "title": title,
        "url": f"/de/a/{slug}-{listing_id}/",
        "price": price,
        "image": f"https://img.ricardostatic.ch/images/example/t_265x200/{slug}",
    }


@pytest.fixture
def product_jsonld_factory():
    return make_product_jsonld


@pytest.fixture
def summary_item_factory():
    return make_summary_item


@pytest.fixture
def fake_session_factory():
    return FakeBrowserSession


@pytest.fixture
def no_sleep(monkeypatch):
    """Make time.sleep a no-op so tests exercising delay loops run instantly."""
    monkeypatch.setattr(scraper.time, "sleep", lambda *_args, **_kwargs: None)
