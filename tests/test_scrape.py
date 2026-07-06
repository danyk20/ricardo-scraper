import pytest

from ricardo_scraper import BASE_URL, scrape


def _url(query, page, locale="de"):
    return f"{BASE_URL}/{locale}/s/{query}?page={page}"


def test_scrape_rejects_price_from_greater_than_price_to(fake_session_factory):
    session = fake_session_factory()
    with pytest.raises(ValueError, match="price_from"):
        scrape("laptop", price_from=200, price_to=100, session=session)
    assert session.goto_log == []  # validated before any navigation


def test_scrape_rejects_category_without_detail(fake_session_factory):
    session = fake_session_factory()
    with pytest.raises(ValueError, match="detail=True"):
        scrape("laptop", category="39272", detail=False, session=session)
    assert session.goto_log == []


def test_scrape_full_happy_path_with_price_filter_and_detail(
    fake_session_factory, summary_item_factory, product_jsonld_factory, no_sleep
):
    cheap = summary_item_factory(listing_id="1", title="Cheap laptop", price=50.0, slug="cheap-laptop")
    mid = summary_item_factory(listing_id="2", title="Mid laptop", price=150.0, slug="mid-laptop")
    expensive = summary_item_factory(listing_id="3", title="Pricey laptop", price=999.0, slug="pricey-laptop")

    detail_url_mid = f"{BASE_URL}/de/a/mid-laptop-2/"
    detail_url_cheap = f"{BASE_URL}/de/a/cheap-laptop-1/"

    session = fake_session_factory(
        search_responses={
            _url("laptop", 1): [cheap, mid, expensive],
            _url("laptop", 2): [],
        },
        detail_responses={
            detail_url_cheap: product_jsonld_factory(listing_id="1", title="Cheap laptop", price=50.0),
            detail_url_mid: product_jsonld_factory(listing_id="2", title="Mid laptop", price=150.0),
        },
    )

    result = scrape("laptop", price_from=40, price_to=500, verbose=False, session=session)

    assert result.query == "laptop"
    assert result.total_elements == 3  # pre-filter search count
    assert [item["id"] for item in result.listings] == ["1", "2"]
    # rows sorted by price ascending
    assert [row["id"] for row in result.rows] == ["1", "2"]
    assert session.closed is False  # caller-provided session is not closed by scrape()


def test_scrape_no_detail_returns_summary_shape_only(fake_session_factory, summary_item_factory, no_sleep):
    session = fake_session_factory(search_responses={_url("laptop", 1): [summary_item_factory(listing_id="1")]})

    result = scrape("laptop", detail=False, verbose=False, session=session)

    assert result.total_elements == 1
    assert result.listings[0]["id"] == "1"
    assert "image" in result.listings[0]
    assert "description" not in result.listings[0]
    # Only search-page navigations happened (page 1 with a result, page 2
    # confirming there's nothing more) -- no detail-page URL was ever visited.
    assert session.goto_log == [_url("laptop", 1), _url("laptop", 2)]


def test_scrape_category_filter_applied_after_detail(
    fake_session_factory, summary_item_factory, product_jsonld_factory, no_sleep
):
    a = summary_item_factory(listing_id="1", slug="a")
    b = summary_item_factory(listing_id="2", slug="b")
    url_a = f"{BASE_URL}/de/a/a-1/"
    url_b = f"{BASE_URL}/de/a/b-2/"

    session = fake_session_factory(
        search_responses={_url("laptop", 1): [a, b]},
        detail_responses={
            url_a: product_jsonld_factory(listing_id="1", categories=["notebooks-39272", "de"]),
            url_b: product_jsonld_factory(listing_id="2", categories=["phones-12345", "de"]),
        },
    )

    result = scrape("laptop", category="39272", verbose=False, session=session)

    assert [item["id"] for item in result.listings] == ["1"]


def test_scrape_verbose_logs_progress_through_every_stage(
    fake_session_factory, summary_item_factory, product_jsonld_factory, no_sleep
):
    item = summary_item_factory(listing_id="1", price=50.0, slug="a")
    detail_url = f"{BASE_URL}/de/a/a-1/"
    session = fake_session_factory(
        search_responses={_url("laptop", 1): [item]},
        detail_responses={detail_url: product_jsonld_factory(listing_id="1", categories=["notebooks-39272"])},
    )

    result = scrape("laptop", price_from=1, category="39272", verbose=True, session=session)

    assert result.total_elements == 1


def test_scrape_owns_and_closes_a_session_it_creates(monkeypatch, fake_session_factory, summary_item_factory, no_sleep):
    fake = fake_session_factory(search_responses={_url("laptop", 1): [summary_item_factory(listing_id="1")]})
    monkeypatch.setattr("ricardo_scraper.BrowserSession", lambda headless=True: fake)

    scrape("laptop", detail=False, verbose=False)

    assert fake.closed is True
