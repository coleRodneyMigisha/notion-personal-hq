import pytest

from personal_hq import schema
from personal_hq.notion_api import DryRunGateway, NotionError
from personal_hq.report import Report
from personal_hq.workspace_builder import AccessError, WorkspaceBuilder, block_text

from conftest import PARENT


def build(gw, state, report=None):
    report = report or Report("t", dry_run=False)
    WorkspaceBuilder(gw, PARENT, state, report).build()
    return report


def test_fresh_build_creates_everything(notion, make_state):
    state = make_state()
    report = build(notion, state)
    assert report.counts["failed"] == 0
    assert set(state["databases"]) == {d.key for d in schema.DATABASES}
    tasks_props = state["databases"]["tasks"]["properties"]
    assert {"Project", "Goal", "Completed"} <= set(tasks_props)
    assert "Tasks" in state["databases"]["projects"]["properties"]          # dual relation synced back
    assert "Task completion" in state["databases"]["goals"]["properties"]
    assert len(state["views"]) == len(schema.DATABASE_VIEWS)
    assert len(state["dashboard"]["views"]) == len(schema.DASHBOARD_SECTIONS)
    # databases live on the system page, not on Personal HQ itself
    titles = [b.get("child_page", {}).get("title") for b in notion.iter_children(PARENT)]
    assert schema.SYSTEM_PAGE_TITLE in titles


def test_rerun_is_idempotent(notion, make_state):
    build(notion, make_state())
    writes_before = len(notion.writes)
    report = build(notion, make_state())             # reload state from disk
    assert len(notion.writes) == writes_before
    assert report.counts["created"] == 0 and report.counts["failed"] == 0


def test_rerun_without_state_file_adopts_existing_objects(notion, make_state, tmp_path):
    build(notion, make_state())
    (tmp_path / "state.json").unlink()               # state lost
    writes_before = len(notion.writes)
    report = build(notion, make_state())
    created_kinds = {e["kind"] for e in report.events if e["outcome"] == "created"}
    assert "database" not in created_kinds and "page" not in created_kinds and "dashboard" not in created_kinds
    assert not any(m == "create_database" for m, _ in notion.writes[writes_before:])


def test_existing_page_content_is_never_touched(notion, make_state):
    notion.append_children(PARENT, [{"type": "paragraph", "paragraph": {"rich_text": [
        {"type": "text", "text": {"content": "My own notes"}}]}}])
    notion.writes.clear()
    build(notion, make_state())
    blocks = list(notion.iter_children(PARENT))
    assert block_text(blocks[0]) == "My own notes"                  # still first
    assert not any(m == "update_page" for m, _ in notion.writes)    # nothing edited in place
    appended = [p for m, p in notion.writes if m == "append_children"]
    assert all(p["position"] is None for p in appended)             # only appended at the end


def test_dry_run_makes_no_writes_but_plans_everything(notion, make_state):
    gw = DryRunGateway(notion)
    state = make_state(read_only=True)
    report = build(gw, state, Report("t", dry_run=True))
    assert notion.writes == []
    assert report.counts["created"] > 0
    actions = {p["action"] for p in gw.planned}
    assert {"create_page", "create_database", "update_data_source", "create_view", "append_children"} <= actions
    assert not state.path.exists()                                   # dry run never saves state


def test_offline_dry_run_needs_no_notion(make_state):
    gw = DryRunGateway(None)
    report = build(gw, make_state(read_only=True), Report("t", dry_run=True))
    assert report.counts["failed"] == 0
    assert any("NOT verified" in n for n in report.notes)


def test_missing_access_stops_before_any_write(make_state):
    from personal_hq.notion_api import InMemoryNotion
    empty = InMemoryNotion()                          # parent page not shared -> 404
    with pytest.raises(AccessError, match="Connections"):
        build(empty, make_state())
    assert empty.writes == []


def test_state_for_a_different_parent_is_refused(notion, make_state):
    state = make_state()
    state["parent_page_id"] = "00000000-0000-0000-0000-000000000000"
    with pytest.raises(AccessError, match="Refusing"):
        build(notion, state)


def test_partial_failure_then_rerun_completes(notion, make_state):
    notion.fail_after_writes = 4                      # crash part-way through
    with pytest.raises(NotionError):
        build(notion, make_state())
    notion.fail_after_writes = None
    report = build(notion, make_state())
    assert report.counts["failed"] == 0
    db_creates = [p for m, p in notion.writes if m == "create_database"]
    assert len(db_creates) == len(schema.DATABASES)  # none duplicated


def test_dashboard_views_resume_after_failure(notion, make_state, monkeypatch):
    original = notion.create_view
    calls = {"n": 0}

    def flaky(body):
        if "create_database" in body:
            calls["n"] += 1
            if calls["n"] == 3:
                raise NotionError(500, "internal_server_error", "boom")
        return original(body)

    monkeypatch.setattr(notion, "create_view", flaky)
    first = build(notion, make_state())
    assert first.counts["failed"] == 1
    monkeypatch.setattr(notion, "create_view", original)
    second = build(notion, make_state())
    assert second.counts["failed"] == 0
    assert [e for e in second.events if e["outcome"] == "created"] == [
        e for e in second.events if e["kind"] == "view" and e["outcome"] == "created"]
    dashboard_blocks = [b for b in notion.iter_children(PARENT) if b["type"] == "callout"]
    assert len(dashboard_blocks) == 1                # dashboard not appended twice


def test_rejected_rollup_falls_back_and_lists_manual_step(notion, make_state):
    notion.fail_on_property = {"Task completion"}
    state = make_state()
    report = build(notion, state)
    assert "Linked tasks" in state["databases"]["goals"]["properties"]
    assert any("Percent checked" in s for s in report.manual_steps)


def test_rejected_view_is_reported_with_manual_steps(notion, make_state, monkeypatch):
    def reject(body):
        raise NotionError(400, "validation_error", "views not allowed")
    monkeypatch.setattr(notion, "create_view", reject)
    report = build(notion, make_state())
    assert report.counts["failed"] == len(schema.DATABASE_VIEWS) + len(schema.DASHBOARD_SECTIONS)
    assert any('add a table view "Today"' in s and "Planned equals today" in s for s in report.manual_steps)
