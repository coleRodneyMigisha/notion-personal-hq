"""Writes mapped records into the databases without creating duplicates.

Every record carries an "Import ID" (for example P05-03 = page 5, line 3).
Before writing, the importer reads all existing Import IDs from Notion:
  * not in Notion           -> create
  * in Notion, identical    -> skip
  * in Notion, different    -> report the difference; only overwrite with --update
  * in Notion more than once -> report as a duplicate and leave it alone
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

from .data_mapper import IMPORT_ORDER, Record
from .notion_api import NotionError, plain_text
from .report import Report
from .state import State

log = logging.getLogger(__name__)
Json = dict[str, Any]


def _norm_id(value: str) -> str:
    return value.replace("-", "")


def plain_value(prop: Json | None) -> Any:
    """Reduce a property value (from the API or from our payload) to something comparable."""
    if not prop:
        return None
    if "title" in prop:
        return plain_text(prop["title"]) or None
    if "rich_text" in prop:
        return plain_text(prop["rich_text"]) or None
    if "select" in prop:
        return (prop["select"] or {}).get("name")
    if "date" in prop:
        d = prop["date"] or {}
        return (d.get("start", "")[:10] or None, (d.get("end") or "")[:10] or None) if d else None
    if "checkbox" in prop:
        return bool(prop["checkbox"])
    if "relation" in prop:
        return sorted(_norm_id(r["id"]) for r in prop["relation"])
    return None


def diff_properties(existing: Json, desired: Json) -> list[str]:
    return [name for name, value in desired.items() if plain_value(existing.get(name)) != plain_value(value)]


class Importer:
    def __init__(self, gw: Any, state: State, report: Report, update: bool = False):
        self.gw = gw
        self.state = state
        self.report = report
        self.update = update
        self.page_ids: dict[tuple[str, str], str] = {}

    def run(self, records: dict[str, list[Record]], only: Iterable[str] | None = None) -> None:
        missing = [db for db in IMPORT_ORDER if db not in self.state["databases"]]
        if missing:
            raise RuntimeError(f"Databases not created yet: {', '.join(missing)}. Run create_workspace.py first.")
        selected = [db for db in IMPORT_ORDER if not only or db in only]
        referenced = {ref_db for db in selected for rec in records.get(db, [])
                      for refs in rec.relations.values() for ref_db, _ in refs}
        for db in IMPORT_ORDER:
            if db not in selected:
                if db in referenced:
                    self._load_existing(db)  # only so relations to these records resolve
                continue
            existing, duplicates = self._load_existing(db)
            log.info(f"{db}: {len(records.get(db, []))} source records, {len(existing)} already in Notion")
            for rec in records.get(db, []):
                self._upsert(rec, existing, duplicates)

    def _load_existing(self, db: str) -> tuple[dict[str, Json], set[str]]:
        ds = self.state["databases"][db]["data_source_id"]
        found: dict[str, Json] = {}
        duplicates: set[str] = set()
        for page in self.gw.query_data_source(ds, {"property": "Import ID", "rich_text": {"is_not_empty": True}}):
            iid = plain_text(page["properties"].get("Import ID", {}).get("rich_text"))
            if iid in found:
                duplicates.add(iid)
                continue
            found[iid] = page
            self.page_ids[(db, iid)] = page["id"]
        for iid in sorted(duplicates):
            self.report.failed(db[:-1], iid, "appears more than once in Notion - left untouched; delete the extra copy")
        return found, duplicates

    def _relations(self, rec: Record) -> Json:
        out: Json = {}
        for prop, refs in rec.relations.items():
            ids = []
            for ref in refs:
                page_id = self.page_ids.get(ref)
                if page_id:
                    ids.append({"id": page_id})
                else:
                    log.warning(f"  {rec.import_id}: related record {ref[1]} not found; {prop} left empty")
            out[prop] = {"relation": ids}
        return out

    def _upsert(self, rec: Record, existing: dict[str, Json], duplicates: set[str]) -> None:
        kind = rec.db[:-1]
        if rec.import_id in duplicates:
            return
        props = {**rec.properties, **self._relations(rec)}
        name = f"{rec.import_id} {rec.title[:60]}"
        page = existing.get(rec.import_id)
        try:
            if page:
                changed = diff_properties(page["properties"], props)
                if not changed:
                    self.report.skipped(kind, name, "unchanged")
                elif not self.update:
                    self.report.skipped(kind, name, f"differs in {', '.join(changed)}; not updated")
                    self.report.pending_changes.append({"db": rec.db, "import_id": rec.import_id, "fields": {
                        f: {"notion": plain_value(page["properties"].get(f)), "source": plain_value(props[f])}
                        for f in changed}})
                else:
                    self.gw.update_page(page["id"], {f: props[f] for f in changed})
                    self.report.updated(kind, name, ", ".join(changed))
                return
            body: Json = {"parent": {"type": "data_source_id",
                                     "data_source_id": self.state["databases"][rec.db]["data_source_id"]},
                          "properties": props}
            if rec.children:
                body["children"] = rec.children
            created = self.gw.create_page(body)
            self.page_ids[(rec.db, rec.import_id)] = created["id"]
            self.state.record(rec.db, rec.import_id, created["id"])
            self.state.save()
            self.report.created(kind, name)
        except NotionError as exc:
            self.report.failed(kind, name, exc.message)
