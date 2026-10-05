import pytest

from ricardo_categories import CATEGORIES as BUNDLED
from ricardo_scraper import _category_matches, _with_ancestors

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


# A trimmed copy of the real Büro & Gewerbe branch (ricardo_categories.py's
# shape): a listing in 82351 only carries the 82351/79697/79687 breadcrumbs.
TREE = {
    63788: ("buero-gewerbe-63788", None),
    79574: ("agrar-forst-bauen-79574", 63788),
    79687: ("erntetechnik-79687", 79574),
    79697: ("pressen-wickeln-zubehoer-79697", 79687),
    82351: ("pressen-wickelnzubehoer-82351", 79697),
}
DEEP_BREADCRUMBS = ["pressen-wickelnzubehoer-82351", "pressen-wickeln-zubehoer-79697", "erntetechnik-79687", "de"]


@pytest.fixture
def tree(monkeypatch):
    monkeypatch.setattr("ricardo_scraper.CATEGORIES", TREE)


@pytest.mark.parametrize(
    "category",
    [
        "63788",  # top-level id, 4 levels above the listing -- not in its breadcrumbs
        "79574",  # 3 levels above -- also not in its breadcrumbs
        "79687",  # nearest ancestor that *is* in the breadcrumbs
        "buero-gewerbe-63788",  # full slug of a missing ancestor
        "agrar",  # one word out of a missing ancestor's slug
    ],
)
def test_category_matches_any_ancestor_beyond_the_breadcrumbs(tree, category):
    assert _category_matches(DEEP_BREADCRUMBS, category) is True


def test_category_ancestors_do_not_widen_the_match_downwards_or_sideways(tree):
    # A listing filed under the top-level category itself is not in a subcategory.
    assert _category_matches(["buero-gewerbe-63788", "de"], "79574") is False
    assert _category_matches(DEEP_BREADCRUMBS, "39091") is False


def test_category_matches_falls_back_to_breadcrumbs_for_ids_missing_from_the_snapshot(tree):
    # 99999 is newer than the snapshot: no ancestry, but its own breadcrumbs still match.
    crumbs = ["neue-kategorie-99999", "erntetechnik-79687", "de"]
    assert _category_matches(crumbs, "99999") is True
    assert _category_matches(crumbs, "63788") is True  # via its known breadcrumb 79687
    assert _category_matches(["neue-kategorie-99999", "de"], "63788") is False


def test_with_ancestors_appends_each_missing_ancestor_once(tree):
    assert _with_ancestors(DEEP_BREADCRUMBS) == [*DEEP_BREADCRUMBS, "agrar-forst-bauen-79574", "buero-gewerbe-63788"]


def test_with_ancestors_stops_at_a_parent_missing_from_the_snapshot(monkeypatch):
    monkeypatch.setattr("ricardo_scraper.CATEGORIES", {82351: ("pressen-wickelnzubehoer-82351", 79697)})
    assert _with_ancestors(["pressen-wickelnzubehoer-82351"]) == ["pressen-wickelnzubehoer-82351"]


def test_bundled_snapshot_is_a_consistent_tree():
    # Guards the generated ricardo_categories.py itself: every parent exists,
    # every slug ends in its own id, and every chain reaches a top-level category.
    assert len(BUNDLED) > 1000
    for category_id, (slug, parent_id) in BUNDLED.items():
        assert slug.endswith(f"-{category_id}")
        seen = {category_id}
        while parent_id is not None:
            assert parent_id in BUNDLED and parent_id not in seen
            seen.add(parent_id)
            parent_id = BUNDLED[parent_id][1]
