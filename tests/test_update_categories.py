import datetime
import json

import pytest

import update_categories as uc

# A trimmed copy of /api/mfa/categories' shape: flat, parent-pointer, API order
# deliberately not alphabetical.
RAW = [
    {"categoryId": 39091, "displayName": "Computer & Netzwerk", "slug": "computer-netzwerk-39091"},
    {"categoryId": 39272, "displayName": "Notebooks", "slug": "notebooks-39272", "parentId": 39091},
    {"categoryId": 39092, "displayName": "Adapter,  Kabel", "slug": "adapter-kabel-39092", "parentId": 39091},
    {"categoryId": 40295, "displayName": "Haushalt & Wohnen", "slug": "haushalt-wohnen-40295"},
    {"categoryId": 38399, "displayName": "Antiquitäten & Kunst", "slug": "antiquitaeten-kunst-38399"},
    {"categoryId": 50000, "displayName": "Zubehör", "slug": "zubehoer-50000", "parentId": 39272},
]
DATE = datetime.date(2026, 10, 5)


class _FakePage:
    def __init__(self, result):
        self.result = result
        self.evaluated_with = None

    def evaluate(self, _js, arg):
        self.evaluated_with = arg
        return self.result


class _FakeSession:
    def __init__(self, result):
        self.page = _FakePage(result)
        self.goto_log = []

    def goto(self, url):
        self.goto_log.append(url)


def test_build_tree_orders_depth_first_with_umlauts_filed_under_base_letter():
    ids = [c["id"] for c in uc.build_tree(RAW)]
    # "Antiquitäten" sorts as "Antiquitaten" (before "Computer"); children follow their parent.
    assert ids == [38399, 39091, 39092, 39272, 50000, 40295]


def test_build_tree_fills_depth_parent_and_path():
    by_id = {c["id"]: c for c in uc.build_tree(RAW)}
    assert by_id[39091] == {
        "id": 39091,
        "name": "Computer & Netzwerk",
        "slug": "computer-netzwerk-39091",
        "parent_id": None,
        "depth": 0,
        "path": "Computer & Netzwerk",
    }
    assert by_id[50000]["depth"] == 2
    assert by_id[50000]["parent_id"] == 39272
    assert by_id[50000]["path"] == "Computer & Netzwerk > Notebooks > Zubehör"


def test_build_tree_collapses_stray_whitespace_in_names():
    by_id = {c["id"]: c for c in uc.build_tree(RAW)}
    assert by_id[39092]["name"] == "Adapter, Kabel"


def test_build_tree_rejects_unknown_parent():
    with pytest.raises(ValueError, match="unknown parent 999"):
        uc.build_tree([{"categoryId": 1, "displayName": "Orphan", "slug": "orphan-1", "parentId": 999}])


def test_render_json_is_valid_and_one_category_per_line():
    categories = uc.build_tree(RAW)
    text = uc.render_json(categories, "de", DATE)
    data = json.loads(text)
    assert data["count"] == len(RAW)
    assert data["generated"] == "2026-10-05"
    assert data["source"] == "https://www.ricardo.ch/api/mfa/categories?locale=de"
    assert data["categories"] == categories
    notebooks_line = next(line for line in text.splitlines() if '"id": 39272' in line)
    assert json.loads(notebooks_line.strip().rstrip(","))["slug"] == "notebooks-39272"


def test_render_markdown_has_index_and_a_table_per_top_level_category():
    md = uc.render_markdown(uc.build_tree(RAW), DATE)
    assert "all 6 of them (3 top-level, nested up to 3 levels deep)" in md
    assert "| 39091 | [Computer & Netzwerk](#computer--netzwerk-39091) | 3 |" in md
    assert "| 38399 | [Antiquitäten & Kunst](#antiquitäten--kunst-38399) | 0 |" in md
    assert "## Computer & Netzwerk (39091)" in md
    assert "| 50000 | 2 | Computer & Netzwerk > Notebooks > Zubehör | `zubehoer-50000` |" in md


@pytest.mark.parametrize(
    ("heading", "anchor"),
    [
        ("Antiquitäten & Kunst (38399)", "antiquitäten--kunst-38399"),
        ("Handy, Festnetz, Funk (39940)", "handy-festnetz-funk-39940"),
        ("Sports (41875)", "sports-41875"),
    ],
)
def test_github_anchor(heading, anchor):
    assert uc._github_anchor(heading) == anchor


def test_fetch_categories_loads_api_from_inside_the_page():
    session = _FakeSession({"status": 200, "body": json.dumps(RAW)})
    assert uc.fetch_categories(session) == RAW
    assert session.goto_log == ["https://www.ricardo.ch/de/"]
    assert session.page.evaluated_with == "/api/mfa/categories?locale=de"


def test_fetch_categories_raises_on_http_error():
    with pytest.raises(RuntimeError, match="HTTP 403"):
        uc.fetch_categories(_FakeSession({"status": 403, "body": ""}))


def test_render_python_module_round_trips_to_the_id_to_slug_and_parent_mapping():
    source = uc.render_python_module(uc.build_tree(RAW), DATE)
    namespace: dict = {}
    exec(source, namespace)
    assert namespace["CATEGORIES"][50000] == ("zubehoer-50000", 39272)
    assert namespace["CATEGORIES"][39091] == ("computer-netzwerk-39091", None)
    assert len(namespace["CATEGORIES"]) == len(RAW)
    assert "on 2026-10-05 -- do not edit by hand" in source
