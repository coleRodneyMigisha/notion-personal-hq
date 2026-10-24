"""Logging and the end-of-run summary report."""
from __future__ import annotations

import json
import logging
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("personal_hq")


def setup_logging(log_dir: Path, run_name: str) -> Path:
    """Log INFO to the console and DEBUG to logs/<run>-<timestamp>.log."""
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = log_dir / f"{run_name}-{stamp}.log"
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(message)s"))
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(console)
    root.addHandler(file_handler)
    for noisy in ("httpx", "httpcore", "notion_client"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return log_file


class Report:
    """Collects created / updated / skipped / failed events for one run."""

    def __init__(self, name: str, dry_run: bool):
        self.name = name
        self.dry_run = dry_run
        self.events: list[dict[str, str]] = []
        self.notes: list[str] = []
        self.manual_steps: list[str] = []
        self.pending_changes: list[dict[str, Any]] = []

    def _add(self, outcome: str, kind: str, name: str, detail: str = "") -> None:
        self.events.append({"outcome": outcome, "kind": kind, "name": name, "detail": detail})
        verb = {"created": "WOULD CREATE" if self.dry_run else "CREATED",
                "updated": "WOULD UPDATE" if self.dry_run else "UPDATED",
                "skipped": "SKIP", "failed": "FAILED"}[outcome]
        line = f"  {verb:<13} {kind:<10} {name}" + (f"  ({detail})" if detail else "")
        (log.error if outcome == "failed" else log.info)(line)

    def created(self, kind: str, name: str, detail: str = "") -> None:
        self._add("created", kind, name, detail)

    def updated(self, kind: str, name: str, detail: str = "") -> None:
        self._add("updated", kind, name, detail)

    def skipped(self, kind: str, name: str, detail: str = "") -> None:
        self._add("skipped", kind, name, detail)

    def failed(self, kind: str, name: str, detail: str = "") -> None:
        self._add("failed", kind, name, detail)

    def note(self, text: str) -> None:
        self.notes.append(text)
        log.info(f"  NOTE  {text}")

    def manual(self, text: str) -> None:
        self.manual_steps.append(text)

    @property
    def counts(self) -> Counter:
        return Counter(e["outcome"] for e in self.events)

    def summary(self) -> str:
        c = self.counts
        mode = "DRY RUN - nothing was changed in Notion" if self.dry_run else "APPLIED to Notion"
        lines = ["", "=" * 70, f"{self.name}: {mode}",
                 f"  {'would create' if self.dry_run else 'created'}: {c['created']}   "
                 f"{'would update' if self.dry_run else 'updated'}: {c['updated']}   "
                 f"skipped: {c['skipped']}   failed: {c['failed']}"]
        by_kind = Counter((e["outcome"], e["kind"]) for e in self.events)
        for (outcome, kind), n in sorted(by_kind.items()):
            lines.append(f"    {outcome:<8} {kind:<10} {n}")
        if self.pending_changes:
            lines.append(f"  {len(self.pending_changes)} existing record(s) differ from the source data; "
                         "rerun with --update (plus --apply) to overwrite them.")
        if self.manual_steps:
            lines.append("  Manual steps needed in Notion:")
            lines += [f"    - {s}" for s in self.manual_steps]
        if c["failed"]:
            lines.append("  Some steps failed. Fix the cause shown above and rerun: completed steps are skipped.")
        lines.append("=" * 70)
        return "\n".join(lines)

    def write(self, log_dir: Path, planned: list[dict[str, Any]] | None = None) -> Path:
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = log_dir / f"{self.name}-report-{stamp}.json"
        payload = {"run": self.name, "dry_run": self.dry_run, "counts": dict(self.counts),
                   "events": self.events, "notes": self.notes, "manual_steps": self.manual_steps,
                   "pending_changes": self.pending_changes}
        if planned is not None:
            payload["planned_api_calls"] = planned
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path
