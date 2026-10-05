import pytest

import ricardo_scraper
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


# A trimmed copy of the real Büro & Gewerbe branch, in _CATEGORY_PARENTS'
# id -> (slug, parent id) shape: a listing in 82351 only carries the 82351/79697/79687 breadcrumbs.
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
    monkeypatch.setattr("ricardo_scraper._CATEGORY_PARENTS", TREE)


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
    monkeypatch.setattr("ricardo_scraper._CATEGORY_PARENTS", {82351: ("pressen-wickelnzubehoer-82351", 79697)})
    assert _with_ancestors(["pressen-wickelnzubehoer-82351"]) == ["pressen-wickelnzubehoer-82351"]


def test_public_categories_list_has_one_record_per_category():
    # ricardo_scraper.CATEGORIES is public API (downstream code builds its own
    # tree from id/name/parent_id), so pin the record shape, not just the count.
    assert len(ricardo_scraper.CATEGORIES) > 1000
    for record in ricardo_scraper.CATEGORIES:
        assert set(record) == {"id", "name", "slug", "parent_id", "depth", "path"}
        assert isinstance(record["id"], int)
        assert record["slug"].endswith(f"-{record['id']}")
    ids = [c["id"] for c in ricardo_scraper.CATEGORIES]
    assert len(ids) == len(set(ids))
    notebooks = next(c for c in ricardo_scraper.CATEGORIES if c["id"] == 39272)
    assert notebooks["parent_id"] == 39091
    assert notebooks["path"] == "Computer & Netzwerk > Notebooks"


def test_bundled_snapshot_is_a_consistent_tree():
    # Every parent exists and comes before its children (depth-first order),
    # depth matches the parent chain, and the path ends in the category's name.
    by_id = {}
    for record in ricardo_scraper.CATEGORIES:
        parent = by_id.get(record["parent_id"])
        if record["parent_id"] is None:
            assert record["depth"] == 0
            assert record["path"] == record["name"]
        else:
            assert parent is not None, f"{record['id']} listed before its parent {record['parent_id']}"
            assert record["depth"] == parent["depth"] + 1
            assert record["path"] == f"{parent['path']} > {record['name']}"
        by_id[record["id"]] = record
    assert ricardo_scraper._CATEGORY_PARENTS == {i: (c["slug"], c["parent_id"]) for i, c in by_id.items()}
