#!/usr/bin/env python3
"""Interactive Daily Tasks Viewer.

Skim through days, view respective tasks, and edit them in real time in Notion.

Usage:
    python scripts/task_viewer.py                    # browse starting from today
    python scripts/task_viewer.py --date 2026-10-22  # browse starting from a specific date
    python scripts/task_viewer.py --offline          # browse extracted notebook data offline
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from personal_hq.config import EXTRACTION_PATH, PROJECTS_MAPPING_PATH, ConfigError, load_settings  # noqa: E402
from personal_hq.notion_api import NotionGateway  # noqa: E402
from personal_hq.state import State  # noqa: E402
from personal_hq.task_viewer import (  # noqa: E402
    DailyTasksViewer,
    TaskManager,
    create_offline_manager,
    parse_target_date,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Date to open on (YYYY-MM-DD, 'today', 'tomorrow', 'yesterday', or +N/-N; default: today)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run offline using local notebook extraction data without contacting Notion",
    )
    args = parser.parse_args(argv)

    initial_date = parse_target_date(args.date) if args.date else date.today()
    if args.date and not initial_date:
        print(f"Error: Invalid date format {args.date!r}. Expected YYYY-MM-DD.")
        return 2

    if args.offline:
        print("Starting Daily Tasks Viewer in OFFLINE mode (using local extraction data)...")
        manager = create_offline_manager(EXTRACTION_PATH, PROJECTS_MAPPING_PATH)
    else:
        try:
            settings = load_settings(require_token=True)
        except ConfigError as exc:
            print(f"Configuration error: {exc}")
            print("Tip: Run with --offline to browse local notebook extraction data without credentials.")
            return 2

        state = State.load(settings.state_path, read_only=False)
        db_info = state["databases"]
        tasks_info = db_info.get("tasks")
        if not tasks_info or not tasks_info.get("data_source_id"):
            print("Tasks database not found in state. Run create_workspace.py first.")
            return 1

        projects_info = db_info.get("projects") or {}
        gw = NotionGateway(settings.token, settings.notion_version)

        print("Connecting to Notion and loading tasks...")
        manager = TaskManager(
            gw=gw,
            tasks_ds_id=tasks_info["data_source_id"],
            tasks_db_id=tasks_info.get("database_id", ""),
            projects_ds_id=projects_info.get("data_source_id", ""),
            state=state,
        )
        try:
            manager.load()
        except Exception as exc:
            print(f"Failed to load tasks from Notion: {exc}")
            return 1

    app = DailyTasksViewer(manager, initial_date=initial_date)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
