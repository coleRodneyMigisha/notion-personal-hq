#!/usr/bin/env python3
"""Read-only check that your integration can see the Personal HQ page.

    python scripts/check_access.py

Makes two read requests (page + its children) and changes nothing.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from personal_hq.config import ConfigError, load_settings  # noqa: E402
from personal_hq.notion_api import NotionError, NotionGateway  # noqa: E402
from personal_hq.workspace_builder import page_title  # noqa: E402


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Configuration problem: {exc}")
        return 2
    print(f"Parent page ID (from NOTION_PARENT_PAGE): {settings.parent_page_id}")
    gw = NotionGateway(settings.token, settings.notion_version)
    try:
        page = gw.retrieve_page(settings.parent_page_id)
        children = list(gw.iter_children(settings.parent_page_id))
    except NotionError as exc:
        print(f"NO ACCESS: {exc}")
        return 1
    if page.get("in_trash"):
        print("The page is in Notion's trash. Restore it first.")
        return 1
    print(f"OK - the integration can read {page_title(page)!r}.")
    print(f"It currently has {len(children)} top-level block(s); the scripts will only ever append after them.")
    kinds = {}
    for block in children:
        kinds[block["type"]] = kinds.get(block["type"], 0) + 1
    if kinds:
        print("Existing content:", ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
