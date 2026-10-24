#!/usr/bin/env python3
"""Optional helper: create next week's page in the Weeks database.

    python scripts/new_week.py --apply                    # the week after today
    python scripts/new_week.py --date 2026-11-02 --apply  # the week containing that date

You can do the same by hand in Notion (Weeks > New); this just saves typing.
Running it twice for the same week does nothing the second time.
"""
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from personal_hq.cli import add_mode_args, run  # noqa: E402
from personal_hq.data_mapper import Record, date_prop, rich, title  # noqa: E402
from personal_hq.importer import Importer  # noqa: E402


def week_record(day: date) -> Record:
    monday = day - timedelta(days=day.weekday())
    sunday = monday + timedelta(days=6)
    label = f"Week of {monday:%d %b} - {sunday:%d %b %Y}"
    iid = f"W{monday.isoformat()}"
    return Record("weeks", iid, label, {"Week": title(label), "Dates": date_prop(monday.isoformat(), sunday.isoformat()),
                                         "Import ID": rich(iid)})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_mode_args(parser)
    parser.add_argument("--date", type=date.fromisoformat, help="Any date in the target week (default: next week)")
    args = parser.parse_args(argv)
    target = args.date or date.today() + timedelta(days=7)

    def body(gw, state, report):
        Importer(gw, state, report).run({"weeks": [week_record(target)]}, only=["weeks"])

    return run("new_week", args, body)


if __name__ == "__main__":
    sys.exit(main())
