"""Shared plumbing for the scripts in scripts/: modes, gateway, error handling."""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Callable

from .config import EXTRACTION_PATH, PROJECTS_MAPPING_PATH, ConfigError, Settings, load_settings
from .notion_api import DryRunGateway, NotionError, NotionGateway
from .report import Report, setup_logging
from .state import State
from .validation import validate_extraction
from .workspace_builder import AccessError

log = logging.getLogger("personal_hq")


def add_mode_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--apply", action="store_true",
                        help="Actually write to Notion. Without this flag the run is a dry run.")
    parser.add_argument("--offline", action="store_true",
                        help="Dry run without contacting Notion (no token needed). Plans as if starting fresh.")


def make_gateway(settings: Settings, args: argparse.Namespace) -> Any:
    if args.offline:
        return DryRunGateway(None)
    real = NotionGateway(settings.token, settings.notion_version)
    return real if args.apply else DryRunGateway(real)


def load_inputs(extraction_path: Path = EXTRACTION_PATH,
                projects_path: Path = PROJECTS_MAPPING_PATH) -> tuple[dict, dict]:
    extraction = json.loads(Path(extraction_path).read_text(encoding="utf-8"))
    projects = json.loads(Path(projects_path).read_text(encoding="utf-8"))
    errors, warnings = validate_extraction(extraction, projects)
    for w in warnings:
        log.debug(f"validation warning: {w}")
    if errors:
        raise ValueError("Extraction failed validation; run scripts/validate_data.py:\n  " + "\n  ".join(errors[:20]))
    return extraction, projects


def run(name: str, args: argparse.Namespace, body: Callable[[Any, State, Report], None]) -> int:
    """Load settings, build the gateway, run `body`, always print and save a report."""
    if args.apply and args.offline:
        print("--apply and --offline cannot be combined.")
        return 2
    try:
        settings = load_settings(require_token=not args.offline)
    except ConfigError as exc:
        print(f"Configuration problem: {exc}")
        return 2
    log_file = setup_logging(settings.log_dir, name)
    dry_run = not args.apply
    log.info(f"{name}: {'DRY RUN (no changes will be made)' if dry_run else 'APPLY MODE (writing to Notion)'}"
             f"{' - offline' if args.offline else ''}")
    gw = make_gateway(settings, args)
    state = State.load(settings.state_path, read_only=dry_run)
    report = Report(name, dry_run=dry_run)
    code = 0
    try:
        body(gw, state, report)
    except AccessError as exc:
        log.error(f"\nSTOPPED: {exc}")
        code = 2
    except NotionError as exc:
        log.error(f"\nSTOPPED by a Notion error: {exc}")
        code = 1
    except (ValueError, RuntimeError) as exc:
        log.error(f"\nSTOPPED: {exc}")
        code = 1
    except KeyboardInterrupt:
        log.error("\nInterrupted. Progress so far is saved; rerun to continue.")
        code = 130
    log.info(report.summary())
    planned = gw.planned if isinstance(gw, DryRunGateway) else None
    report_path = report.write(settings.log_dir, planned)
    log.info(f"Report: {report_path}\nLog:    {log_file}")
    if dry_run and code == 0:
        log.info("Nothing was changed. Review the plan above, then rerun with --apply to make these changes.")
    return code or (1 if report.counts["failed"] else 0)
