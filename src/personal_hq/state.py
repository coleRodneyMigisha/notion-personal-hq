"""Remembers which Notion objects the scripts created.

Saved after every successful write, so an interrupted run can simply be
rerun: anything already recorded (and still present in Notion) is skipped.
Dry runs use a read-only copy and never write this file.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

EMPTY_STATE: dict[str, Any] = {
    "parent_page_id": None,
    "system_page_id": None,
    "databases": {},     # key -> {database_id, data_source_id, properties: {name: id}}
    "views": {},         # "db:View name" -> view id
    "dashboard": {},     # marker_block_id, views: {section: view id}
    "records": {},       # db key -> {import_id: page_id}
}


class State:
    def __init__(self, path: Path, data: dict[str, Any] | None = None, read_only: bool = False):
        self.path = Path(path)
        self.read_only = read_only
        self.data = json.loads(json.dumps(EMPTY_STATE))
        if data:
            self.data.update(data)

    @classmethod
    def load(cls, path: Path, read_only: bool = False) -> "State":
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        return cls(path, data, read_only=read_only)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.data[key] = value

    def __contains__(self, key: str) -> bool:
        return key in self.data

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def keys(self):
        return self.data.keys()

    def values(self):
        return self.data.values()

    def items(self):
        return self.data.items()

    def record(self, db: str, import_id: str, page_id: str) -> None:
        self.data["records"].setdefault(db, {})[import_id] = page_id

    def save(self) -> None:
        if self.read_only:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=2)
        os.replace(tmp, self.path)  # atomic: never leaves a half-written state file
