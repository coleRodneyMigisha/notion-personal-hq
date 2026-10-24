#!/usr/bin/env python3
"""Refresh the Contribution Calendar from Tasks marked Done.

Aggregates by the 'Completed on' date when present, otherwise Planned.
Idempotent via Import ID = contrib-YYYY-MM-DD.

    python scripts/update_contribution_calendar.py          # dry-run
    python scripts/update_contribution_calendar.py --apply  # write
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from personal_hq.cli import add_mode_args, run  # noqa: E402
from personal_hq.notion_api import plain_text  # noqa: E402
from personal_hq.report import Report  # noqa: E402
from personal_hq.state import State  # noqa: E402

log = logging.getLogger("personal_hq")
Json = dict[str, Any]


def level_for(count: int) -> str:
    """GitHub-style intensity buckets."""
    if count <= 0:
        return "None"
    if count <= 2:
        return "Low"
    if count <= 5:
        return "Medium"
    if count <= 8:
        return "High"
    return "Very High"


def parse_date(val: Any) -> date | None:
    if not val:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    s = str(val)[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _title(text: str) -> Json:
    return {"title": [{"type": "text", "text": {"content": text[:2000]}}]}


def _rich(text: str) -> Json:
    return {"rich_text": [{"type": "text", "text": {"content": text[:2000]}}]}


def _date(d: date) -> Json:
    return {"date": {"start": d.isoformat()}}


def _number(n: int) -> Json:
    return {"number": n}


def _select(name: str) -> Json:
    return {"select": {"name": name}}


def body(gw: Any, state: State, report: Report) -> None:
    db_info = state["databases"]
    tasks_info = db_info.get("tasks")
    contrib_info = db_info.get("contribution_calendar")

    if not tasks_info or not tasks_info.get("data_source_id"):
        report.note("Tasks database not found in state. Run create_workspace first.")
        return
    if not contrib_info or not contrib_info.get("data_source_id"):
        report.note(
            "Contribution Calendar not found in state.\n"
            "  1. Add the DatabaseSpec to schema.py\n"
            "  2. Run: python scripts/create_workspace.py --apply\n"
            "  (Or the database already exists in Notion from the connector;\n"
            "   record its data_source_id under state['databases']['contribution_calendar'].)"
        )
        return

    tasks_ds = tasks_info["data_source_id"]
    contrib_ds = contrib_info["data_source_id"]
    contrib_db_id = contrib_info.get("database_id")

    # 1. Query Done tasks
    log.info("Querying Done tasks…")
    filter_ = {"property": "Status", "select": {"equals": "Done"}}
    pages = list(gw.query_data_source(tasks_ds, filter=filter_))
    log.info("Found %d Done tasks", len(pages))
    report.note(f"Done tasks found: {len(pages)}")

    # 2. Aggregate by day (prefer Completed on, else Planned)
    counts: dict[date, int] = defaultdict(int)
    for p in pages:
        props = p.get("properties", {})
        d = None
        for key in ("Completed on", "Planned"):
            prop = props.get(key) or {}
            if prop.get("type") == "date" and prop.get("date"):
                d = parse_date(prop["date"].get("start"))
                if d:
                    break
        if d:
            counts[d] += 1

    if not counts:
        report.note("No dated completed tasks found – nothing to do.")
        return

    # 3. Existing contribution pages by Import ID
    existing: dict[str, str] = {}
    for p in gw.query_data_source(contrib_ds):
        props = p.get("properties", {})
        iid_prop = props.get("Import ID") or {}
        iid = plain_text(iid_prop.get("rich_text") or iid_prop.get("title") or [])
        if iid:
            existing[iid] = p["id"]

    created = updated = 0
    for day, cnt in sorted(counts.items()):
        import_id = f"contrib-{day.isoformat()}"
        level = level_for(cnt)
        props = {
            "Day": _title(day.isoformat()),
            "Date": _date(day),
            "Completed": _number(cnt),
            "Level": _select(level),
            "Import ID": _rich(import_id),
        }
        if import_id in existing:
            gw.update_page(existing[import_id], props)
            updated += 1
            state.record("contribution_calendar", import_id, existing[import_id])
        else:
            parent = {"database_id": contrib_db_id} if contrib_db_id else {"data_source_id": contrib_ds}
            # Prefer data_source parent when available (newer API)
            try:
                page = gw.create_page({"parent": {"data_source_id": contrib_ds}, "properties": props})
            except Exception:
                page = gw.create_page({"parent": parent, "properties": props})
            created += 1
            if page and page.get("id"):
                state.record("contribution_calendar", import_id, page["id"])

    report.note(f"Days with activity : {len(counts)}")
    report.note(f"Created / Updated  : {created} / {updated}")
    report.note(f"Date range         : {min(counts)} → {max(counts)}")
    report.note(f"Max in one day     : {max(counts.values())}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    add_mode_args(parser)
    args = parser.parse_args(argv)
    return run("update_contribution_calendar", args, body)


if __name__ == "__main__":
    sys.exit(main())
