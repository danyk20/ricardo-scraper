"""End-to-end tests: real calls against ricardo.ch through a real camoufox
browser. Marked `@pytest.mark.e2e` and excluded by default (see
pyproject.toml's addopts) -- run explicitly with `pytest -m e2e --no-cov`
to confirm the scraper still works against the live site. A small
`max_results` (rather than a small-inventory query, the trick AutoScout24's
e2e suite uses) keeps these fast and light regardless of how many listings
actually match "laptop" on any given day.
"""

import subprocess
import sys

import pytest

from ricardo_scraper import scrape

pytestmark = pytest.mark.e2e


def test_scrape_real_site_detail_mode():
    result = scrape("laptop", max_results=2, verbose=False)

    assert result.total_elements >= 2
    assert len(result.rows) == len(result.listings) == 2
    for row in result.rows:
        assert row["price"] is None or row["price"] > 0
        assert row["url"].startswith("https://www.ricardo.ch/de/a/")


def test_scrape_real_site_no_detail_mode():
    result = scrape("laptop", max_results=2, detail=False, verbose=False)

    assert len(result.listings) == 2
    assert all("image" in item for item in result.listings)


def test_cli_subprocess_real_run(tmp_path):
    """Exercises the `if __name__ == "__main__":` guard for real (that line
    is excluded from the unit-suite coverage requirement precisely because
    it's covered here instead, not because it's untested)."""
    out_base = tmp_path / "e2e_laptop"
    proc = subprocess.run(
        [sys.executable, "ricardo_scraper.py", "laptop", "--max-results", "2", "--out", str(out_base)],
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert proc.returncode == 0, proc.stderr
    assert out_base.with_suffix(".csv").exists()
    assert out_base.with_suffix(".json").exists()


def test_cli_subprocess_real_error_exit_code():
    proc = subprocess.run(
        [sys.executable, "ricardo_scraper.py", "laptop", "--price-from", "500", "--price-to", "10"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 1
    assert "price_from" in proc.stderr
