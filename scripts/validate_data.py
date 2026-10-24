#!/usr/bin/env python3
"""Check data/extracted/extraction.json before importing it.

    python scripts/validate_data.py [--images /path/to/screenshots]
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from personal_hq.config import EXTRACTION_PATH, PROJECTS_MAPPING_PATH  # noqa: E402
from personal_hq.data_mapper import Mapper  # noqa: E402
from personal_hq.validation import validate_extraction  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--extraction", type=Path, default=EXTRACTION_PATH)
    parser.add_argument("--projects", type=Path, default=PROJECTS_MAPPING_PATH)
    parser.add_argument("--images", type=Path, help="Also check every source image exists in this folder")
    parser.add_argument("--show-warnings", action="store_true")
    args = parser.parse_args(argv)

    extraction = json.loads(args.extraction.read_text(encoding="utf-8"))
    projects = json.loads(args.projects.read_text(encoding="utf-8"))
    errors, warnings = validate_extraction(extraction, projects, args.images)

    print(f"Pages: {len(extraction['pages'])}   items: {len(extraction['items'])}")
    print("Sections:", dict(Counter(i["section"] for i in extraction["items"])))
    print("Proposed status:", dict(Counter(i["proposed_status"] for i in extraction["items"])))
    print(f"Flagged uncertain: {sum(1 for i in extraction['items'] if i.get('uncertain'))}")
    if not errors:
        records = Mapper(extraction, projects).build()
        print("Records to import:", {db: len(r) for db, r in records.items()})
    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    for e in errors:
        print(f"  ERROR   {e}")
    for w in warnings if args.show_warnings else warnings[:5]:
        print(f"  warning {w}")
    if len(warnings) > 5 and not args.show_warnings:
        print(f"  ... {len(warnings) - 5} more (use --show-warnings)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
