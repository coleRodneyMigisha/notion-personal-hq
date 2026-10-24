import pytest

from personal_hq.data_mapper import Mapper
from personal_hq.importer import Importer, diff_properties
from personal_hq.notion_api import DryRunGateway, NotionError
from personal_hq.report import Report
from personal_hq.workspace_builder import WorkspaceBuilder

from conftest import PARENT

CFG = {"projects": [{"thread": "ds_course", "name": "Data Science course", "area": "ACAD"},
                    {"thread": "lit_review", "name": "Structured literature review", "area": "RES"}]}


@pytest.fixture
def workspace(notion, make_state):
    state = make_state()
    WorkspaceBuilder(notion, PARENT, state, Report("t", dry_run=False)).build()
    notion.writes.clear()
    return notion


def run_import(gw, state, records, update=False, dry_run=False):
    report = Report("t", dry_run=dry_run)
    Importer(gw, state, report, update=update).run(records)
    return report


def test_import_creates_all_records_with_relations(workspace, make_state, small_extraction):
    state = make_state()
    records = Mapper(small_extraction, CFG).build()
    report = run_import(workspace, state, records)
    assert report.counts["failed"] == 0
    assert report.counts["created"] == sum(len(r) for r in records.values())
    task_ds = state["databases"]["tasks"]["data_source_id"]
    lab = next(p for p in workspace.query_data_source(task_ds)
               if p["properties"]["Import ID"]["rich_text"][0]["plain_text"] == "P01-02")
    project_id = state["records"]["projects"]["PRJ-ds_course"]
    assert lab["properties"]["Project"]["relation"] == [{"id": project_id}]


def test_rerun_creates_nothing(workspace, make_state, small_extraction):
    records = Mapper(small_extraction, CFG).build()
    run_import(workspace, make_state(), records)
    writes = len(workspace.writes)
    report = run_import(workspace, make_state(), records)
    assert len(workspace.writes) == writes
    assert report.counts["created"] == 0 and report.counts["skipped"] == sum(len(r) for r in records.values())


def test_duplicates_detected_even_without_state(workspace, make_state, small_extraction, tmp_path):
    records = Mapper(small_extraction, CFG).build()
    run_import(workspace, make_state(), records)
    state = make_state()
    state["records"] = {}                              # forget what we created
    report = run_import(workspace, state, records)
    assert report.counts["created"] == 0


def test_duplicate_copies_in_notion_are_reported_not_touched(workspace, make_state, small_extraction):
    state = make_state()
    records = Mapper(small_extraction, CFG).build()
    run_import(workspace, state, records)
    task = next(r for r in records["tasks"] if r.import_id == "P01-02")
    workspace.create_page({"parent": {"type": "data_source_id",
                                      "data_source_id": state["databases"]["tasks"]["data_source_id"]},
                           "properties": task.properties})
    workspace.writes.clear()
    report = run_import(workspace, make_state(), records)
    assert any(e["name"] == "P01-02" and e["outcome"] == "failed" for e in report.events)
    assert workspace.writes == []


def test_changed_records_are_reported_and_only_updated_with_flag(workspace, make_state, small_extraction):
    records = Mapper(small_extraction, CFG).build()
    run_import(workspace, make_state(), records)
    small_extraction["items"][0]["text"] = "wake up at 05:30"
    changed = Mapper(small_extraction, CFG).build()
    workspace.writes.clear()

    report = run_import(workspace, make_state(), changed)
    assert workspace.writes == []
    assert report.pending_changes[0]["import_id"] == "P01-01"
    assert report.pending_changes[0]["fields"]["Task"] == {"notion": "wake up at 05:00", "source": "wake up at 05:30"}

    report = run_import(workspace, make_state(), changed, update=True)
    assert report.counts["updated"] == 1
    assert [m for m, _ in workspace.writes] == ["update_page"]


def test_partial_import_failure_then_rerun(workspace, make_state, small_extraction):
    records = Mapper(small_extraction, CFG).build()
    original = workspace.create_page
    calls = {"n": 0}

    def flaky(body):
        calls["n"] += 1
        if calls["n"] in (3, 7):
            raise NotionError(0, "network_error", "connection reset")
        return original(body)

    workspace.create_page = flaky
    first = run_import(workspace, make_state(), records)
    assert first.counts["failed"] == 2
    workspace.create_page = original
    second = run_import(workspace, make_state(), records)
    assert second.counts["created"] == 2 and second.counts["failed"] == 0
    total = sum(len(list(workspace.query_data_source(db["data_source_id"])))
                for db in make_state()["databases"].values())
    assert total == sum(len(r) for r in records.values())


def test_dry_run_import_writes_nothing(workspace, make_state, small_extraction):
    gw = DryRunGateway(workspace)
    report = run_import(gw, make_state(read_only=True), Mapper(small_extraction, CFG).build(), dry_run=True)
    assert workspace.writes == []
    assert report.counts["created"] > 0
    assert {p["action"] for p in gw.planned} == {"create_page"}


def test_import_refuses_before_workspace_exists(notion, make_state, small_extraction):
    with pytest.raises(RuntimeError, match="create_workspace"):
        run_import(notion, make_state(), Mapper(small_extraction, CFG).build())


def test_full_offline_plan_for_real_data(make_state, real_extraction, projects_cfg):
    gw = DryRunGateway(None)
    state = make_state(read_only=True)
    report = Report("t", dry_run=True)
    WorkspaceBuilder(gw, PARENT, state, report).build()
    Importer(gw, state, report).run(Mapper(real_extraction, projects_cfg).build())
    assert report.counts["failed"] == 0
    creates = [p for p in gw.planned if p["action"] == "create_page"]
    assert len(creates) == 1 + 3 + 23 + 37 + 248 + 27      # system page + all records


def test_diff_ignores_equivalent_values():
    existing = {"Task": {"title": [{"plain_text": "a"}]}, "Due": {"date": None},
                "Project": {"relation": [{"id": "abc-def"}]}}
    desired = {"Task": {"title": [{"text": {"content": "a"}}]}, "Due": {"date": None},
               "Project": {"relation": [{"id": "abcdef"}]}}
    assert diff_properties(existing, desired) == []
