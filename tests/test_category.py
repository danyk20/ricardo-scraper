import pytest

from ricardo_scraper import _category_matches

CATEGORIES = ["notebooks-39272", "computer-netzwerk-39091", "de"]


@pytest.mark.parametrize(
    "category",
    [
        "39272",  # numeric id
        "notebooks-39272",  # full slug
        "notebooks",  # bare name, lowercase
        "Notebooks",  # bare name, mixed case
        "NOTEBOOKS",  # bare name, uppercase
        "computer-netzwerk",  # multi-word slug name (id stripped)
        "computer",  # single word out of a multi-word slug
        "netzwerk",  # the other word out of that same multi-word slug
    ],
)
def test_category_matches_positive_cases(category):
    assert _category_matches(CATEGORIES, category) is True


@pytest.mark.parametrize("category", ["furniture", "391", "notebook", "39091notebooks"])
def test_category_matches_negative_cases(category):
    assert _category_matches(CATEGORIES, category) is False


def test_category_matches_empty_categories_list():
    assert _category_matches([], "notebooks") is False
