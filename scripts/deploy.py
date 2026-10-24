#!/usr/bin/env python3
"""Workspace + import in one go (what you run the first time).

    python scripts/deploy.py              # dry run of everything
    python scripts/deploy.py --offline    # same, without contacting Notion
    python scripts/deploy.py --apply      # build the workspace and import the data
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from personal_hq.cli import add_mode_args, load_inputs, run  # noqa: E402
from personal_hq.config import load_settings  # noqa: E402
from personal_hq.data_mapper import Mapper  # noqa: E402
from personal_hq.importer import Importer  # noqa: E402
from personal_hq.workspace_builder import WorkspaceBuilder  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_mode_args(parser)
    args = parser.parse_args(argv)

    def body(gw, state, report):
        extraction, projects = load_inputs()   # validate before any write
        parent = load_settings(require_token=False).parent_page_id
        WorkspaceBuilder(gw, parent, state, report).build()
        Importer(gw, state, report).run(Mapper(extraction, projects).build())

    return run("deploy", args, body)


if __name__ == "__main__":
    sys.exit(main())
