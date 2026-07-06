from ricardo_scraper import BASE_URL, search_listings


def _url(query, page, locale="de"):
    return f"{BASE_URL}/{locale}/s/{query}?page={page}"


def test_search_listings_paginates_and_dedupes(fake_session_factory, summary_item_factory, no_sleep):
    boosted = summary_item_factory(listing_id="1", title="Boosted item", price=50.0)
    page1_items = [boosted, summary_item_factory(listing_id="2", title="Second item", price=80.0)]
    # The boosted listing reappears at the top of page 2 -- a real Ricardo
    # behavior this function must de-duplicate against.
    page2_items = [boosted, summary_item_factory(listing_id="3", title="Third item", price=120.0)]

    session = fake_session_factory(
        search_responses={
            _url("laptop", 1): page1_items,
            _url("laptop", 2): page2_items,
            _url("laptop", 3): [],
        }
    )

    listings = search_listings(session, "laptop", verbose=False)

    assert [item["id"] for item in listings] == ["1", "2", "3"]
    assert listings[0]["url"] == f"{BASE_URL}/de/a/test-laptop-1/"


def test_search_listings_empty_first_page_returns_nothing(fake_session_factory, no_sleep):
    session = fake_session_factory(search_responses={_url("nonexistentquery", 1): []})
    listings = search_listings(session, "nonexistentquery", verbose=False)
    assert listings == []


def test_search_listings_respects_max_results(fake_session_factory, summary_item_factory, no_sleep):
    page1_items = [summary_item_factory(listing_id=str(i), price=float(i)) for i in range(10)]
    session = fake_session_factory(search_responses={_url("laptop", 1): page1_items})

    listings = search_listings(session, "laptop", max_results=3, verbose=False)

    assert len(listings) == 3
    assert [item["id"] for item in listings] == ["0", "1", "2"]


def test_search_listings_uses_the_given_locale(fake_session_factory, summary_item_factory, no_sleep):
    session = fake_session_factory(
        search_responses={
            _url("laptop", 1, locale="fr"): [summary_item_factory(listing_id="1")],
            _url("laptop", 1, locale="de"): [summary_item_factory(listing_id="999")],
        }
    )

    listings = search_listings(session, "laptop", locale="fr", verbose=False)

    assert [item["id"] for item in listings] == ["1"]


def test_search_listings_verbose_logs_progress(fake_session_factory, summary_item_factory, no_sleep):
    session = fake_session_factory(search_responses={_url("laptop", 1): [summary_item_factory(listing_id="1")]})
    listings = search_listings(session, "laptop", verbose=True)
    assert len(listings) == 1


def test_search_listings_skips_items_with_no_id(fake_session_factory, no_sleep):
    session = fake_session_factory(search_responses={_url("laptop", 1): [{"id": None, "title": "broken card"}]})
    listings = search_listings(session, "laptop", verbose=False)
    assert listings == []
