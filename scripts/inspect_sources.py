#!/usr/bin/env python3
"""Phase 1: count and open the screenshots in a folder and write a manifest.

    python scripts/inspect_sources.py ~/Pictures/goal-notes --expected 32

Exit code 0 when at least the expected number of distinct, readable images
was found; 1 otherwise (and the missing/unreadable files are listed).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from personal_hq.config import PROJECT_ROOT  # noqa: E402
from personal_hq.sources import inspect_folder, summarise, write_manifest  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path, help="Folder containing the screenshots")
    parser.add_argument("--expected", type=int, default=32, help="How many screenshots you expect (default 32)")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "data" / "manifests" / "inspection_manifest.csv")
    args = parser.parse_args(argv)

    if not args.folder.is_dir():
        print(f"Folder not found: {args.folder}")
        return 2
    results = inspect_folder(args.folder)
    summary = summarise(results, args.expected)
    write_manifest(results, args.out)

    for r in results:
        print(f"  {r.status:<11} {r.source_file}" + (f"  - {r.issue}" if r.issue else ""))
    print(f"\nExpected {summary['expected']}, inspected {summary['inspected']} distinct readable images.")
    if summary["duplicates"]:
        print(f"Exact duplicates ignored: {len(summary['duplicates'])}")
    if summary["unreadable"]:
        print(f"Could not open: {', '.join(summary['unreadable'])}")
    if summary["missing"]:
        print(f"MISSING: {summary['missing']} screenshot(s). Add them to the folder and rerun.")
    if summary["extra"]:
        print(f"Note: {summary['extra']} more than expected - check whether the expected count is right.")
    print(f"Manifest written to {args.out}")
    return 0 if summary["complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
