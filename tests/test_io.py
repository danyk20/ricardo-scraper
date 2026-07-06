import csv
import json

from ricardo_scraper import ScrapeResult, save_csv, save_json


def test_save_csv_writes_header_and_rows(tmp_path):
    rows = [{"id": "1", "title": "Laptop A", "price": 100.0}, {"id": "2", "title": "Laptop B", "price": 200.0}]
    path = tmp_path / "out.csv"

    save_csv(rows, str(path))

    with open(path, newline="", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
    assert len(reader) == 2
    assert reader[0]["title"] == "Laptop A"


def test_save_csv_heterogeneous_rows_fill_missing_with_empty_string(tmp_path):
    rows = [{"id": "1", "title": "Laptop A"}, {"id": "2", "brand": "Dell"}]
    path = tmp_path / "out.csv"

    save_csv(rows, str(path))

    with open(path, newline="", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
    assert reader[0]["brand"] == ""
    assert reader[1]["title"] == ""


def test_save_csv_unicode_is_preserved(tmp_path):
    rows = [{"id": "1", "title": 'Günstiger Laptop – 15"'}]
    path = tmp_path / "out.csv"

    save_csv(rows, str(path))

    content = path.read_text(encoding="utf-8")
    assert 'Günstiger Laptop – 15"' in content


def test_save_csv_empty_rows_writes_nothing(tmp_path):
    path = tmp_path / "out.csv"

    save_csv([], str(path))

    assert not path.exists()


def test_save_json_round_trip_with_unicode(tmp_path):
    rows = [{"id": "1", "title": "Günstiger Laptop"}]
    path = tmp_path / "out.json"

    save_json(rows, str(path))

    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded == rows
    assert "Günstiger" in path.read_text(encoding="utf-8")  # not \u-escaped


def test_scrape_result_to_csv_and_to_json(tmp_path):
    result = ScrapeResult(
        query="laptop",
        locale="de",
        category=None,
        total_elements=1,
        listings=[{"id": "1", "title": "Laptop", "images": ["a", "b"]}],
        rows=[{"id": "1", "title": "Laptop", "images": "a; b"}],
    )

    csv_path = tmp_path / "r.csv"
    json_path = tmp_path / "r.json"
    result.to_csv(str(csv_path))
    result.to_json(str(json_path))

    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["images"] == "a; b"

    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded[0]["images"] == ["a", "b"]  # .to_json() writes .listings (raw), not .rows (flattened)
