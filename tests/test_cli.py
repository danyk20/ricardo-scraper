import pytest
from playwright.sync_api import Error as PlaywrightError

import ricardo_scraper as scraper
from ricardo_scraper import ScrapeResult, _slugify, build_arg_parser, main, run_cli


def test_arg_parser_requires_query():
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_arg_parser_version_exits_zero(capsys):
    parser = build_arg_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--version"])
    assert exc_info.value.code == 0
    assert scraper.__version__ in capsys.readouterr().out


def test_arg_parser_defaults():
    parser = build_arg_parser()
    args = parser.parse_args(["laptop"])
    assert args.query == "laptop"
    assert args.locale == "de"
    assert args.category is None
    assert args.no_detail is False
    assert args.delay == 1.5
    assert args.price_from is None
    assert args.price_to is None


def test_arg_parser_rejects_invalid_locale():
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["laptop", "--locale", "es"])


def test_arg_parser_verbose_and_quiet_are_mutually_exclusive():
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["laptop", "-v", "-q"])


def test_arg_parser_all_flags_parse():
    parser = build_arg_parser()
    args = parser.parse_args(
        [
            "laptop",
            "--locale",
            "fr",
            "--category",
            "39272",
            "--out",
            "myout",
            "--no-detail",
            "--delay",
            "2.5",
            "--max-results",
            "10",
            "--price-from",
            "10",
            "--price-to",
            "500",
            "--show-browser",
            "-v",
        ]
    )
    assert args.locale == "fr"
    assert args.category == "39272"
    assert args.out == "myout"
    assert args.no_detail is True
    assert args.delay == 2.5
    assert args.max_results == 10
    assert args.price_from == 10
    assert args.price_to == 500
    assert args.show_browser is True
    assert args.verbose is True


def _fake_result(**overrides):
    defaults = dict(
        query="laptop",
        locale="de",
        category=None,
        total_elements=1,
        listings=[{"id": "1"}],
        rows=[{"id": "1"}],
    )
    defaults.update(overrides)
    return ScrapeResult(**defaults)


def test_main_writes_csv_and_json_with_default_out_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(scraper, "scrape", lambda *a, **kw: _fake_result())

    exit_code = main(["laptop"])

    assert exit_code == 0
    assert (tmp_path / "laptop.csv").exists()
    assert (tmp_path / "laptop.json").exists()


def test_main_writes_to_custom_out_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(scraper, "scrape", lambda *a, **kw: _fake_result())

    main(["laptop", "--out", "custom_name"])

    assert (tmp_path / "custom_name.csv").exists()
    assert (tmp_path / "custom_name.json").exists()


def test_main_passes_flags_through_to_scrape(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    captured = {}

    def fake_scrape(query, **kwargs):
        captured["query"] = query
        captured.update(kwargs)
        return _fake_result(query=query)

    monkeypatch.setattr(scraper, "scrape", fake_scrape)

    main(["laptop", "--no-detail", "--price-to", "200", "--show-browser"])

    assert captured["query"] == "laptop"
    assert captured["detail"] is False
    assert captured["price_to"] == 200
    assert captured["headless"] is False


def test_run_cli_maps_value_error_to_exit_1(monkeypatch, capsys):
    # main() (called by run_cli()) configures real stderr handlers on the
    # "ricardo_scraper" logger with propagate=False -- by design, so a host
    # application's own logging config is never disturbed by importing this
    # module. That also means caplog (which attaches at the root logger)
    # never sees these records; asserting on the real stderr output is the
    # actual observable behavior a CLI user would see.
    monkeypatch.setattr(scraper, "scrape", lambda *a, **kw: (_ for _ in ()).throw(ValueError("bad input")))
    exit_code = run_cli(["laptop"])
    assert exit_code == 1
    assert "bad input" in capsys.readouterr().err


def test_run_cli_maps_playwright_error_to_exit_1(monkeypatch, capsys):
    monkeypatch.setattr(scraper, "scrape", lambda *a, **kw: (_ for _ in ()).throw(PlaywrightError("boom")))
    exit_code = run_cli(["laptop"])
    assert exit_code == 1
    assert "Browser/navigation error" in capsys.readouterr().err


def test_run_cli_maps_keyboard_interrupt_to_exit_130(monkeypatch):
    monkeypatch.setattr(scraper, "scrape", lambda *a, **kw: (_ for _ in ()).throw(KeyboardInterrupt()))
    assert run_cli(["laptop"]) == 130


@pytest.mark.parametrize(
    "text,expected",
    [
        ("laptop", "laptop"),
        ("Tesla Model S", "tesla_model_s"),
        ("iPhone 13 Pro Max!", "iphone_13_pro_max"),
        ("", "query"),
        ("!!!", "query"),
    ],
)
def test_slugify(text, expected):
    assert _slugify(text) == expected
