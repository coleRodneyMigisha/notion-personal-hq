#!/usr/bin/env python3
"""Keep the review spreadsheet and extraction.json in step.

    python scripts/sync_review_csv.py export   # extraction.json -> data/extracted/items.csv
    python scripts/sync_review_csv.py import   # your edits in items.csv -> extraction.json

Edit items.csv in LibreOffice/Excel (keep the item_id column unchanged), then
run `import`. Only the editable columns below are copied back; a backup of
extraction.json is written first.
"""
import argparse
import csv
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from personal_hq.config import EXTRACTION_PATH  # noqa: E402

CSV_PATH = EXTRACTION_PATH.parent / "items.csv"
COLUMNS = ["item_id", "page_date", "section", "parent_item_id", "text", "box_mark", "proposed_status",
           "struck_through", "carried_marker", "ink", "time_noted", "annotation", "proposed_area",
           "proposed_thread", "uncertain", "uncertainty_note", "source_file"]
EDITABLE = ["text", "box_mark", "proposed_status", "carried_marker", "time_noted", "annotation",
            "proposed_area", "proposed_thread", "uncertain", "uncertainty_note"]
BOOLEAN = {"struck_through", "carried_marker", "uncertain"}


def export(data: dict) -> None:
    dates = {p["page_id"]: p["date_iso"] or p["date_written"] for p in data["pages"]}
    with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for item in data["items"]:
            writer.writerow({**item, "page_date": dates[item["page_id"]]})
    print(f"Wrote {len(data['items'])} rows to {CSV_PATH}")


def import_csv(data: dict) -> None:
    by_id = {i["item_id"]: i for i in data["items"]}
    changes = 0
    with open(CSV_PATH, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            item = by_id.get(row["item_id"])
            if not item:
                print(f"  unknown item_id {row['item_id']!r} - ignored")
                continue
            for col in EDITABLE:
                raw = row.get(col, "")
                value = raw.strip().lower() in ("true", "1", "yes", "y") if col in BOOLEAN else (raw or None)
                if item.get(col) != value:
                    print(f"  {item['item_id']}.{col}: {item.get(col)!r} -> {value!r}")
                    item[col] = value
                    changes += 1
    if not changes:
        print("No changes found.")
        return
    backup = EXTRACTION_PATH.with_suffix(f".backup-{datetime.now():%Y%m%d-%H%M%S}.json")
    shutil.copy2(EXTRACTION_PATH, backup)
    EXTRACTION_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Applied {changes} change(s). Backup: {backup}. Now run scripts/validate_data.py.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("direction", choices=["export", "import"])
    args = parser.parse_args(argv)
    data = json.loads(EXTRACTION_PATH.read_text(encoding="utf-8"))
    export(data) if args.direction == "export" else import_csv(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
