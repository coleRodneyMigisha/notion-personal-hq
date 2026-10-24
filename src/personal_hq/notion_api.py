"""A small gateway in front of the Notion API.

The builder and importer only use the methods defined here. Three versions
implement them:

* NotionGateway   - the real API via the official-community `notion-client` SDK.
* InMemoryNotion  - a dictionary-backed stand-in used by tests and offline dry runs.
* DryRunGateway   - reads from the real workspace (if available) but only
                    *records* writes, so a dry run never changes Notion.
"""
from __future__ import annotations

import copy
import itertools
import time
from collections import defaultdict
from typing import Any, Iterator

from .config import NOTION_VERSION

Json = dict[str, Any]

_HINTS = {
    401: "The token was rejected. Re-copy the integration secret into .env.",
    403: "The integration lacks a capability. In the integration settings enable "
         "Read, Update and Insert content.",
    404: "Notion cannot see this object. Open the Personal HQ page in Notion, click "
         "'...' > Connections, and add your integration. (A page URL alone grants no access.)",
    409: "Notion reported a conflicting edit. Wait a moment and rerun; finished steps are skipped.",
    429: "Rate limited even after automatic retries. Wait a minute and rerun; finished steps are skipped.",
}


class NotionError(Exception):
    """An API or network error with a human-readable recovery hint."""

    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message
        if status == 400:
            hint = "Notion rejected the request shape. Check the message above; the API may have changed."
        elif status >= 500:
            hint = "Notion had a server problem. Rerun later; finished steps are skipped."
        elif status == 0:
            hint = "Network problem. Check your connection and rerun; finished steps are skipped."
        else:
            hint = _HINTS.get(status, "")
        self.hint = hint
        super().__init__(f"[{status} {code}] {message}" + (f"\n  Fix: {hint}" if hint else ""))


def plain_text(rich: list[Json] | None) -> str:
    return "".join(part.get("plain_text") or part.get("text", {}).get("content", "") for part in rich or [])


# --------------------------------------------------------------------------- real API
class NotionGateway:
    """Talks to Notion. Throttled to stay under the 180 requests/minute limit;
    the SDK itself retries 429 responses using Notion's Retry-After header."""

    def __init__(self, token: str, notion_version: str = NOTION_VERSION, min_interval: float = 0.35,
                 client: Any = None):
        if client is None:
            from notion_client import Client
            client = Client(auth=token, notion_version=notion_version)
        self._client = client
        self._min_interval = min_interval
        self._last_call = 0.0

    def _call(self, fn, **kwargs) -> Json:
        from notion_client.errors import APIResponseError, RequestTimeoutError
        import httpx

        wait = self._min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        try:
            return fn(**kwargs)
        except APIResponseError as exc:
            raise NotionError(exc.status, str(getattr(exc.code, "value", exc.code)), str(exc)) from exc
        except (RequestTimeoutError, httpx.HTTPError) as exc:
            raise NotionError(0, "network_error", str(exc)) from exc
        finally:
            self._last_call = time.monotonic()

    def _paginate(self, fn, **kwargs) -> Iterator[Json]:
        cursor = None
        while True:
            args = dict(kwargs, page_size=100)
            if cursor:
                args["start_cursor"] = cursor
            result = self._call(fn, **args)
            yield from result.get("results", [])
            if not result.get("has_more"):
                return
            cursor = result.get("next_cursor")

    # reads
    def retrieve_page(self, page_id: str) -> Json:
        return self._call(self._client.pages.retrieve, page_id=page_id)

    def iter_children(self, block_id: str) -> Iterator[Json]:
        return self._paginate(self._client.blocks.children.list, block_id=block_id)

    def retrieve_database(self, database_id: str) -> Json:
        return self._call(self._client.databases.retrieve, database_id=database_id)

    def retrieve_data_source(self, data_source_id: str) -> Json:
        return self._call(self._client.data_sources.retrieve, data_source_id=data_source_id)

    def query_data_source(self, data_source_id: str, filter: Json | None = None) -> Iterator[Json]:
        kwargs: Json = {"data_source_id": data_source_id}
        if filter:
            kwargs["filter"] = filter
        return self._paginate(self._client.data_sources.query, **kwargs)

    def list_views(self, database_id: str) -> Iterator[Json]:
        return self._paginate(self._client.views.list, database_id=database_id)

    def retrieve_view(self, view_id: str) -> Json:
        return self._call(self._client.views.retrieve, view_id=view_id)

    # writes
    def create_page(self, body: Json) -> Json:
        return self._call(self._client.pages.create, **body)

    def update_page(self, page_id: str, properties: Json) -> Json:
        return self._call(self._client.pages.update, page_id=page_id, properties=properties)

    def append_children(self, block_id: str, children: list[Json], position: Json | None = None) -> Json:
        kwargs: Json = {"block_id": block_id, "children": children}
        if position:
            kwargs["position"] = position
        return self._call(self._client.blocks.children.append, **kwargs)

    def create_database(self, body: Json) -> Json:
        return self._call(self._client.databases.create, **body)

    def update_data_source(self, data_source_id: str, properties: Json) -> Json:
        return self._call(self._client.data_sources.update, data_source_id=data_source_id, properties=properties)

    def create_view(self, body: Json) -> Json:
        return self._call(self._client.views.create, **body)


# --------------------------------------------------------------------------- in-memory
class InMemoryNotion:
    """Just enough of Notion's behaviour for tests and offline planning."""

    WRITE_METHODS = ("create_page", "update_page", "append_children", "create_database",
                     "update_data_source", "create_view")

    def __init__(self, id_prefix: str = "mem"):
        self.objects: dict[str, Json] = {}
        self.children: dict[str, list[str]] = defaultdict(list)
        self.rows: dict[str, list[str]] = defaultdict(list)       # data source id -> page ids
        self.views: dict[str, list[str]] = defaultdict(list)      # database id -> view ids
        self.writes: list[tuple[str, Json]] = []
        self.fail_on_property: set[str] = set()   # property names whose creation fails (tests)
        self.fail_after_writes: int | None = None  # simulate a crash mid-run (tests)
        self._ids = itertools.count(1)
        self._prefix = id_prefix

    # helpers
    def _new_id(self) -> str:
        return f"{self._prefix}-{next(self._ids):04d}"

    def _write(self, method: str, payload: Json) -> None:
        if self.fail_after_writes is not None and len(self.writes) >= self.fail_after_writes:
            raise NotionError(0, "network_error", "simulated failure")
        self.writes.append((method, payload))

    def _get(self, obj_id: str, kind: str) -> Json:
        obj = self.objects.get(obj_id)
        if not obj or obj["object"] != kind:
            raise NotionError(404, "object_not_found", f"Could not find {kind} with ID: {obj_id}.")
        return obj

    def add_page(self, page_id: str, title: str) -> Json:
        """Seed an existing page (e.g. the Personal HQ parent)."""
        page = {"object": "page", "id": page_id, "in_trash": False,
                "properties": {"title": {"id": "title", "type": "title", "title": [{"plain_text": title}]}}}
        self.objects[page_id] = page
        return page

    def import_object(self, obj: Json) -> None:
        self.objects[obj["id"]] = copy.deepcopy(obj)

    def _make_block(self, block: Json) -> Json:
        b = copy.deepcopy(block)
        b.update(object="block", id=self._new_id())
        b.pop("children", None)
        self.objects[b["id"]] = b
        return b

    def _insert(self, parent: str, ids: list[str], position: Json | None) -> None:
        kids = self.children[parent]
        if not position or position.get("type") == "end":
            kids.extend(ids)
        elif position["type"] == "start":
            kids[:0] = ids
        else:
            # block append uses {"after_block": {"id": ...}}; view placement uses {"block_id": ...}
            after = position.get("block_id") or position["after_block"]["id"]
            idx = kids.index(after) + 1 if after in kids else len(kids)
            kids[idx:idx] = ids

    # reads
    def retrieve_page(self, page_id: str) -> Json:
        return copy.deepcopy(self._get(page_id, "page"))

    def iter_children(self, block_id: str) -> Iterator[Json]:
        for cid in list(self.children.get(block_id, [])):
            yield copy.deepcopy(self.objects[cid])

    def retrieve_database(self, database_id: str) -> Json:
        return copy.deepcopy(self._get(database_id, "database"))

    def retrieve_data_source(self, data_source_id: str) -> Json:
        return copy.deepcopy(self._get(data_source_id, "data_source"))

    def query_data_source(self, data_source_id: str, filter: Json | None = None) -> Iterator[Json]:
        for pid in self.rows.get(data_source_id, []):
            page = self.objects[pid]
            if page.get("in_trash"):
                continue
            if filter and not self._matches(page, filter):
                continue
            yield copy.deepcopy(page)

    @staticmethod
    def _matches(page: Json, flt: Json) -> bool:
        prop = page["properties"].get(flt["property"], {})
        cond = flt.get("rich_text") or flt.get("title") or {}
        value = plain_text(prop.get("rich_text") or prop.get("title"))
        if "equals" in cond:
            return value == cond["equals"]
        if cond.get("is_not_empty"):
            return bool(value)
        return True

    def list_views(self, database_id: str) -> Iterator[Json]:
        for vid in self.views.get(database_id, []):
            yield copy.deepcopy(self.objects[vid])

    def retrieve_view(self, view_id: str) -> Json:
        return copy.deepcopy(self._get(view_id, "view"))

    # writes
    def create_page(self, body: Json) -> Json:
        self._write("create_page", body)
        pid = self._new_id()
        props = copy.deepcopy(body.get("properties", {}))
        for value in props.values():
            for part in value.get("title", []) + value.get("rich_text", []) if isinstance(value, dict) else []:
                part.setdefault("plain_text", part.get("text", {}).get("content", ""))
        page = {"object": "page", "id": pid, "parent": body["parent"], "in_trash": False, "properties": props}
        self.objects[pid] = page
        parent = body["parent"]
        if parent["type"] == "page_id":
            title = plain_text(props.get("title", {}).get("title"))
            self.objects[pid + ":block"] = {"object": "block", "id": pid, "type": "child_page",
                                            "child_page": {"title": title}}
            self.children[parent["page_id"]].append(pid + ":block")
        else:
            self.rows[parent["data_source_id"]].append(pid)
        for child in body.get("children", []):
            self.children[pid].append(self._make_block(child)["id"])
        return copy.deepcopy(page)

    def update_page(self, page_id: str, properties: Json) -> Json:
        self._write("update_page", {"page_id": page_id, "properties": properties})
        page = self._get(page_id, "page")
        page["properties"].update(copy.deepcopy(properties))
        return copy.deepcopy(page)

    def append_children(self, block_id: str, children: list[Json], position: Json | None = None) -> Json:
        self._write("append_children", {"block_id": block_id, "children": children, "position": position})
        made = [self._make_block(c) for c in children]
        self._insert(block_id, [b["id"] for b in made], position)
        return {"object": "list", "results": copy.deepcopy(made)}

    def _schema(self, properties: Json) -> Json:
        out = {}
        for name, spec in properties.items():
            if name in self.fail_on_property:
                raise NotionError(400, "validation_error", f"Property {name!r} rejected (simulated).")
            prop_id = "title" if spec.get("type") == "title" else f"p-{name}"
            out[name] = {"id": prop_id, "name": name, **copy.deepcopy(spec)}
        return out

    def create_database(self, body: Json) -> Json:
        self._write("create_database", body)
        db_id, ds_id = self._new_id(), self._new_id()
        title = plain_text(body.get("title"))
        props = self._schema(body.get("initial_data_source", {}).get("properties", {}))
        self.objects[ds_id] = {"object": "data_source", "id": ds_id, "parent": {"database_id": db_id},
                               "title": body.get("title"), "properties": props}
        db = {"object": "database", "id": db_id, "parent": body["parent"], "title": body.get("title"),
              "in_trash": False, "data_sources": [{"id": ds_id, "name": title}]}
        self.objects[db_id] = db
        self.objects[db_id + ":block"] = {"object": "block", "id": db_id, "type": "child_database",
                                          "child_database": {"title": title}}
        self.children[body["parent"]["page_id"]].append(db_id + ":block")
        return copy.deepcopy(db)

    def update_data_source(self, data_source_id: str, properties: Json) -> Json:
        self._write("update_data_source", {"data_source_id": data_source_id, "properties": properties})
        ds = self._get(data_source_id, "data_source")
        for name, spec in properties.items():
            if spec is None:
                ds["properties"].pop(name, None)
                continue
            ds["properties"].update(self._schema({name: spec}))
            rel = spec.get("relation", {})
            synced = rel.get("dual_property", {}).get("synced_property_name")
            if synced and rel["data_source_id"] in self.objects:
                target = self.objects[rel["data_source_id"]]
                target["properties"][synced] = {
                    "id": f"p-{synced}", "name": synced, "type": "relation",
                    "relation": {"data_source_id": data_source_id, "dual_property": {"synced_property_name": name}}}
        return copy.deepcopy(ds)

    def create_view(self, body: Json) -> Json:
        self._write("create_view", body)
        vid = self._new_id()
        view = {"object": "view", "id": vid, "name": body["name"], "type": body["type"]}
        self.objects[vid] = view
        if "database_id" in body:
            self.views[body["database_id"]].append(vid)
        elif "create_database" in body:
            spec = body["create_database"]
            block = {"object": "block", "id": self._new_id(), "type": "child_database",
                     "child_database": {"title": body["name"]}}
            self.objects[block["id"]] = block
            self._insert(spec["parent"]["page_id"], [block["id"]], spec.get("position"))
        return copy.deepcopy(view)


# --------------------------------------------------------------------------- dry run
class DryRunGateway:
    """Reads pass through to `inner` (the real workspace, or nothing when offline);
    writes are applied to an in-memory overlay and recorded in `planned`."""

    def __init__(self, inner: Any = None):
        self.inner = inner
        self.overlay = InMemoryNotion(id_prefix="planned")
        self.planned: list[Json] = []

    @property
    def offline(self) -> bool:
        return self.inner is None

    def _mine(self, obj_id: str) -> bool:
        return obj_id in self.overlay.objects

    def _plan(self, action: str, target: str, payload: Json) -> None:
        self.planned.append({"action": action, "target": target, "payload": copy.deepcopy(payload)})

    # reads
    def retrieve_page(self, page_id: str) -> Json:
        if self._mine(page_id):
            return self.overlay.retrieve_page(page_id)
        if self.offline:
            return {"object": "page", "id": page_id, "in_trash": False, "properties": {}, "_offline": True}
        return self.inner.retrieve_page(page_id)

    def iter_children(self, block_id: str) -> Iterator[Json]:
        if not self._mine(block_id) and not self.offline:
            yield from self.inner.iter_children(block_id)
        yield from self.overlay.iter_children(block_id)

    def retrieve_database(self, database_id: str) -> Json:
        if self._mine(database_id) or self.offline:
            return self.overlay.retrieve_database(database_id)
        return self.inner.retrieve_database(database_id)

    def retrieve_data_source(self, data_source_id: str) -> Json:
        if self._mine(data_source_id) or self.offline:
            return self.overlay.retrieve_data_source(data_source_id)
        return self.inner.retrieve_data_source(data_source_id)

    def query_data_source(self, data_source_id: str, filter: Json | None = None) -> Iterator[Json]:
        if not self._mine(data_source_id) and not self.offline:
            yield from self.inner.query_data_source(data_source_id, filter)
        yield from self.overlay.query_data_source(data_source_id, filter)

    def list_views(self, database_id: str) -> Iterator[Json]:
        if not self._mine(database_id) and not self.offline:
            yield from self.inner.list_views(database_id)
        yield from self.overlay.list_views(database_id)

    def retrieve_view(self, view_id: str) -> Json:
        if self._mine(view_id) or self.offline:
            return self.overlay.retrieve_view(view_id)
        return self.inner.retrieve_view(view_id)

    # writes (recorded, never sent)
    def create_page(self, body: Json) -> Json:
        self._plan("create_page", str(body.get("parent")), body)
        return self.overlay.create_page(body)

    def update_page(self, page_id: str, properties: Json) -> Json:
        self._plan("update_page", page_id, {"properties": properties})
        if not self._mine(page_id):
            if self.offline:
                return {"object": "page", "id": page_id, "properties": properties}
            self.overlay.import_object(self.inner.retrieve_page(page_id))
        return self.overlay.update_page(page_id, properties)

    def append_children(self, block_id: str, children: list[Json], position: Json | None = None) -> Json:
        self._plan("append_children", block_id, {"children": children, "position": position})
        return self.overlay.append_children(block_id, children, position)

    def create_database(self, body: Json) -> Json:
        self._plan("create_database", str(body.get("parent")), body)
        return self.overlay.create_database(body)

    def update_data_source(self, data_source_id: str, properties: Json) -> Json:
        self._plan("update_data_source", data_source_id, {"properties": properties})
        if not self._mine(data_source_id) and not self.offline:
            self.overlay.import_object(self.inner.retrieve_data_source(data_source_id))
        return self.overlay.update_data_source(data_source_id, properties)

    def create_view(self, body: Json) -> Json:
        self._plan("create_view", body.get("database_id") or "dashboard", body)
        return self.overlay.create_view(body)
