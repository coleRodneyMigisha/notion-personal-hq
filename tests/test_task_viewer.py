"""Tests for the Daily Tasks Viewer."""
from datetime import date, timedelta
from io import StringIO

import pytest

from personal_hq.notion_api import InMemoryNotion
from personal_hq.task_viewer import (
    DailyTasksViewer,
    TaskItem,
    TaskManager,
    TerminalController,
    create_offline_manager,
    format_relative_day,
    parse_target_date,
    task_from_page,
)


def make_page(
    page_id: str,
    title: str,
    status: str = "To do",
    planned: str | None = "2026-11-07",
    time_str: str = "",
    focus: bool = False,
    notes: str = "",
    project_id: str | None = None,
    carried_over: bool = False,
    completed_on: str | None = None,
):
    props = {
        "Task": {"title": [{"type": "text", "text": {"content": title}, "plain_text": title}]},
        "Status": {"select": {"name": status}},
        "Planned": {"date": {"start": planned}} if planned else {"date": None},
        "Time": {"rich_text": [{"type": "text", "text": {"content": time_str}, "plain_text": time_str}]} if time_str else {"rich_text": []},
        "Focus": {"checkbox": focus},
        "Notes": {"rich_text": [{"type": "text", "text": {"content": notes}, "plain_text": notes}]} if notes else {"rich_text": []},
        "Carried over": {"checkbox": carried_over},
        "Completed on": {"date": {"start": completed_on}} if completed_on else {"date": None},
    }
    if project_id:
        props["Project"] = {"relation": [{"id": project_id}]}
    return {"id": page_id, "object": "page", "properties": props}


@pytest.fixture
def mock_notion_env():
    gw = InMemoryNotion()
    tasks_ds_id = "test-tasks-ds"
    contrib_ds_id = "test-contrib-ds"
    gw.objects[tasks_ds_id] = {"object": "data_source", "id": tasks_ds_id, "properties": {}}
    gw.rows[tasks_ds_id] = []
    gw.objects[contrib_ds_id] = {"object": "data_source", "id": contrib_ds_id, "properties": {}}
    gw.rows[contrib_ds_id] = []

    mock_state = {
        "databases": {
            "contribution_calendar": {"data_source_id": contrib_ds_id, "database_id": "test-contrib-db"}
        },
        "records": {"contribution_calendar": {}}
    }

    pages = [
        make_page("p1", "Task 1", "To do", planned="2026-11-07", time_str="08:00-09:00", focus=True),
        make_page("p2", "Task 2", "Done", planned="2026-11-07", completed_on="2026-11-07"),
        make_page("p3", "Task 3", "To do", planned="2026-11-08"),
        make_page("p4", "Task 4", "Not done", planned="2026-11-05"),
    ]
    for p in pages:
        gw.objects[p["id"]] = p
        gw.rows[tasks_ds_id].append(p["id"])

    projects_map = {"proj-1": "AI Research"}
    mgr = TaskManager(
        gw=gw,
        tasks_ds_id=tasks_ds_id,
        tasks_db_id="test-tasks-db",
        projects_map=projects_map,
        state=mock_state,
    )
    mgr.load()
    return mgr


def test_parse_target_date():
    today = date.today()
    assert parse_target_date("today") == today
    assert parse_target_date("t") == today
    assert parse_target_date("tomorrow") == today + timedelta(days=1)
    assert parse_target_date("yesterday") == today - timedelta(days=1)
    assert parse_target_date("+2", today) == today + timedelta(days=2)
    assert parse_target_date("-3", today) == today - timedelta(days=3)
    assert parse_target_date("2026-10-22") == date(2026, 10, 22)
    assert parse_target_date("invalid-date") is None
    assert parse_target_date("") is None


def test_format_relative_day():
    today = date(2026, 11, 7)
    assert format_relative_day(date(2026, 11, 7), today) == "Today"
    assert format_relative_day(date(2026, 11, 8), today) == "Tomorrow"
    assert format_relative_day(date(2026, 11, 6), today) == "Yesterday"
    assert format_relative_day(date(2026, 11, 10), today) == "+3 days"
    assert format_relative_day(date(2026, 11, 3), today) == "-4 days"


def test_task_from_page():
    page = make_page(
        "p10",
        "Test Title",
        "Done",
        planned="2026-11-01",
        time_str="10:00",
        focus=True,
        notes="Important note",
        project_id="prj_a",
        carried_over=True,
        completed_on="2026-11-01",
    )
    item = task_from_page(page, projects={"prj_a": "My Project"})
    assert item.id == "p10"
    assert item.title == "Test Title"
    assert item.status == "Done"
    assert item.planned == "2026-11-01"
    assert item.time == "10:00"
    assert item.focus is True
    assert item.project_name == "My Project"
    assert item.notes == "Important note"
    assert item.carried_over is True
    assert item.completed_on == "2026-11-01"


def test_task_manager_navigation_helpers(mock_notion_env):
    mgr = mock_notion_env
    dates = mgr.dates_with_tasks()
    assert dates == ["2026-11-05", "2026-11-07", "2026-11-08"]

    assert mgr.next_date_with_tasks("2026-11-05") == "2026-11-07"
    assert mgr.next_date_with_tasks("2026-11-07") == "2026-11-08"
    assert mgr.next_date_with_tasks("2026-11-08") is None

    assert mgr.prev_date_with_tasks("2026-11-08") == "2026-11-07"
    assert mgr.prev_date_with_tasks("2026-11-07") == "2026-11-05"
    assert mgr.prev_date_with_tasks("2026-11-05") is None

    tasks_7th = mgr.tasks_for_date("2026-11-07")
    assert len(tasks_7th) == 2
    # Sorted by time first
    assert tasks_7th[0].id == "p1"


def test_task_manager_toggle_done(mock_notion_env):
    mgr = mock_notion_env
    # p1 is initially To do
    t1 = mgr.toggle_done("p1")
    assert t1.status == "Done"
    assert t1.completed_on == date.today().isoformat()

    # Toggle back to To do
    t1_again = mgr.toggle_done("p1")
    assert t1_again.status == "To do"
    assert t1_again.completed_on is None


def test_task_manager_toggle_focus(mock_notion_env):
    mgr = mock_notion_env
    # p2 is initially focus=False
    t2 = mgr.toggle_focus("p2")
    assert t2.focus is True

    t2 = mgr.toggle_focus("p2")
    assert t2.focus is False


def test_task_manager_set_status(mock_notion_env):
    mgr = mock_notion_env
    t1 = mgr.set_status("p1", "Needs review")
    assert t1.status == "Needs review"
    assert t1.completed_on is None

    t1_done = mgr.set_status("p1", "Done")
    assert t1_done.status == "Done"
    assert t1_done.completed_on == date.today().isoformat()


def test_task_manager_edit_task(mock_notion_env):
    mgr = mock_notion_env
    updated = mgr.edit_task("p1", title="Renamed task", time_str="12:00-13:00", notes="New note")
    assert updated.title == "Renamed task"
    assert updated.time == "12:00-13:00"
    assert updated.notes == "New note"


def test_task_manager_move_task(mock_notion_env):
    mgr = mock_notion_env
    assert len(mgr.tasks_for_date("2026-11-07")) == 2
    assert len(mgr.tasks_for_date("2026-11-10")) == 0

    moved = mgr.move_task("p1", "2026-11-10")
    assert moved.planned == "2026-11-10"
    assert len(mgr.tasks_for_date("2026-11-07")) == 1
    assert len(mgr.tasks_for_date("2026-11-10")) == 1


def test_task_manager_add_task(mock_notion_env):
    mgr = mock_notion_env
    new_t = mgr.add_task(
        date_str="2026-11-07",
        title="Created Task",
        time_str="15:00",
        focus=True,
        notes="Test note",
    )
    assert new_t.title == "Created Task"
    assert new_t.planned == "2026-11-07"
    assert new_t.focus is True
    assert len(mgr.tasks_for_date("2026-11-07")) == 3


def test_task_manager_carry_over_task(mock_notion_env):
    mgr = mock_notion_env
    old_t, new_t = mgr.carry_over_task("p1", "2026-11-08")
    assert old_t.status == "Not done"
    assert new_t.title == old_t.title
    assert new_t.planned == "2026-11-08"
    assert new_t.carried_over is True
    assert "Carried over" in new_t.notes


class DummyTerminal(TerminalController):
    def __init__(self, key_sequence: list[str], prompt_answers: list[str] | None = None):
        super().__init__(StringIO(), StringIO())
        self.keys = list(key_sequence)
        self.prompts = list(prompt_answers or [])
        self.is_tty = False

    def get_key(self) -> str:
        if self.keys:
            return self.keys.pop(0)
        return "q"

    def prompt(self, prompt_text: str, default: str = "") -> str:
        if self.prompts:
            return self.prompts.pop(0)
        return default


def test_viewer_rendering_and_navigation(mock_notion_env):
    mgr = mock_notion_env
    term = DummyTerminal(key_sequence=["right", "left", "q"])
    viewer = DailyTasksViewer(mgr, initial_date=date(2026, 11, 7), terminal=term)

    # Initial render
    out = viewer.render()
    assert "DAILY TASKS VIEWER" in out
    assert "Saturday, 07 November 2026" in out
    assert "Task 1" in out
    assert "Task 2" in out

    # Handle right arrow
    viewer.handle_key("right")
    assert viewer.current_date_str == "2026-11-08"
    assert "Task 3" in viewer.render()

    # Handle left arrow
    viewer.handle_key("left")
    assert viewer.current_date_str == "2026-11-07"

    # Tab jump to next date with tasks
    viewer.handle_key("tab")
    assert viewer.current_date_str == "2026-11-08"


def test_viewer_task_actions(mock_notion_env):
    mgr = mock_notion_env
    term = DummyTerminal(key_sequence=["space", "f", "q"])
    viewer = DailyTasksViewer(mgr, initial_date=date(2026, 11, 7), terminal=term)

    # Toggle task #1 (originally To do -> Done)
    viewer.selected_index = 0
    viewer.handle_key("space")
    assert mgr.tasks["p1"].status == "Done"

    # Toggle focus
    viewer.handle_key("f")
    assert mgr.tasks["p1"].focus is False  # was initially True


def test_viewer_esc_does_not_quit_but_q_does(mock_notion_env):
    mgr = mock_notion_env
    viewer = DailyTasksViewer(mgr, initial_date=date(2026, 11, 7))
    assert viewer.running is True
    viewer.handle_key("esc")
    assert viewer.running is True  # ESC should not close the view
    viewer.handle_key("q")
    assert viewer.running is False  # q closes the view


def test_sync_contribution_calendar(mock_notion_env):
    mgr = mock_notion_env
    # Initially p2 is Done on 2026-11-07
    res = mgr.sync_contribution_calendar()
    assert res["days"] == 1
    assert res["created"] == 1
    assert res["total_done"] == 1

    # Now mark p1 as Done too
    mgr.toggle_done("p1")
    res2 = mgr.sync_contribution_calendar()
    assert res2["days"] == 1
    assert res2["updated"] == 1
    assert res2["total_done"] == 2


def test_viewer_press_u_syncs_calendar(mock_notion_env):
    mgr = mock_notion_env
    viewer = DailyTasksViewer(mgr, initial_date=date(2026, 11, 7))
    viewer.handle_key("u")
    assert "Contribution Calendar updated" in viewer.status_message


def test_terminal_arrow_key_parsing(monkeypatch):
    import os
    import select
    import termios
    import tty
    from types import SimpleNamespace

    dummy_file = SimpleNamespace(fileno=lambda: 0, isatty=lambda: True)
    controller = TerminalController(in_file=dummy_file, out_file=StringIO())
    controller.is_tty = True

    # Mock termios and tty to not fail on non-pty
    monkeypatch.setattr(termios, "tcgetattr", lambda fd: [])
    monkeypatch.setattr(termios, "tcsetattr", lambda fd, when, settings: None)
    monkeypatch.setattr(tty, "setraw", lambda fd: None)

    # Test each escape sequence
    test_cases = [
        (b"\x1b[A", "up"),
        (b"\x1b[B", "down"),
        (b"\x1b[C", "right"),
        (b"\x1b[D", "left"),
        (b"\x1bOA", "up"),
        (b"\x1bOB", "down"),
        (b"\x1bOC", "right"),
        (b"\x1bOD", "left"),
        (b"\x1b[Z", "shift_tab"),
        (b"\x1b", "esc"),
        (b"q", "q"),
        (b" ", "space"),
    ]

    for byte_seq, expected in test_cases:
        # Simulate os.read returning the first byte then any remaining bytes
        first_byte = byte_seq[:1]
        rest = byte_seq[1:]
        calls = {"n": 0}

        def mock_read(fd, n):
            calls["n"] += 1
            if calls["n"] == 1:
                return first_byte
            return rest

        monkeypatch.setattr(os, "read", mock_read)
        monkeypatch.setattr(select, "select", lambda r, w, x, t: ([r], [], []) if rest else ([], [], []))

        result = controller.get_key()
        assert result == expected, f"Failed for {byte_seq!r}: got {result!r}, expected {expected!r}"


def test_dayglass_bridge_sync(tmp_path):
    import sqlite3
    from personal_hq.task_viewer import DayglassBridge

    db_path = tmp_path / "dayglass.sqlite3"
    bridge = DayglassBridge(db_path)
    assert bridge.is_available is True

    # 1. Sync new task
    item = TaskItem(
        id="notion-t1",
        title="Sync Task 1",
        status="To do",
        planned="2026-11-07",
        notes="Important notes",
    )
    bridge.sync_task(item)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM tasks WHERE notion_id = 'notion-t1'").fetchall()
        assert len(rows) == 1
        cols = {desc[0]: val for desc, val in zip(conn.execute("SELECT * FROM tasks").description, rows[0])}
        assert cols["title"] == "Sync Task 1"
        assert cols["task_date"] == "2026-11-07"
        assert cols["completed_at"] is None
        assert cols["notes"] == "Important notes"

    # 2. Update task completion
    item.status = "Done"
    item.completed_on = "2026-11-07"
    bridge.sync_task(item)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT completed_at FROM tasks WHERE notion_id = 'notion-t1'").fetchone()
        assert row[0] is not None

    # 3. Delete task
    bridge.delete_task("notion-t1")
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM tasks WHERE notion_id = 'notion-t1'").fetchall()
        assert len(rows) == 0


def test_offline_manager_loader(real_extraction, projects_cfg, tmp_path):
    import json
    ext_path = tmp_path / "extraction.json"
    prj_path = tmp_path / "projects.json"
    ext_path.write_text(json.dumps(real_extraction), encoding="utf-8")
    prj_path.write_text(json.dumps(projects_cfg), encoding="utf-8")

    mgr = create_offline_manager(ext_path, prj_path)
    assert len(mgr.tasks) > 200
    dates = mgr.dates_with_tasks()
    assert len(dates) > 10
    tasks_sample = mgr.tasks_for_date(dates[0])
    assert len(tasks_sample) > 0
