# Contributing

Thanks for considering a contribution — human or AI agent, both welcome (see
the [License](README.md#license) section of the README).

## Dev setup

```bash
git clone https://github.com/danyk20/ricardo-scraper.git
cd ricardo-scraper
pipenv install --dev
```

## Before opening a PR

```bash
pipenv run ruff check .            # lint
pipenv run ruff format .           # format
pipenv run mypy ricardo_scraper.py # type-check
pipenv run pytest                  # unit tests, must stay at 100% coverage
```

If your change touches browser navigation or JSON-LD parsing against the
real site, also run the end-to-end suite (real network calls, real
browser, ~30s):

```bash
pipenv run pytest -m e2e --no-cov
```

## Expectations

- **Every behavior change needs a test.** The unit suite mocks the browser
  layer entirely (via `FakeBrowserSession` in `tests/conftest.py`) and
  enforces 100% coverage of `ricardo_scraper.py` — a change without a test
  will fail CI on that basis alone.
- **Keep `verbose`/logging output backward compatible** unless the PR is
  specifically about changing it — other code (and the e2e/CLI tests)
  depends on the current message wording.
- If ricardo.ch changes its page structure, prefer fixing the affected
  function directly over adding a workaround — the module docstring in
  `ricardo_scraper.py` documents the current search/detail page shapes.
- Keep the change minimal and focused; this is a small utility by design
  (see the README's [Notes](README.md#notes) section for what's
  intentionally out of scope, e.g. real server-side price/category
  filtering, concurrency, a database layer).
- If you touch `pin_camoufox_browser.py`'s pinned build, re-verify the new
  build against ricardo.ch first — see that module's docstring for why
  "latest" isn't safe to trust here.

## Questions / bug reports

Open a GitHub issue using the bug report template — include the exact
command you ran and, if relevant, the browser console/network output you
got back (`--show-browser` and `-v` help here).

## Releasing (maintainer only)

Publishing to PyPI is automated via `.github/workflows/release.yml` using
PyPI Trusted Publishing (no API tokens stored anywhere) — pushing a tag is
the only manual step:

1. Bump `__version__` in `ricardo_scraper.py`.
2. Add a new entry at the top of `CHANGELOG.md` (Keep a Changelog format).
3. Commit those two changes, then tag and push:
   ```bash
   git commit -am "Release vX.Y.Z"
   git tag vX.Y.Z
   git push origin master
   git push origin vX.Y.Z
   ```
4. The release workflow verifies `__version__` matches the tag (fails fast
   if they disagree), builds, publishes to TestPyPI, then to real PyPI.
   Watch the Actions tab.
5. To dry-run the pipeline without a real release, push a pre-release tag
   instead (e.g. `vX.Y.Z-rc1`) — it publishes to TestPyPI only and never
   reaches real PyPI, since the version/tag check and the real-PyPI job
   both key off an exact `vX.Y.Z` tag.

One-time setup this depends on (see the maintainer's own notes for
confirmation it's done): a Trusted Publisher registered on both pypi.org
and test.pypi.org for this repo, and matching GitHub Environments named
`pypi`/`testpypi`.
