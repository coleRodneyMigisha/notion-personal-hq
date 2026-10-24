"""Creates the Personal HQ structure in Notion, idempotently.

Order of work:
  1. verify the Personal HQ page is reachable (stop with guidance if not)
  2. a "Personal HQ System" child page that holds the databases
  3. the five databases, then their relations, formula and rollups
  4. saved views inside each database
  5. the dashboard: blocks + linked views appended to the end of Personal HQ

Each step first looks in the state file, then in Notion (by title), and only
creates what is missing. Nothing is ever deleted or overwritten.
"""
from __future__ import annotations

import logging
from typing import Any

from . import schema
from .notion_api import NotionError, plain_text
from .report import Report
from .state import State

log = logging.getLogger(__name__)
Json = dict[str, Any]


class AccessError(Exception):
    """The integration cannot reach the Personal HQ page."""


def text(content: str, **annotations: Any) -> Json:
    rt: Json = {"type": "text", "text": {"content": content[:2000]}}
    if annotations:
        rt["annotations"] = annotations
    return rt


def page_title(page: Json) -> str:
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title" or "title" in prop:
            return plain_text(prop.get("title"))
    return ""


def block_text(block: Json) -> str:
    body = block.get(block.get("type", ""), {})
    return plain_text(body.get("rich_text")) if isinstance(body, dict) else ""


class WorkspaceBuilder:
    def __init__(self, gw: Any, parent_page_id: str, state: State, report: Report):
        self.gw = gw
        self.parent_id = parent_page_id
        self.state = state
        self.report = report
        self.trust_state = getattr(gw, "offline", False)  # offline dry run cannot check Notion

    # ------------------------------------------------------------------ entry point
    def build(self) -> None:
        self.verify_parent()
        self.ensure_system_page()
        for spec in schema.DATABASES:
            self.ensure_database(spec)
        for rel in schema.RELATIONS:
            self.ensure_relation(rel)
        for comp in schema.COMPUTED:
            self.ensure_computed(comp)
        for view in schema.DATABASE_VIEWS:
            self.ensure_view(view)
        self.ensure_dashboard()

    # ------------------------------------------------------------------ helpers
    def _exists(self, retrieve, obj_id: str | None) -> bool:
        if not obj_id:
            return False
        if self.trust_state:
            return True
        try:
            return not retrieve(obj_id).get("in_trash", False)
        except NotionError as exc:
            if exc.status == 404:
                return False
            raise

    def _db(self, key: str) -> Json:
        return self.state["databases"][key]

    def _refresh_properties(self, key: str) -> dict[str, str]:
        ds = self.gw.retrieve_data_source(self._db(key)["data_source_id"])
        props = {name: p["id"] for name, p in ds["properties"].items()}
        self._db(key)["properties"] = props
        return props

    # ------------------------------------------------------------------ steps
    def verify_parent(self) -> None:
        recorded = self.state["parent_page_id"]
        if recorded and recorded != self.parent_id:
            raise AccessError(
                f"The state file belongs to parent page {recorded}, but .env points to {self.parent_id}. "
                "Refusing to continue so nothing is created in the wrong place.")
        try:
            page = self.gw.retrieve_page(self.parent_id)
        except NotionError as exc:
            if exc.status in (401, 403, 404):
                raise AccessError(f"Cannot access the Personal HQ page ({self.parent_id}).\n  {exc.hint}") from exc
            raise
        if page.get("in_trash"):
            raise AccessError("The Personal HQ page is in Notion's trash. Restore it, then rerun.")
        if page.get("_offline"):
            self.report.note("Offline dry run: access to the Personal HQ page was NOT verified.")
        else:
            self.report.note(f"Personal HQ page reachable: {page_title(page)!r} ({self.parent_id})")
        self.state["parent_page_id"] = self.parent_id

    def ensure_system_page(self) -> None:
        if self._exists(self.gw.retrieve_page, self.state["system_page_id"]):
            self.report.skipped("page", schema.SYSTEM_PAGE_TITLE, "already exists")
            return
        for block in self.gw.iter_children(self.parent_id):
            if block["type"] == "child_page" and block["child_page"]["title"] == schema.SYSTEM_PAGE_TITLE:
                self.state["system_page_id"] = block["id"]
                self.state.save()
                self.report.skipped("page", schema.SYSTEM_PAGE_TITLE, "found existing page, adopted it")
                return
        page = self.gw.create_page({
            "parent": {"type": "page_id", "page_id": self.parent_id},
            "icon": {"type": "emoji", "emoji": "🗂️"},
            "properties": {"title": {"title": [text(schema.SYSTEM_PAGE_TITLE)]}},
            "children": [{"type": "paragraph", "paragraph": {"rich_text": [text(
                "The databases behind your Personal HQ dashboard. Use the dashboard day to day; "
                "open these for full lists and extra views.")]}}],
        })
        self.state["system_page_id"] = page["id"]
        self.state.save()
        self.report.created("page", schema.SYSTEM_PAGE_TITLE, "under Personal HQ")

    def ensure_database(self, spec: schema.DatabaseSpec) -> None:
        rec = self.state["databases"].get(spec.key)
        if rec and self._exists(self.gw.retrieve_database, rec.get("database_id")):
            if not self.trust_state:
                self._refresh_properties(spec.key)
            self.report.skipped("database", spec.title, "already exists")
            return
        system_id = self.state["system_page_id"]
        for block in self.gw.iter_children(system_id):
            if block["type"] == "child_database" and block["child_database"]["title"] == spec.title:
                db = self.gw.retrieve_database(block["id"])
                self.state["databases"][spec.key] = {"database_id": db["id"],
                                                     "data_source_id": db["data_sources"][0]["id"]}
                self._refresh_properties(spec.key)
                self.state.save()
                self.report.skipped("database", spec.title, "found existing database, adopted it")
                return
        db = self.gw.create_database({
            "parent": {"type": "page_id", "page_id": system_id},
            "title": [text(spec.title)],
            "icon": {"type": "emoji", "emoji": spec.icon},
            "initial_data_source": {"properties": spec.properties},
        })
        self.state["databases"][spec.key] = {"database_id": db["id"], "data_source_id": db["data_sources"][0]["id"]}
        self._refresh_properties(spec.key)
        self.state.save()
        self.report.created("database", spec.title, f"{len(spec.properties)} properties")

    def ensure_relation(self, rel: schema.RelationSpec) -> None:
        label = f"{schema.DATABASES_BY_KEY[rel.source].title}.{rel.name}"
        if rel.name in self._db(rel.source).get("properties", {}):
            self.report.skipped("relation", label, "already exists")
            return
        relation: Json = {"data_source_id": self._db(rel.target)["data_source_id"]}
        if rel.synced_name:
            relation["dual_property"] = {"synced_property_name": rel.synced_name}
        else:
            relation["single_property"] = {}
        try:
            self.gw.update_data_source(self._db(rel.source)["data_source_id"],
                                       {rel.name: {"type": "relation", "relation": relation}})
        except NotionError as exc:
            self.report.failed("relation", label, exc.message)
            self.report.manual(f"Add relation {label} -> {schema.DATABASES_BY_KEY[rel.target].title}")
            return
        self._refresh_properties(rel.source)
        self._refresh_properties(rel.target)
        self.state.save()
        target = schema.DATABASES_BY_KEY[rel.target].title
        both = f" (and {target}.{rel.synced_name})" if rel.synced_name else ""
        self.report.created("relation", label, f"-> {target}{both}")

    def ensure_computed(self, comp: schema.ComputedSpec) -> None:
        label = f"{schema.DATABASES_BY_KEY[comp.db].title}.{comp.name}"
        props = self._db(comp.db).get("properties", {})
        if comp.name in props or (comp.fallback_name and comp.fallback_name in props):
            self.report.skipped("property", label, "already exists")
            return
        ds_id = self._db(comp.db)["data_source_id"]
        try:
            self.gw.update_data_source(ds_id, {comp.name: comp.definition})
            self.report.created("property", label, comp.definition["type"])
        except NotionError as exc:
            if not comp.fallback_name:
                self.report.failed("property", label, exc.message)
                self.report.manual(comp.manual_if_failed)
                return
            log.warning(f"  {label} was rejected ({exc.message}); trying simpler fallback")
            try:
                self.gw.update_data_source(ds_id, {comp.fallback_name: comp.fallback_definition})
                self.report.created("property", f"{schema.DATABASES_BY_KEY[comp.db].title}.{comp.fallback_name}",
                                    "fallback rollup (count)")
                self.report.manual(comp.manual_if_failed)
            except NotionError as exc2:
                self.report.failed("property", label, exc2.message)
                self.report.manual(comp.manual_if_failed)
                return
        self._refresh_properties(comp.db)
        self.state.save()

    def _find_view(self, database_id: str, name: str) -> str | None:
        if self.trust_state:
            return None
        for view in self.gw.list_views(database_id):
            view_name = view.get("name") or self.gw.retrieve_view(view["id"]).get("name")
            if view_name == name:
                return view["id"]
        return None

    def ensure_view(self, view: schema.ViewSpec) -> None:
        key = f"{view.db}:{view.name}"
        label = f"{schema.DATABASES_BY_KEY[view.db].title} / {view.name}"
        if key in self.state["views"]:
            self.report.skipped("view", label, "already exists")
            return
        db = self._db(view.db)
        existing = self._find_view(db["database_id"], view.name)
        if existing:
            self.state["views"][key] = existing
            self.state.save()
            self.report.skipped("view", label, "found existing view, adopted it")
            return
        body = {"database_id": db["database_id"], "data_source_id": db["data_source_id"],
                **view.body(db.get("properties", {}))}
        try:
            created = self.gw.create_view(body)
        except NotionError as exc:
            self.report.failed("view", label, exc.message)
            self.report.manual(view.manual_steps())
            return
        self.state["views"][key] = created["id"]
        self.state.save()
        self.report.created("view", label, view.type)

    # ------------------------------------------------------------------ dashboard
    def dashboard_blocks(self) -> tuple[list[Json], list[tuple[int, schema.ViewSpec]]]:
        """Blocks to append, plus (index of the block each linked view goes after, view)."""
        blocks: list[Json] = [
            {"type": "divider", "divider": {}},
            {"type": "callout", "callout": {
                "icon": {"type": "emoji", "emoji": "🧭"},
                "color": "gray_background",
                "rich_text": [text(schema.DASHBOARD_INTRO + "\n"),
                              text(f"(Built by notion-personal-hq · {schema.DASHBOARD_MARKER} - keep this "
                                   "line so reruns know the dashboard exists.)", italic=True, color="gray")]}},
        ]
        anchors: list[tuple[int, schema.ViewSpec]] = []
        for section in schema.DASHBOARD_SECTIONS:
            blocks.append({"type": "heading_2", "heading_2": {"rich_text": [text(section.heading)]}})
            blocks.append({"type": "paragraph", "paragraph": {"rich_text": [text(section.hint, italic=True)]}})
            for item in section.extra:
                blocks.append({"type": "to_do", "to_do": {"rich_text": [text(item)], "checked": False}})
            if section.view:
                anchors.append((len(blocks) - 1, section.view))
        blocks.append({"type": "heading_2", "heading_2": {"rich_text": [text("🧩 All databases")]}})
        blocks.append({"type": "link_to_page", "link_to_page": {"type": "page_id",
                                                                "page_id": self.state["system_page_id"]}})
        return blocks, anchors

    def ensure_dashboard(self) -> None:
        blocks, anchors = self.dashboard_blocks()
        dash = self.state["dashboard"]
        page_blocks = [] if (self.trust_state and dash.get("marker_block_id")) else list(
            self.gw.iter_children(self.parent_id))
        marker_present = (self.trust_state and dash.get("marker_block_id")) or any(
            schema.DASHBOARD_MARKER in block_text(b) for b in page_blocks)

        if not marker_present:
            created = self.gw.append_children(self.parent_id, blocks)["results"]
            marker = next(b for b in created if b["type"] == "callout")
            self.state["dashboard"] = dash = {"marker_block_id": marker["id"], "views": {}}
            self.state.save()
            self.report.created("dashboard", "Personal HQ dashboard",
                                f"{len(blocks)} blocks appended to the END of the page; existing content untouched")
            anchor_ids = {view.name: created[i]["id"] for i, view in anchors}
        elif not dash.get("marker_block_id"):
            # Built by an earlier run whose state file is gone: leave it alone.
            self.report.skipped("dashboard", "Personal HQ dashboard", "marker found on page")
            return
        else:
            self.report.skipped("dashboard", "Personal HQ dashboard blocks", "already on page")
            # Resume: find each section's anchor block by its text, for views not yet created.
            by_text = {block_text(b): b["id"] for b in page_blocks}
            anchor_ids = {view.name: by_text.get(block_text(blocks[i])) for i, view in anchors}

        for _, view in anchors:
            label = f"dashboard / {view.name}"
            if view.name in dash.get("views", {}):
                self.report.skipped("view", label, "already exists")
                continue
            anchor = anchor_ids.get(view.name)
            if not anchor:
                self.report.failed("view", label, "section heading not found on the page")
                self.report.manual(f"On Personal HQ add a linked view of "
                                   f"{schema.DATABASES_BY_KEY[view.db].title}: {view.manual_steps()}")
                continue
            db = self._db(view.db)
            body = {"data_source_id": db["data_source_id"], **view.body(db.get("properties", {})),
                    "create_database": {"parent": {"type": "page_id", "page_id": self.parent_id},
                                        "position": {"type": "after_block", "block_id": anchor},
                                        "show_data_source_title": True}}
            try:
                made = self.gw.create_view(body)
            except NotionError as exc:
                self.report.failed("view", label, exc.message)
                self.report.manual(f"On Personal HQ under '{view.name}': type /linked view, choose "
                                   f"{schema.DATABASES_BY_KEY[view.db].title}, then {view.manual_steps()}")
                continue
            dash.setdefault("views", {})[view.name] = made["id"]
            self.state.save()
            self.report.created("view", label, f"linked {schema.DATABASES_BY_KEY[view.db].title} view")
