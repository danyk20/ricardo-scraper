#!/usr/bin/env python3
"""Regenerate docs/categories.json, docs/CATEGORIES.md and ricardo_categories.py
from ricardo.ch's live category tree.

ricardo.ch's own frontend loads its full category taxonomy from
`/api/mfa/categories?locale=<locale>` -- a flat JSON list of every category
(`categoryId`, `displayName`, `slug`, `parentId`), not just the two levels
the site's category menu shows. Like every other ricardo.ch URL it sits
behind Cloudflare, so it's fetched from inside a real `BrowserSession`
(after one ordinary page load has passed the challenge) rather than with a
plain HTTP client.

Three outputs, from the same data:

- `docs/categories.json`: the canonical, machine-readable list -- one
  category per line (greppable, diff-friendly), each with its id, name,
  slug, parent id, depth and full path.
- `docs/CATEGORIES.md`: the same list rendered for humans, one table per
  top-level category.
- `ricardo_categories.py`: just id -> (slug, parent id), as an importable
  module shipped with the package -- ricardo_scraper uses it to rebuild a
  listing's full category ancestry, which ricardo.ch's own JSON-LD
  breadcrumbs cut off after three levels.

Ricardo changes its taxonomy now and then; rerun this to refresh both files.

Usage: pipenv run python update_categories.py
"""

import argparse
import datetime
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from ricardo_scraper import BASE_URL, DEFAULT_LOCALE, BrowserSession, _configure_cli_logging, logger

CATEGORIES_API = "/api/mfa/categories?locale={locale}"
DOCS_DIR = Path(__file__).parent / "docs"
JSON_PATH = DOCS_DIR / "categories.json"
MARKDOWN_PATH = DOCS_DIR / "CATEGORIES.md"
MODULE_PATH = Path(__file__).parent / "ricardo_categories.py"
PATH_SEPARATOR = " > "

# Fetched from inside the page so the request carries the Cloudflare
# clearance cookies the preceding navigation earned.
_FETCH_JS = """
async (url) => {
  const response = await fetch(url);
  return {status: response.status, body: await response.text()};
}
"""


def fetch_categories(session: BrowserSession, locale: str = DEFAULT_LOCALE) -> list[dict[str, Any]]:
    """Return ricardo.ch's raw category list, as its own frontend sees it."""
    session.goto(f"{BASE_URL}/{locale}/")
    result = session.page.evaluate(_FETCH_JS, CATEGORIES_API.format(locale=locale))
    if result["status"] != 200:
        raise RuntimeError(f"category API returned HTTP {result['status']}")
    return json.loads(result["body"])


def _sort_key(name: str) -> str:
    """Alphabetical order that files umlauts with their base letter (Ä with A)."""
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().casefold()


def build_tree(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn the API's flat parent-pointer list into a depth-first ordered list
    (each parent directly followed by its subtree, siblings alphabetical),
    with each category's depth (0 = top level) and full name path filled in.

    Raises ValueError if a category's parent isn't in the list -- a partial
    response is better caught here than published as a silently truncated tree.
    """
    by_id = {c["categoryId"]: c for c in raw}
    children: dict[int | None, list[dict[str, Any]]] = {}
    for c in raw:
        parent_id = c.get("parentId")
        if parent_id is not None and parent_id not in by_id:
            raise ValueError(f"category {c['categoryId']} has unknown parent {parent_id}")
        children.setdefault(parent_id, []).append(c)

    ordered: list[dict[str, Any]] = []

    def walk(parent_id: int | None, path: list[str]) -> None:
        for c in sorted(children.get(parent_id, []), key=lambda c: _sort_key(c["displayName"])):
            name = " ".join(c["displayName"].split())  # the API has stray double spaces
            ordered.append(
                {
                    "id": c["categoryId"],
                    "name": name,
                    "slug": c["slug"],
                    "parent_id": parent_id,
                    "depth": len(path),
                    "path": PATH_SEPARATOR.join([*path, name]),
                }
            )
            walk(c["categoryId"], [*path, name])

    walk(None, [])
    return ordered


def render_json(categories: list[dict[str, Any]], locale: str, generated: datetime.date) -> str:
    """Pretty-print the header fields, but keep each category on one line so
    `grep 39272 docs/categories.json` returns a complete, self-describing record."""
    lines = ",\n".join(f"    {json.dumps(c, ensure_ascii=False)}" for c in categories)
    return (
        "{\n"
        f'  "source": {json.dumps(BASE_URL + CATEGORIES_API.format(locale=locale))},\n'
        f'  "locale": {json.dumps(locale)},\n'
        f'  "generated": "{generated.isoformat()}",\n'
        f'  "count": {len(categories)},\n'
        f'  "categories": [\n{lines}\n  ]\n'
        "}\n"
    )


def render_python_module(categories: list[dict[str, Any]], generated: datetime.date) -> str:
    """Emit ricardo_categories.py, already in `ruff format` style (one entry
    per line, kept expanded by the trailing comma)."""
    entries = "".join(f'    {c["id"]}: ("{c["slug"]}", {c["parent_id"]}),\n' for c in categories)
    return (
        f'"""Generated by update_categories.py on {generated.isoformat()} -- do not edit by hand.\n'
        "\n"
        "Every ricardo.ch category id mapped to its (slug, parent id), parent id None\n"
        "for a top-level category. ricardo_scraper uses it to rebuild a listing's full\n"
        "category ancestry, which ricardo.ch's JSON-LD breadcrumbs cut off after three\n"
        "levels -- see docs/CATEGORIES.md for the same data in readable form.\n"
        '"""\n'
        "\n"
        f"CATEGORIES: dict[int, tuple[str, int | None]] = {{\n{entries}}}\n"
    )


def _github_anchor(heading: str) -> str:
    """The fragment GitHub generates for a Markdown heading."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def render_markdown(categories: list[dict[str, Any]], generated: datetime.date) -> str:
    roots = [c for c in categories if c["depth"] == 0]
    descendant_counts = {r["id"]: 0 for r in roots}
    root_of: dict[int, int] = {}
    for c in categories:
        root_id = c["id"] if c["depth"] == 0 else root_of[c["parent_id"]]
        root_of[c["id"]] = root_id
        if c["depth"]:
            descendant_counts[root_id] += 1
    max_depth = max(c["depth"] for c in categories)
    # Stats for the "prefer the ID" advice below, computed so they stay true after a regeneration.
    slug_words = Counter(w for c in categories for w in set(re.sub(r"-\d+$", "", c["slug"]).split("-")))
    (word1, count1), (word2, count2) = slug_words.most_common(2)
    repeated_name, repeat_count = Counter(c["name"] for c in categories).most_common(1)[0]

    out = [
        "# Ricardo categories",
        "",
        f"<!-- Generated by update_categories.py on {generated.isoformat()} -- do not edit by hand. -->",
        "",
        f"Every ricardo.ch category, all {len(categories)} of them ({len(roots)} top-level, nested up to "
        f"{max_depth + 1} levels deep), as of {generated.isoformat()} — these are the values `--category` / "
        "`scrape(category=...)` can match. Names and slugs are German (`de`), the scraper's default locale.",
        "",
        "Machine-readable copy (same data, one category per line, with `parent_id`/`depth`/full `path`): "
        "[`categories.json`](categories.json). Both files are regenerated by "
        "`pipenv run python update_categories.py` — Ricardo changes its taxonomy now and then.",
        "",
        "## Using a category with `--category`",
        "",
        "- **Prefer the numeric ID.** `--category 39272` is unambiguous. A name is matched against the words "
        "of each breadcrumb slug, so a common word matches many unrelated categories "
        f"(`{word1}` appears in {count1} slugs, `{word2}` in {count2}), and names repeat across branches "
        f"(there are {repeat_count} categories called *{repeated_name}*).",
        "- **A category matches its whole subtree.** `--category 63788` (*Büro & Gewerbe*) also keeps listings "
        "filed anywhere below it, however deep. A listing's own breadcrumbs only name its category and its two "
        "nearest ancestors (a listing in *Büro & Gewerbe > Agrar, Forst & Bauen > Erntetechnik > Pressen / "
        "Wickeln & Zubehör > Pressen-&Wickelnzubehör* carries just `pressen-wickelnzubehoer-82351`, "
        "`pressen-wickeln-zubehoer-79697` and `erntetechnik-79687`), so the scraper rebuilds the rest of the path "
        "from the snapshot of this list it ships with (`ricardo_categories.py`). The same goes for names: a name "
        "also matches every category below one whose slug contains it. A listing in a category newer than the "
        "snapshot falls back to its breadcrumbs (2 levels up). Rerun `update_categories.py` to refresh it.",
        "- **Category is a client-side filter** that needs detail mode, so it narrows what you get back but not "
        "what is visited. Pair it with a search query that already targets the category. See "
        "[REFERENCE.md](REFERENCE.md#detail-mode).",
        "- *Angebote der Saison* (`82435`) is a seasonal storefront (Halloween, Black Friday, …), not a real "
        "branch. Its listings carry their regular category breadcrumbs, so it won't match anything as a filter.",
        "",
        "## Top-level categories",
        "",
        "| ID | Category | Subcategories |",
        "|---:|---|---:|",
    ]
    sections = []
    for root in roots:
        heading = f"{root['name']} ({root['id']})"
        out.append(f"| {root['id']} | [{root['name']}](#{_github_anchor(heading)}) | {descendant_counts[root['id']]} |")
        sections.append(heading)

    by_root: dict[int, list[dict[str, Any]]] = {r["id"]: [] for r in roots}
    for c in categories:
        by_root[root_of[c["id"]]].append(c)
    for root, heading in zip(roots, sections, strict=True):
        out += ["", f"## {heading}", "", "| ID | Depth | Category | Slug |", "|---:|---:|---|---|"]
        for c in by_root[root["id"]]:
            out.append(f"| {c['id']} | {c['depth']} | {c['path']} | `{c['slug']}` |")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate docs/categories.json, docs/CATEGORIES.md and ricardo_categories.py."
    )
    parser.add_argument("--show-browser", action="store_true", help="Show the browser window instead of headless")
    args = parser.parse_args(argv)
    _configure_cli_logging(verbose=False, quiet=False)

    with BrowserSession(headless=not args.show_browser) as session:
        raw = fetch_categories(session)
    categories = build_tree(raw)
    today = datetime.date.today()
    JSON_PATH.write_text(render_json(categories, DEFAULT_LOCALE, today), encoding="utf-8")
    MARKDOWN_PATH.write_text(render_markdown(categories, today), encoding="utf-8")
    MODULE_PATH.write_text(render_python_module(categories, today), encoding="utf-8")
    logger.info("wrote %d categories to %s, %s and %s", len(categories), JSON_PATH, MARKDOWN_PATH, MODULE_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
