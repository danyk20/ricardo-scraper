from ricardo_scraper import extract_product_jsonld, visit_all_listings

DETAIL_URL = "https://www.ricardo.ch/de/a/test-laptop-1234567890/"


def test_extract_product_jsonld_found_immediately(fake_session_factory, product_jsonld_factory):
    session = fake_session_factory(detail_responses={DETAIL_URL: product_jsonld_factory()})
    session.goto(DETAIL_URL)

    product = extract_product_jsonld(session)

    assert product["sku"] == "1234567890"
    assert product["name"] == "Test Laptop"


def test_extract_product_jsonld_retries_then_succeeds(fake_session_factory, product_jsonld_factory):
    """Simulates the real-world race: the very first read of the script tag
    on a fresh navigation can come back empty even though the page has
    genuinely finished navigating -- extract_product_jsonld() should retry
    rather than give up on the first empty read."""
    calls = {"n": 0}

    session = fake_session_factory(detail_responses={DETAIL_URL: product_jsonld_factory()})
    session.goto(DETAIL_URL)

    original_evaluate = session.evaluate

    def flaky_evaluate(js):
        calls["n"] += 1
        if calls["n"] < 3:
            return None
        return original_evaluate(js)

    session.evaluate = flaky_evaluate

    product = extract_product_jsonld(session, attempts=5, retry_wait_ms=0)

    assert product["sku"] == "1234567890"
    assert calls["n"] == 3


def test_extract_product_jsonld_gives_up_after_all_attempts(fake_session_factory):
    session = fake_session_factory(detail_responses={DETAIL_URL: None})
    session.goto(DETAIL_URL)

    product = extract_product_jsonld(session, attempts=2, retry_wait_ms=0)

    assert product is None


def test_extract_product_jsonld_no_product_node(fake_session_factory):
    import json

    session = fake_session_factory(
        detail_responses={DETAIL_URL: json.dumps({"@graph": [{"@type": "WebPage", "name": "no product here"}]})}
    )
    session.goto(DETAIL_URL)

    product = extract_product_jsonld(session, attempts=1)

    assert product is None


def test_visit_all_listings_replaces_summary_with_full_record(
    fake_session_factory, summary_item_factory, product_jsonld_factory, no_sleep
):
    summary = summary_item_factory(listing_id="1234567890")
    summary["url"] = DETAIL_URL  # search_listings() normally makes this absolute before this point
    session = fake_session_factory(detail_responses={DETAIL_URL: product_jsonld_factory()})

    visited = visit_all_listings(session, [summary], verbose=False)

    assert len(visited) == 1
    item = visited[0]
    assert item["id"] == "1234567890"
    assert item["description"] == "A fine laptop."
    assert item["categories"] == ["notebooks-39272", "computer-netzwerk-39091", "de"]
    assert "image" not in item  # summary-only field, replaced by the richer "images" list


def test_visit_all_listings_verbose_logs_progress(
    fake_session_factory, summary_item_factory, product_jsonld_factory, no_sleep
):
    summary = summary_item_factory(listing_id="1234567890")
    summary["url"] = DETAIL_URL
    session = fake_session_factory(detail_responses={DETAIL_URL: product_jsonld_factory()})

    visited = visit_all_listings(session, [summary], verbose=True)

    assert len(visited) == 1


def test_visit_all_listings_skips_listings_with_no_product_data(fake_session_factory, summary_item_factory, no_sleep):
    good = summary_item_factory(listing_id="1")
    good["url"] = "https://www.ricardo.ch/de/a/good-1/"
    bad = summary_item_factory(listing_id="2")
    bad["url"] = "https://www.ricardo.ch/de/a/bad-2/"

    session = fake_session_factory(detail_responses={good["url"]: _minimal_jsonld("1"), bad["url"]: None})

    visited = visit_all_listings(session, [good, bad], verbose=False)

    assert [item["id"] for item in visited] == ["1"]


def _minimal_jsonld(listing_id):
    import json

    return json.dumps({"@graph": [{"@type": "Product", "sku": listing_id, "name": "x", "offers": {}}]})
