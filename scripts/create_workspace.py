#!/usr/bin/env python3
"""Create the Personal HQ pages, databases, views and dashboard.

    python scripts/create_workspace.py            # dry run: show the plan
    python scripts/create_workspace.py --apply    # make the changes

Safe to rerun: anything that already exists is skipped.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from personal_hq.cli import add_mode_args, run  # noqa: E402
from personal_hq.config import load_settings  # noqa: E402
from personal_hq.workspace_builder import WorkspaceBuilder  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_mode_args(parser)
    args = parser.parse_args(argv)

    def body(gw, state, report):
        parent = load_settings(require_token=False).parent_page_id
        WorkspaceBuilder(gw, parent, state, report).build()

    return run("create_workspace", args, body)


if __name__ == "__main__":
    sys.exit(main())
