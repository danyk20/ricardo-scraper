import json

from ricardo_scraper import _extract_extra_fields, extract_next_data

DETAIL_URL = "https://www.ricardo.ch/de/a/test-laptop-1234567890/"


def test_extract_next_data_found_immediately(fake_session_factory, next_data_factory):
    session = fake_session_factory(next_data_responses={DETAIL_URL: next_data_factory()})
    session.goto(DETAIL_URL)

    data = extract_next_data(session)

    assert data["props"]["pageProps"]["article"]["offer"]["city"] == "Zürich"


def test_extract_next_data_retries_then_succeeds(fake_session_factory, next_data_factory):
    calls = {"n": 0}
    session = fake_session_factory(next_data_responses={DETAIL_URL: next_data_factory()})
    session.goto(DETAIL_URL)
    original_evaluate = session.evaluate

    def flaky_evaluate(js):
        calls["n"] += 1
        if calls["n"] < 2:
            return None
        return original_evaluate(js)

    session.evaluate = flaky_evaluate

    data = extract_next_data(session, attempts=5, retry_wait_ms=0)

    assert data is not None
    assert calls["n"] == 2


def test_extract_next_data_missing_returns_none(fake_session_factory):
    session = fake_session_factory(next_data_responses={DETAIL_URL: None})
    session.goto(DETAIL_URL)

    assert extract_next_data(session, attempts=1) is None


def test_extract_next_data_malformed_json_returns_none(fake_session_factory):
    session = fake_session_factory(next_data_responses={DETAIL_URL: "{not valid json"})
    session.goto(DETAIL_URL)

    assert extract_next_data(session, attempts=1) is None


def test_extract_extra_fields_none_input_returns_defaults():
    extra = _extract_extra_fields(None)

    assert extra == {
        "location_city": None,
        "location_zip": None,
        "seller_rating_score": None,
        "seller_ratings_count": None,
        "delivery_options": [],
        "questions_and_answers": [],
    }


def test_extract_extra_fields_full_shape(next_data_factory):
    next_data = json.loads(
        next_data_factory(
            location_city="Biberist",
            location_zip="4562",
            seller_score=0.9894,
            seller_ratings_count=481,
            delivery_options=(("parcel_b_10kg", 1200, False), ("get_by_buyer", 0, False)),
            questions_and_answers=(("Kann ich abholen?", "Ja, klar.", "2026-06-01T00:00:00Z", "2026-06-02T00:00:00Z"),),
        )
    )

    extra = _extract_extra_fields(next_data)

    assert extra["location_city"] == "Biberist"
    assert extra["location_zip"] == "4562"
    assert extra["seller_rating_score"] == 98.94
    assert extra["seller_ratings_count"] == 481
    assert extra["delivery_options"] == [
        {"id": "parcel_b_10kg", "price": 12.0, "cumulative": False},
        {"id": "get_by_buyer", "price": 0.0, "cumulative": False},
    ]
    assert extra["questions_and_answers"] == [
        {
            "question": "Kann ich abholen?",
            "question_date": "2026-06-01T00:00:00Z",
            "answer": "Ja, klar.",
            "answer_date": "2026-06-02T00:00:00Z",
        }
    ]


def test_extract_extra_fields_no_seller_rating_yet(next_data_factory):
    """A seller with zero ratings has score=None (not 0) on real pages."""
    next_data = json.loads(next_data_factory(seller_score=None, seller_ratings_count=0))

    extra = _extract_extra_fields(next_data)

    assert extra["seller_rating_score"] is None
    assert extra["seller_ratings_count"] == 0


def test_extract_extra_fields_no_questions_yet(next_data_factory):
    next_data = json.loads(next_data_factory(questions_and_answers=()))

    extra = _extract_extra_fields(next_data)

    assert extra["questions_and_answers"] == []


def test_extract_extra_fields_unanswered_question(next_data_factory):
    next_data = json.loads(
        next_data_factory(questions_and_answers=(("Still available?", None, "2026-06-01T00:00:00Z", None),))
    )

    extra = _extract_extra_fields(next_data)

    assert extra["questions_and_answers"] == [
        {"question": "Still available?", "question_date": "2026-06-01T00:00:00Z", "answer": None, "answer_date": None}
    ]


def test_extract_extra_fields_missing_article_key_degrades_gracefully():
    extra = _extract_extra_fields({"props": {"pageProps": {}}})

    assert extra["location_city"] is None
    assert extra["delivery_options"] == []


def test_extract_extra_fields_missing_dehydrated_state_degrades_gracefully():
    next_data = {"props": {"pageProps": {"article": {"offer": {"city": "Bern"}}}}}

    extra = _extract_extra_fields(next_data)

    assert extra["location_city"] == "Bern"
    assert extra["questions_and_answers"] == []
