"""Checks the extraction file before anything is written to Notion."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from .schema import AREAS

Json = dict[str, Any]

SECTIONS = {"daily", "weekly_goal", "weekly_subgoal", "subtask", "note"}
MARKS = {"tick", "cross", "marked", "empty", "filled", "unclear", "none"}
STATUSES = {"done", "likely_done", "not_done", "not_done_on_page", "open", "unclear", "dropped", "n/a"}
WEEK_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.\.\d{4}-\d{2}-\d{2}$")


def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except (TypeError, ValueError):
        return False


def validate_extraction(x: Json, projects_cfg: Json | None = None, image_dir: Path | None = None) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors block the import; warnings are for review."""
    errors: list[str] = []
    warnings: list[str] = []
    pages = {p["page_id"]: p for p in x.get("pages", [])}
    if len(pages) != len(x.get("pages", [])):
        errors.append("Duplicate page_id values in pages.")
    if x.get("inspected_screenshots") != len(pages):
        errors.append(f"inspected_screenshots={x.get('inspected_screenshots')} but {len(pages)} pages are listed.")
    if x.get("expected_screenshots") and x["expected_screenshots"] != len(pages):
        warnings.append(f"Expected {x['expected_screenshots']} screenshots, extraction has {len(pages)} "
                        f"({x.get('count_note', 'no note')}).")

    files = [p["source_file"] for p in pages.values()]
    if len(set(files)) != len(files):
        errors.append("Two pages point at the same source file.")
    for p in pages.values():
        if p.get("date_iso") and not _valid_date(p["date_iso"]):
            errors.append(f"{p['page_id']}: invalid date_iso {p['date_iso']!r}.")
        if not p.get("date_iso") and not p.get("week_range") and p.get("date_confidence") != "inferred":
            warnings.append(f"{p['page_id']}: no date and not marked as inferred.")
        if p.get("week_range"):
            start, _, end = p["week_range"].partition("..")
            if not WEEK_RE.match(p["week_range"]) or not (_valid_date(start) and _valid_date(end)):
                errors.append(f"{p['page_id']}: invalid week_range {p['week_range']!r}.")
        if image_dir and not (image_dir / p["source_file"]).exists():
            warnings.append(f"{p['page_id']}: source image {p['source_file']} not found in {image_dir}.")

    seen: set[str] = set()
    ids = {i["item_id"] for i in x.get("items", [])}
    threads = {p["thread"] for p in (projects_cfg or {}).get("projects", [])}
    for item in x.get("items", []):
        iid = item.get("item_id", "?")
        if iid in seen:
            errors.append(f"{iid}: duplicate item_id.")
        seen.add(iid)
        if item.get("page_id") not in pages:
            errors.append(f"{iid}: unknown page_id {item.get('page_id')!r}.")
            continue
        if item.get("source_file") != pages[item["page_id"]]["source_file"]:
            errors.append(f"{iid}: source_file does not match its page.")
        if not (item.get("text") or "").strip():
            errors.append(f"{iid}: empty text.")
        if item.get("section") not in SECTIONS:
            errors.append(f"{iid}: unknown section {item.get('section')!r}.")
        if item.get("box_mark") not in MARKS:
            errors.append(f"{iid}: unknown box_mark {item.get('box_mark')!r}.")
        if item.get("proposed_status") not in STATUSES:
            errors.append(f"{iid}: unknown proposed_status {item.get('proposed_status')!r}.")
        if item.get("box_mark") == "empty" and item.get("proposed_status") in ("done", "likely_done"):
            errors.append(f"{iid}: an empty box can never be marked done.")
        if item.get("proposed_area") and item["proposed_area"] not in AREAS:
            errors.append(f"{iid}: unknown area {item['proposed_area']!r}.")
        if item.get("parent_item_id") and item["parent_item_id"] not in ids:
            errors.append(f"{iid}: parent_item_id {item['parent_item_id']!r} does not exist.")
        if item.get("section") in ("weekly_goal", "weekly_subgoal") and not pages[item["page_id"]].get("week_range"):
            errors.append(f"{iid}: weekly goal on a page without week_range.")
        if item.get("uncertain") and not item.get("uncertainty_note"):
            warnings.append(f"{iid}: marked uncertain but no note explains why.")
        if len(item.get("text", "")) > 2000:
            warnings.append(f"{iid}: text longer than Notion's 2000-character limit; it will be truncated.")
    if projects_cfg:
        used = {i.get("proposed_thread") for i in x.get("items", [])}
        for thread in threads - used:
            warnings.append(f"projects.json lists thread {thread!r} which no item uses.")
    return errors, warnings
