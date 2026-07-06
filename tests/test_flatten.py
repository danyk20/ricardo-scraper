from ricardo_scraper import _scalarize, flatten_listing, order_fieldnames


def test_scalarize_passthrough_scalars():
    assert _scalarize(None) == ""
    assert _scalarize("hello") == "hello"
    assert _scalarize(42) == 42
    assert _scalarize(3.14) == 3.14
    assert _scalarize(True) is True


def test_scalarize_dict_becomes_json_string():
    result = _scalarize({"b": 2, "a": 1})
    assert result == '{"a": 1, "b": 2}'


def test_scalarize_list_is_semicolon_joined():
    assert _scalarize(["a", "b", "c"]) == "a; b; c"


def test_scalarize_list_of_dicts_recurses():
    result = _scalarize([{"x": 1}, {"y": 2}])
    assert result == '{"x": 1}; {"y": 2}'


def test_scalarize_fallback_for_unrecognized_type():
    class Weird:
        def __str__(self):
            return "weird-value"

    assert _scalarize(Weird()) == "weird-value"


def test_flatten_listing_scalar_fields_pass_through():
    item = {"id": "1", "title": "Laptop", "price": 100.0}
    assert flatten_listing(item) == {"id": "1", "title": "Laptop", "price": 100.0}


def test_flatten_listing_lists_are_joined():
    item = {"id": "1", "categories": ["a", "b"], "images": ["img1", "img2"]}
    flat = flatten_listing(item)
    assert flat["categories"] == "a; b"
    assert flat["images"] == "img1; img2"


def test_flatten_listing_nested_dict_becomes_parent_child_columns():
    item = {"id": "1", "extra": {"foo": "bar", "baz": 1}}
    flat = flatten_listing(item)
    assert flat["extra_foo"] == "bar"
    assert flat["extra_baz"] == 1
    assert "extra" not in flat


def test_order_fieldnames_priority_first_then_alphabetical():
    keys = {"url", "zeta", "id", "alpha", "price", "brand"}
    ordered = order_fieldnames(keys)
    assert ordered == ["id", "price", "brand", "url", "alpha", "zeta"]


def test_order_fieldnames_missing_priority_fields_are_skipped():
    keys = {"alpha", "zeta"}
    assert order_fieldnames(keys) == ["alpha", "zeta"]
