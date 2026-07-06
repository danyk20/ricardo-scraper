#!/usr/bin/env python3
"""Install and enforce a specific, known-good camoufox browser build.

`camoufox fetch` (the tool's own installer) picks the newest release its
installed pip package considers "supported" -- but that version check
compares release labels lexicographically (e.g. "alpha" < "beta" as plain
strings), so it skips past every current "alpha.N" release and falls back
to whatever "beta"-labeled build it finds, which on this project turned out
to be a ~1.5 year old build (v135.0.1-beta.24) with a bug: it crashes the
Playwright Node driver on any page that throws an uncaught JS error without
a `location` field -- which ricardo.ch's frontend does. Reproduced with a
bare `page.goto("https://www.ricardo.ch/de/s/laptop")`, no scraper logic
involved.

Camoufox also auto-reinstalls on its own initiative: launching a browser
calls camoufox_path(download_if_missing=True) internally, which silently
runs the same broken "latest supported" install if it ever decides the
cached build doesn't satisfy its version range -- no `camoufox fetch`
required to trigger it. `ensure_pinned_browser()` is called from
scraper.py before every run specifically to preempt that: it checks the
cache against VERSION/RELEASE below and only reinstalls if they don't
match, so camoufox's own fetch logic never gets a chance to run.

Usage: pipenv run python pin_camoufox_browser.py [--force]
"""

import argparse
import io
import os
import platform
import shlex
import sys
import zipfile
from pathlib import Path

import orjson
import requests
from platformdirs import user_cache_dir

# Known-good build, verified against ricardo.ch. Update these together if
# you deliberately move to a newer build (and re-verify against the target
# site first -- see the module docstring for why "latest" isn't safe here).
VERSION = "152.0.4"
RELEASE = "zeta.1"  # arbitrary label that sorts as "supported" (see below)
ASSET_URLS = {
    ("darwin", "arm64"): (
        "https://github.com/daijro/camoufox/releases/download/v152.0.2-alpha/camoufox-152.0.4-alpha.25-mac.arm64.zip"
    ),
}


def _install_dir() -> Path:
    return Path(user_cache_dir("camoufox"))


def is_pinned_build_installed() -> bool:
    """Check whether the cache already holds exactly VERSION/RELEASE."""
    install_dir = _install_dir()
    version_file = install_dir / "version.json"
    if not version_file.exists():
        return False
    try:
        data = orjson.loads(version_file.read_bytes())
    except orjson.JSONDecodeError:
        return False
    if data.get("version") != VERSION or data.get("release") != RELEASE:
        return False
    # Guard against a version.json that claims the pin but a binary that
    # was never actually extracted (e.g. an interrupted install).
    if sys.platform == "darwin":
        return (install_dir / "Camoufox.app").exists()
    return any(install_dir.iterdir())


def install_pinned_build() -> None:
    key = (sys.platform, platform.machine().lower())
    if key not in ASSET_URLS:
        sys.exit(
            f"No pinned build recorded for {key}. Add an entry to ASSET_URLS "
            f"in this script (find the right asset at "
            f"https://github.com/daijro/camoufox/releases and verify it "
            f"against the target site before pinning)."
        )
    url = ASSET_URLS[key]

    install_dir = _install_dir()
    print(f"Downloading {url}")
    resp = requests.get(url, stream=True)
    resp.raise_for_status()
    buf = io.BytesIO(resp.content)

    print(f"Installing to {install_dir}")
    install_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(buf) as zf:
        zf.extractall(install_dir)

    if sys.platform != "win32":
        os.system(f"chmod -R 755 {shlex.quote(str(install_dir))}")  # nosec

    # RELEASE is deliberately NOT the upstream "alpha.25" label: camoufox's
    # Version comparison treats the release string's first letter as a sort
    # key (ord(letter)), and "alpha" sorts below the package's configured
    # minimum ("beta.19"), so the real label would make camoufox consider
    # this build "outdated" and try to replace it. "zeta.1" sorts above
    # "beta.19" and below the max-version sentinel, so it's accepted.
    (install_dir / "version.json").write_bytes(orjson.dumps({"version": VERSION, "release": RELEASE}))
    print(f"Pinned camoufox browser to {VERSION}-{RELEASE} (upstream alpha.25).")


def ensure_pinned_browser(force: bool = False) -> bool:
    """Install the pinned build if it isn't already in place. Returns True
    if an install happened, False if the correct build was already there."""
    if not force and is_pinned_build_installed():
        return False
    install_pinned_build()
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Reinstall even if already pinned")
    args = parser.parse_args()

    if ensure_pinned_browser(force=args.force):
        pass  # install_pinned_build() already printed its own summary
    else:
        print(f"Already pinned to {VERSION}-{RELEASE} (upstream alpha.25) -- nothing to do.")


if __name__ == "__main__":
    main()
