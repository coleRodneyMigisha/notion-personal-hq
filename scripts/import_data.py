#!/usr/bin/env python3
"""Import the reviewed notebook extraction into the databases.

    python scripts/import_data.py                     # dry run
    python scripts/import_data.py --apply             # create missing records
    python scripts/import_data.py --apply --update    # also overwrite records that differ
    python scripts/import_data.py --only tasks notes  # limit to some databases

Records are matched by their Import ID, so reruns never duplicate anything.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from personal_hq.cli import add_mode_args, load_inputs, run  # noqa: E402
from personal_hq.data_mapper import IMPORT_ORDER, Mapper  # noqa: E402
from personal_hq.importer import Importer  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_mode_args(parser)
    parser.add_argument("--update", action="store_true",
                        help="Overwrite Notion records whose values differ from the source data")
    parser.add_argument("--only", nargs="+", choices=IMPORT_ORDER)
    args = parser.parse_args(argv)

    def body(gw, state, report):
        extraction, projects = load_inputs()
        records = Mapper(extraction, projects).build()
        Importer(gw, state, report, update=args.update).run(records, only=args.only)

    return run("import_data", args, body)


if __name__ == "__main__":
    sys.exit(main())
