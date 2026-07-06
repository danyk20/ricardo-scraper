"""Unit tests for the real BrowserSession class itself (as opposed to
FakeBrowserSession, which stands in for it everywhere else). Camoufox and
the browser-pin check are mocked out here so this stays a fast, no-network
unit test rather than an e2e one."""

from unittest.mock import MagicMock, patch

import ricardo_scraper as scraper
from ricardo_scraper import BrowserSession


def _mock_camoufox_stack():
    """Builds the mock chain BrowserSession.__init__ drives: Camoufox(...)
    used as a context manager, whose __enter__ returns a browser, whose
    .new_page() returns a page."""
    fake_page = MagicMock()
    fake_browser = MagicMock()
    fake_browser.new_page.return_value = fake_page
    fake_camoufox = MagicMock()
    fake_camoufox.__enter__.return_value = fake_browser
    return fake_camoufox, fake_browser, fake_page


def test_init_pins_the_browser_and_creates_a_page(monkeypatch):
    ensure_pinned = MagicMock()
    monkeypatch.setattr(scraper, "ensure_pinned_browser", ensure_pinned)
    fake_camoufox, fake_browser, fake_page = _mock_camoufox_stack()

    with patch.object(scraper, "Camoufox", return_value=fake_camoufox) as camoufox_cls:
        session = BrowserSession(headless=True)

    ensure_pinned.assert_called_once()
    camoufox_cls.assert_called_once_with(headless=True, humanize=True)
    assert session.page is fake_page


def test_evaluate_delegates_to_the_page(monkeypatch):
    monkeypatch.setattr(scraper, "ensure_pinned_browser", MagicMock())
    fake_camoufox, fake_browser, fake_page = _mock_camoufox_stack()
    fake_page.evaluate.return_value = {"ok": True}

    with patch.object(scraper, "Camoufox", return_value=fake_camoufox):
        session = BrowserSession()

    assert session.evaluate("1 + 1") == {"ok": True}
    fake_page.evaluate.assert_called_once_with("1 + 1")


def test_close_exits_the_camoufox_context(monkeypatch):
    monkeypatch.setattr(scraper, "ensure_pinned_browser", MagicMock())
    fake_camoufox, fake_browser, fake_page = _mock_camoufox_stack()

    with patch.object(scraper, "Camoufox", return_value=fake_camoufox):
        session = BrowserSession()
        session.close()

    fake_camoufox.__exit__.assert_called_once_with(None, None, None)


def test_context_manager_closes_on_exit(monkeypatch):
    monkeypatch.setattr(scraper, "ensure_pinned_browser", MagicMock())
    fake_camoufox, fake_browser, fake_page = _mock_camoufox_stack()

    with patch.object(scraper, "Camoufox", return_value=fake_camoufox):
        with BrowserSession() as session:
            assert session.page is fake_page

    fake_camoufox.__exit__.assert_called_once()


def test_goto_navigates_and_waits_past_interstitial_title(monkeypatch):
    monkeypatch.setattr(scraper, "ensure_pinned_browser", MagicMock())
    fake_camoufox, fake_browser, fake_page = _mock_camoufox_stack()
    # First title check still says "Just a moment...", second has moved on.
    fake_page.title.side_effect = ["Just a moment...", "Real Page Title"]

    with patch.object(scraper, "Camoufox", return_value=fake_camoufox):
        session = BrowserSession()
        session.goto("https://www.ricardo.ch/de/s/laptop", settle_ms=0)

    fake_page.goto.assert_called_once_with("https://www.ricardo.ch/de/s/laptop", timeout=60000)
    assert fake_page.title.call_count == 2


def test_goto_retries_on_interrupted_navigation_error(monkeypatch):
    from playwright.sync_api import Error as PlaywrightError

    monkeypatch.setattr(scraper, "ensure_pinned_browser", MagicMock())
    fake_camoufox, fake_browser, fake_page = _mock_camoufox_stack()
    fake_page.goto.side_effect = [PlaywrightError("interrupted by another navigation to X"), None]
    fake_page.title.return_value = "Real Page Title"

    with patch.object(scraper, "Camoufox", return_value=fake_camoufox):
        session = BrowserSession()
        session.goto("https://www.ricardo.ch/de/s/laptop", settle_ms=0)

    assert fake_page.goto.call_count == 2


def test_goto_reraises_other_playwright_errors(monkeypatch):
    import pytest
    from playwright.sync_api import Error as PlaywrightError

    monkeypatch.setattr(scraper, "ensure_pinned_browser", MagicMock())
    fake_camoufox, fake_browser, fake_page = _mock_camoufox_stack()
    fake_page.goto.side_effect = PlaywrightError("net::ERR_NAME_NOT_RESOLVED")

    with patch.object(scraper, "Camoufox", return_value=fake_camoufox):
        session = BrowserSession()
        with pytest.raises(PlaywrightError):
            session.goto("https://nonexistent.example", settle_ms=0)
