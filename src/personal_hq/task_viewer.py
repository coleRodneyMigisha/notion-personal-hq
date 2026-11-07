"""Interactive Daily Tasks Viewer: skim through days, see tasks, and edit in real time."""
from __future__ import annotations

import copy
import logging
import os
import re
import select
import sqlite3
import sys
import termios
import tty
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from .data_mapper import Mapper
from .notion_api import NotionGateway, plain_text
from .state import State

log = logging.getLogger("personal_hq.task_viewer")
Json = dict[str, Any]

# ANSI escape styling
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
ITALIC = "\033[3m"
UNDERLINE = "\033[4m"

GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RED = "\033[31m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"
WHITE = "\033[37m"
GRAY = "\033[90m"

BG_GRAY = "\033[48;5;236m"
CLEAR_SCREEN = "\033[2J\033[H"

STATUS_ORDER = ["To do", "Done", "Not done", "Dropped", "Needs review"]
STATUS_BADGES = {
    "Done": f"{GREEN}[✓] Done{RESET}",
    "To do": f"{CYAN}[ ] To do{RESET}",
    "Not done": f"{YELLOW}[✗] Not done{RESET}",
    "Dropped": f"{GRAY}[-] Dropped{RESET}",
    "Needs review": f"{MAGENTA}[?] Needs review{RESET}",
}


@dataclass
class TaskItem:
    id: str
    title: str
    status: str = "To do"
    planned: str | None = None  # "YYYY-MM-DD"
    time: str = ""
    focus: bool = False
    project_id: str | None = None
    project_name: str | None = None
    notes: str = ""
    carried_over: bool = False
    completed_on: str | None = None
    area: str | None = None


def task_from_page(page: Json, projects: dict[str, str] | None = None) -> TaskItem:
    props = page.get("properties", {})
    title_parts = props.get("Task", {}).get("title") or []
    t_title = plain_text(title_parts)

    status_dict = props.get("Status", {}).get("select") or {}
    status = status_dict.get("name") or "To do"

    planned_prop = props.get("Planned", {}).get("date") or {}
    planned = planned_prop.get("start")
    if planned and len(planned) >= 10:
        planned = planned[:10]

    time_parts = props.get("Time", {}).get("rich_text") or []
    time_str = plain_text(time_parts)

    focus = bool(props.get("Focus", {}).get("checkbox"))

    proj_rel = props.get("Project", {}).get("relation") or []
    proj_id = proj_rel[0]["id"] if proj_rel else None
    proj_name = projects.get(proj_id) if proj_id and projects else None

    notes_parts = props.get("Notes", {}).get("rich_text") or []
    notes = plain_text(notes_parts)

    carried = bool(props.get("Carried over", {}).get("checkbox"))

    comp_prop = props.get("Completed on", {}).get("date") or {}
    completed_on = comp_prop.get("start")

    area_dict = props.get("Area", {}).get("select") or {}
    area_name = area_dict.get("name")

    return TaskItem(
        id=page["id"],
        title=t_title,
        status=status,
        planned=planned,
        time=time_str,
        focus=focus,
        project_id=proj_id,
        project_name=proj_name,
        notes=notes,
        carried_over=carried,
        completed_on=completed_on,
        area=area_name,
    )


def parse_target_date(user_input: str, current_date: date | None = None) -> date | None:
    """Parse dates from user input (supports today, yesterday, tomorrow, +N, -N, YYYY-MM-DD, etc.)."""
    if not user_input:
        return None
    raw = user_input.strip().lower()
    today = date.today()
    curr = current_date or today

    if raw in ("today", "t"):
        return today
    if raw in ("tomorrow", "tom"):
        return today + timedelta(days=1)
    if raw in ("yesterday", "yest"):
        return today - timedelta(days=1)

    if raw.startswith("+") and raw[1:].isdigit():
        return curr + timedelta(days=int(raw[1:]))
    if raw.startswith("-") and raw[1:].isdigit():
        return curr - timedelta(days=int(raw[1:]))

    try:
        return date.fromisoformat(raw)
    except ValueError:
        pass

    try:
        parts = raw.split("-")
        if len(parts) == 2:
            return date(today.year, int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        pass

    for sep in ("/", "-"):
        try:
            parts = [int(p) for p in raw.split(sep)]
            if len(parts) == 3:
                if parts[0] > 1000:
                    return date(parts[0], parts[1], parts[2])
                return date(parts[2], parts[1], parts[0])
        except (ValueError, IndexError):
            pass

    return None


def format_relative_day(target: date, today: date | None = None) -> str:
    today = today or date.today()
    diff = (target - today).days
    if diff == 0:
        return "Today"
    if diff == 1:
        return "Tomorrow"
    if diff == -1:
        return "Yesterday"
    if diff > 1:
        return f"+{diff} days"
    return f"{diff} days"


def level_for_count(count: int) -> str:
    """GitHub-style intensity buckets for Contribution Calendar."""
    if count <= 0:
        return "None"
    if count <= 2:
        return "Low"
    if count <= 5:
        return "Medium"
    if count <= 8:
        return "High"
    return "Very High"


def get_dayglass_db_path() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "dayglass" / "dayglass.sqlite3"


class DayglassBridge:
    """Synchronizes Notion tasks directly into Dayglass's SQLite database."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or get_dayglass_db_path()

    @property
    def is_available(self) -> bool:
        return self.db_path.parent.exists() or self.db_path.exists()

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL CHECK (length(trim(title)) > 0),
                task_date TEXT NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                completed_at TEXT,
                carried_from_task_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                notes TEXT NOT NULL DEFAULT '',
                notion_id TEXT
            )
            """
        )
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        if "notion_id" not in existing_cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN notion_id TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_notion_id ON tasks(notion_id)")
        conn.commit()

    def sync_task(self, task: TaskItem) -> None:
        """Upsert a TaskItem from Notion into Dayglass SQLite."""
        if not self.is_available or not task.planned:
            return
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.db_path) as conn:
                self._ensure_schema(conn)
                completed_at = (task.completed_on or datetime.now().isoformat()) if task.status == "Done" else None

                # Check if task already exists by notion_id
                row = conn.execute("SELECT id FROM tasks WHERE notion_id = ?", (task.id,)).fetchone()
                if row:
                    conn.execute(
                        """
                        UPDATE tasks SET
                            title = ?,
                            task_date = ?,
                            completed_at = ?,
                            notes = ?
                        WHERE id = ?
                        """,
                        (task.title, task.planned, completed_at, task.notes or "", row[0]),
                    )
                else:
                    # Check if unlinked task with same title and date exists
                    row2 = conn.execute(
                        "SELECT id FROM tasks WHERE task_date = ? AND lower(trim(title)) = lower(trim(?)) AND notion_id IS NULL",
                        (task.planned, task.title),
                    ).fetchone()
                    if row2:
                        conn.execute(
                            "UPDATE tasks SET notion_id = ?, completed_at = ?, notes = ? WHERE id = ?",
                            (task.id, completed_at, task.notes or "", row2[0]),
                        )
                    else:
                        pos_row = conn.execute(
                            "SELECT COALESCE(MAX(position), -1) + 1 FROM tasks WHERE task_date = ?",
                            (task.planned,),
                        ).fetchone()
                        pos = pos_row[0] if pos_row else 0
                        conn.execute(
                            """
                            INSERT INTO tasks (title, task_date, position, completed_at, notes, notion_id)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (task.title, task.planned, pos, completed_at, task.notes or "", task.id),
                        )
                conn.commit()
        except Exception as exc:
            log.debug(f"Could not sync task to Dayglass SQLite: {exc}")

    def delete_task(self, task_id: str) -> None:
        """Remove task from Dayglass SQLite if deleted/dropped."""
        if not self.db_path.exists():
            return
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM tasks WHERE notion_id = ?", (task_id,))
                conn.commit()
        except Exception as exc:
            log.debug(f"Could not delete task from Dayglass SQLite: {exc}")

    def sync_all_tasks(self, tasks: list[TaskItem]) -> int:
        """Sync a batch of Notion tasks into Dayglass SQLite."""
        synced = 0
        for t in tasks:
            if t.planned:
                self.sync_task(t)
                synced += 1
        return synced


class TaskManager:
    """Manages querying, indexing by date, and editing tasks via Notion API."""

    def __init__(
        self,
        gw: Any,
        tasks_ds_id: str,
        tasks_db_id: str = "",
        projects_ds_id: str = "",
        projects_map: dict[str, str] | None = None,
        state: Any = None,
        dayglass_bridge: DayglassBridge | None = None,
    ):
        self.gw = gw
        self.tasks_ds_id = tasks_ds_id
        self.tasks_db_id = tasks_db_id
        self.projects_ds_id = projects_ds_id
        self.projects_map: dict[str, str] = dict(projects_map or {})
        self.state = state
        self.dayglass_bridge = dayglass_bridge or DayglassBridge()
        self.tasks: dict[str, TaskItem] = {}
        self.tasks_by_date: dict[str, list[TaskItem]] = {}
        self.undated_tasks: list[TaskItem] = []

    def load(self) -> None:
        """Load projects and all tasks into memory for fast zero-latency day skimming."""
        if self.projects_ds_id and not self.projects_map:
            try:
                for p in self.gw.query_data_source(self.projects_ds_id):
                    p_title = plain_text(p.get("properties", {}).get("Project", {}).get("title") or [])
                    if p_title:
                        self.projects_map[p["id"]] = p_title
            except Exception as exc:
                log.warning(f"Could not load projects map: {exc}")

        self.tasks.clear()
        self.tasks_by_date.clear()
        self.undated_tasks.clear()

        pages = list(self.gw.query_data_source(self.tasks_ds_id))
        for page in pages:
            task = task_from_page(page, self.projects_map)
            self.tasks[task.id] = task
            if task.planned:
                self.tasks_by_date.setdefault(task.planned, []).append(task)
            else:
                self.undated_tasks.append(task)

        # Sort tasks within each day by Time, then Focus, then Title
        for d in self.tasks_by_date:
            self._sort_tasks_for_date(d)

        if self.dayglass_bridge and self.dayglass_bridge.is_available:
            try:
                self.dayglass_bridge.sync_all_tasks(list(self.tasks.values()))
            except Exception as exc:
                log.debug(f"Could not sync tasks to Dayglass SQLite: {exc}")

    def _sort_tasks_for_date(self, date_str: str) -> None:
        if date_str in self.tasks_by_date:
            self.tasks_by_date[date_str].sort(
                key=lambda t: (
                    0 if t.time else 1,
                    t.time or "",
                    0 if t.focus else 1,
                    t.title.lower(),
                )
            )

    def dates_with_tasks(self) -> list[str]:
        return sorted([d for d, items in self.tasks_by_date.items() if items])

    def next_date_with_tasks(self, current_date_str: str) -> str | None:
        dates = self.dates_with_tasks()
        for d in dates:
            if d > current_date_str:
                return d
        return None

    def prev_date_with_tasks(self, current_date_str: str) -> str | None:
        dates = self.dates_with_tasks()
        for d in reversed(dates):
            if d < current_date_str:
                return d
        return None

    def tasks_for_date(self, date_str: str) -> list[TaskItem]:
        return self.tasks_by_date.get(date_str, [])

    def toggle_done(self, task_id: str) -> TaskItem:
        task = self.tasks[task_id]
        new_status = "To do" if task.status == "Done" else "Done"
        new_completed_on = date.today().isoformat() if new_status == "Done" else None

        props: Json = {
            "Status": {"select": {"name": new_status}},
            "Completed on": {"date": {"start": new_completed_on}} if new_completed_on else {"date": None},
        }
        self.gw.update_page(task_id, props)
        task.status = new_status
        task.completed_on = new_completed_on
        if self.dayglass_bridge:
            self.dayglass_bridge.sync_task(task)
        return task

    def toggle_focus(self, task_id: str) -> TaskItem:
        task = self.tasks[task_id]
        new_focus = not task.focus
        props: Json = {"Focus": {"checkbox": new_focus}}
        self.gw.update_page(task_id, props)
        task.focus = new_focus
        if task.planned:
            self._sort_tasks_for_date(task.planned)
        if self.dayglass_bridge:
            self.dayglass_bridge.sync_task(task)
        return task

    def set_status(self, task_id: str, new_status: str) -> TaskItem:
        task = self.tasks[task_id]
        completed_on = task.completed_on
        if new_status == "Done" and not completed_on:
            completed_on = date.today().isoformat()
        elif new_status != "Done":
            completed_on = None

        props: Json = {
            "Status": {"select": {"name": new_status}},
            "Completed on": {"date": {"start": completed_on}} if completed_on else {"date": None},
        }
        self.gw.update_page(task_id, props)
        task.status = new_status
        task.completed_on = completed_on
        if self.dayglass_bridge:
            self.dayglass_bridge.sync_task(task)
        return task

    def edit_task(
        self,
        task_id: str,
        title: str | None = None,
        time_str: str | None = None,
        notes: str | None = None,
    ) -> TaskItem:
        task = self.tasks[task_id]
        props: Json = {}
        if title is not None:
            props["Task"] = {"title": [{"type": "text", "text": {"content": title[:2000]}}]}
            task.title = title
        if time_str is not None:
            props["Time"] = {"rich_text": [{"type": "text", "text": {"content": time_str[:2000]}}]} if time_str else {"rich_text": []}
            task.time = time_str
        if notes is not None:
            props["Notes"] = {"rich_text": [{"type": "text", "text": {"content": notes[:2000]}}]} if notes else {"rich_text": []}
            task.notes = notes

        if props:
            self.gw.update_page(task_id, props)
        if task.planned:
            self._sort_tasks_for_date(task.planned)
        if self.dayglass_bridge:
            self.dayglass_bridge.sync_task(task)
        return task

    def move_task(self, task_id: str, new_date_str: str) -> TaskItem:
        task = self.tasks[task_id]
        old_date = task.planned

        props: Json = {"Planned": {"date": {"start": new_date_str}}}
        self.gw.update_page(task_id, props)

        # Remove from old date list
        if old_date and old_date in self.tasks_by_date:
            self.tasks_by_date[old_date] = [t for t in self.tasks_by_date[old_date] if t.id != task_id]
            if not self.tasks_by_date[old_date]:
                del self.tasks_by_date[old_date]

        task.planned = new_date_str
        self.tasks_by_date.setdefault(new_date_str, []).append(task)
        self._sort_tasks_for_date(new_date_str)
        if self.dayglass_bridge:
            self.dayglass_bridge.sync_task(task)
        return task

    def carry_over_task(self, task_id: str, target_date_str: str) -> tuple[TaskItem, TaskItem]:
        """Carry over a task: mark current Not done, and create a duplicate on target date."""
        old_task = self.set_status(task_id, "Not done")

        new_task = self.add_task(
            date_str=target_date_str,
            title=old_task.title,
            time_str=old_task.time,
            focus=old_task.focus,
            notes=f"Carried over from {old_task.planned or 'earlier'}. " + (old_task.notes or ""),
            project_id=old_task.project_id,
            carried_over=True,
            area=old_task.area,
        )
        return old_task, new_task

    def add_task(
        self,
        date_str: str,
        title: str,
        time_str: str = "",
        focus: bool = False,
        notes: str = "",
        project_id: str | None = None,
        carried_over: bool = False,
        area: str | None = None,
        status: str = "To do",
    ) -> TaskItem:
        props: Json = {
            "Task": {"title": [{"type": "text", "text": {"content": title[:2000]}}]},
            "Status": {"select": {"name": status}},
            "Planned": {"date": {"start": date_str}},
            "Focus": {"checkbox": focus},
            "Carried over": {"checkbox": carried_over},
        }
        if time_str:
            props["Time"] = {"rich_text": [{"type": "text", "text": {"content": time_str[:2000]}}]}
        if notes:
            props["Notes"] = {"rich_text": [{"type": "text", "text": {"content": notes[:2000]}}]}
        if project_id:
            props["Project"] = {"relation": [{"id": project_id}]}
        if area:
            props["Area"] = {"select": {"name": area}}

        body = {
            "parent": {"data_source_id": self.tasks_ds_id, "type": "data_source_id"},
            "properties": props,
        }
        try:
            page = self.gw.create_page(body)
        except Exception:
            if self.tasks_db_id:
                body["parent"] = {"database_id": self.tasks_db_id, "type": "database_id"}
                page = self.gw.create_page(body)
            else:
                raise

        new_item = task_from_page(page, self.projects_map)
        # Fallbacks in case returned object has unpopulated relations
        if not new_item.project_name and project_id in self.projects_map:
            new_item.project_name = self.projects_map[project_id]
        if not new_item.title:
            new_item.title = title
        if not new_item.planned:
            new_item.planned = date_str

        self.tasks[new_item.id] = new_item
        self.tasks_by_date.setdefault(date_str, []).append(new_item)
        self._sort_tasks_for_date(date_str)
        if self.dayglass_bridge:
            self.dayglass_bridge.sync_task(new_item)
        return new_item

    def sync_contribution_calendar(self) -> dict[str, Any]:
        """Aggregate completed tasks and update the Contribution Calendar in Notion."""
        counts: dict[date, int] = defaultdict(int)
        for task in self.tasks.values():
            if task.status == "Done":
                d = None
                for candidate in (task.completed_on, task.planned):
                    if candidate:
                        try:
                            d = date.fromisoformat(str(candidate)[:10])
                            break
                        except ValueError:
                            pass
                if d:
                    counts[d] += 1

        total_done = sum(counts.values())
        if not self.state or "databases" not in self.state:
            return {"days": len(counts), "created": 0, "updated": 0, "total_done": total_done}

        contrib_info = self.state["databases"].get("contribution_calendar")
        if not contrib_info or not contrib_info.get("data_source_id"):
            return {"days": len(counts), "created": 0, "updated": 0, "total_done": total_done}

        contrib_ds = contrib_info["data_source_id"]
        contrib_db_id = contrib_info.get("database_id", "")

        existing: dict[str, tuple[str, int | None]] = {}
        try:
            for p in self.gw.query_data_source(contrib_ds):
                props = p.get("properties", {})
                iid_prop = props.get("Import ID") or {}
                iid = plain_text(iid_prop.get("rich_text") or iid_prop.get("title") or [])
                cnt_prop = props.get("Completed") or {}
                cnt_val = cnt_prop.get("number")
                if iid:
                    existing[iid] = (p["id"], cnt_val)
        except Exception as exc:
            log.warning(f"Could not query existing contribution calendar pages: {exc}")

        # Fallback to state records
        cached_records = self.state.get("records", {}).get("contribution_calendar", {})
        for iid, pid in cached_records.items():
            existing.setdefault(iid, (pid, None))

        created = updated = skipped = 0
        for day, cnt in sorted(counts.items()):
            import_id = f"contrib-{day.isoformat()}"
            level = level_for_count(cnt)
            props: Json = {
                "Day": {"title": [{"type": "text", "text": {"content": day.isoformat()}}]},
                "Date": {"date": {"start": day.isoformat()}},
                "Completed": {"number": cnt},
                "Level": {"select": {"name": level}},
                "Import ID": {"rich_text": [{"type": "text", "text": {"content": import_id}}]},
            }
            if import_id in existing:
                pid, prev_cnt = existing[import_id]
                if prev_cnt != cnt:
                    self.gw.update_page(pid, props)
                    updated += 1
                else:
                    skipped += 1
                if hasattr(self.state, "record"):
                    self.state.record("contribution_calendar", import_id, pid)
            else:
                body = {
                    "parent": {"data_source_id": contrib_ds, "type": "data_source_id"},
                    "properties": props,
                }
                try:
                    page = self.gw.create_page(body)
                except Exception:
                    if contrib_db_id:
                        body["parent"] = {"database_id": contrib_db_id, "type": "database_id"}
                        page = self.gw.create_page(body)
                    else:
                        raise
                created += 1
                if page and page.get("id"):
                    existing[import_id] = (page["id"], cnt)
                    if hasattr(self.state, "record"):
                        self.state.record("contribution_calendar", import_id, page["id"])

        if (created or updated) and hasattr(self.state, "save"):
            self.state.save()

        return {
            "days": len(counts),
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "total_done": total_done,
        }


class TerminalController:
    """Manages raw single-key terminal input and ANSI screen rendering."""

    def __init__(self, in_file=None, out_file=None):
        self.in_file = in_file or sys.stdin
        self.out_file = out_file or sys.stdout
        self.is_tty = hasattr(self.in_file, "isatty") and self.in_file.isatty()

    def get_key(self) -> str:
        """Read a single keypress or ANSI escape sequence."""
        if not self.is_tty:
            line = self.in_file.readline()
            return line.strip()

        fd = self.in_file.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            # Use raw unbuffered OS read so Python TextIOWrapper doesn't buffer and swallow bytes
            raw_bytes = os.read(fd, 1)
            if not raw_bytes:
                return ""

            if raw_bytes == b"\x1b":
                # Check if escape sequence continuation bytes are present
                r, _, _ = select.select([fd], [], [], 0.05)
                if r:
                    more = os.read(fd, 31)
                    raw_bytes += more

            KEY_MAP = {
                b"\x1b[A": "up",
                b"\x1b[B": "down",
                b"\x1b[C": "right",
                b"\x1b[D": "left",
                b"\x1bOA": "up",
                b"\x1bOB": "down",
                b"\x1bOC": "right",
                b"\x1bOD": "left",
                b"\x1b[1;2A": "up",
                b"\x1b[1;2B": "down",
                b"\x1b[1;2C": "right",
                b"\x1b[1;2D": "left",
                b"\x1b[Z": "shift_tab",
            }
            for seq, key_name in KEY_MAP.items():
                if raw_bytes.startswith(seq):
                    return key_name

            if raw_bytes == b"\x1b":
                return "esc"
            elif raw_bytes == b"\t":
                return "tab"
            elif raw_bytes in (b"\r", b"\n"):
                return "enter"
            elif raw_bytes == b" ":
                return "space"
            elif raw_bytes in (b"\x7f", b"\x08"):
                return "backspace"
            elif raw_bytes == b"\x03":  # Ctrl+C
                raise KeyboardInterrupt

            try:
                return raw_bytes.decode("utf-8", errors="ignore")
            except Exception:
                return ""
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    def prompt(self, prompt_text: str, default: str = "") -> str:
        """Prompt user for a line of text, temporarily restoring cooked mode."""
        self.out_file.write(prompt_text)
        self.out_file.flush()
        line = self.in_file.readline()
        res = line.strip()
        return res if res else default

    def write(self, text: str) -> None:
        self.out_file.write(text)
        self.out_file.flush()


class DailyTasksViewer:
    """The main interactive Daily Tasks Viewer application."""

    def __init__(
        self,
        manager: TaskManager,
        initial_date: date | None = None,
        terminal: TerminalController | None = None,
    ):
        self.manager = manager
        self.current_date = initial_date or date.today()
        self.terminal = terminal or TerminalController()
        self.selected_index = 0
        self.status_message = "Ready. Use [←/→] to change day, [↑/↓] to select task."
        self.running = True

    @property
    def current_date_str(self) -> str:
        return self.current_date.isoformat()

    def get_current_tasks(self) -> list[TaskItem]:
        return self.manager.tasks_for_date(self.current_date_str)

    def render(self) -> str:
        tasks = self.get_current_tasks()
        d = self.current_date
        today = date.today()
        rel = format_relative_day(d, today)
        day_str = d.strftime("%A, %d %B %Y")

        done_cnt = sum(1 for t in tasks if t.status == "Done")
        todo_cnt = sum(1 for t in tasks if t.status == "To do")
        focus_cnt = sum(1 for t in tasks if t.focus)

        lines = [
            CLEAR_SCREEN,
            f"{BOLD}{CYAN}═" * 80 + RESET,
            f"{BOLD} ☀️  DAILY TASKS VIEWER {RESET}{GRAY}— Personal HQ{RESET}",
            f"{BOLD}{CYAN}═" * 80 + RESET,
            f"  {BOLD}‹ Prev Day{RESET} [h/←]  │  {BOLD}{WHITE}{day_str}{RESET} ({CYAN}{rel}{RESET})  │  {BOLD}Next Day{RESET} [l/→] ›",
            f"{GRAY}─" * 80 + RESET,
            f"  {BOLD}Summary:{RESET} {len(tasks)} tasks  •  {GREEN}{done_cnt} Done{RESET}  •  {CYAN}{todo_cnt} To do{RESET}  •  {YELLOW}{focus_cnt} Focus ★{RESET}",
            f"{GRAY}─" * 80 + RESET,
            "",
            f"   #   Status      Time         Focus  Task & Details",
            f"  {GRAY}" + "─" * 74 + RESET,
        ]

        if not tasks:
            lines.append(f"       {GRAY}(No tasks planned for this day. Press 'a' to add one, or [Tab] for next day with tasks.){RESET}")
            lines.append("")
        else:
            for idx, task in enumerate(tasks, 1):
                is_selected = idx - 1 == self.selected_index
                ptr = f"{BOLD}{CYAN}> {RESET}" if is_selected else "  "

                badge = STATUS_BADGES.get(task.status, f"[{task.status}]")
                # Pad status badge cleanly
                raw_badge_len = len(re.sub(r"\033\[[0-9;]*m", "", badge))
                badge_padded = badge + " " * max(0, 11 - raw_badge_len)

                time_str = f"{task.time:<11}" if task.time else "           "
                star = f"{YELLOW}★{RESET}" if task.focus else " "

                title_styled = f"{BOLD}{WHITE}{task.title}{RESET}" if is_selected else task.title
                if task.status == "Done":
                    title_styled = f"{DIM}{task.title}{RESET}"

                lines.append(f"{ptr}{idx:>2}   {badge_padded} {time_str}   {star}    {title_styled}")

                # Sub-details
                sub_parts = []
                if task.project_name:
                    sub_parts.append(f"{BLUE}Project:{RESET} {task.project_name}")
                if task.notes:
                    sub_parts.append(f"{GRAY}Note:{RESET} {task.notes}")
                if task.carried_over:
                    sub_parts.append(f"{YELLOW}↳ Carried over{RESET}")

                if sub_parts:
                    lines.append(f"       {' │ '.join(sub_parts)}")
            lines.append("")

        lines.extend([
            f"{GRAY}─" * 80 + RESET,
            f" {BOLD}[←/→ or h/l]{RESET} Prev/Next Day  •  {BOLD}[t]{RESET} Today  •  {BOLD}[g]{RESET} Go to Date  •  {BOLD}[Tab]{RESET} Jump Task Day",
            f" {BOLD}[↑/↓ or k/j]{RESET} Select Task    •  {BOLD}[Space/d]{RESET} Toggle Done  •  {BOLD}[f]{RESET} Focus  •  {BOLD}[s]{RESET} Status",
            f" {BOLD}[a]{RESET} Add  •  {BOLD}[e]{RESET} Edit  •  {BOLD}[m]{RESET} Move  •  {BOLD}[c]{RESET} Carry  •  {BOLD}[u]{RESET} Sync Cal  •  {BOLD}[r]{RESET} Refresh  •  {BOLD}[q]{RESET} Quit",
            f"{BOLD}{CYAN}═" * 80 + RESET,
            f" {BOLD}Status:{RESET} {self.status_message}",
        ])
        return "\n".join(lines)

    def handle_key(self, key: str) -> None:
        tasks = self.get_current_tasks()
        self.status_message = ""

        # Navigation
        if key in ("left", "h", "p"):
            self.current_date -= timedelta(days=1)
            self.selected_index = 0
            self.status_message = f"Moved to {self.current_date_str}"
        elif key in ("right", "l", "n"):
            self.current_date += timedelta(days=1)
            self.selected_index = 0
            self.status_message = f"Moved to {self.current_date_str}"
        elif key == "t":
            self.current_date = date.today()
            self.selected_index = 0
            self.status_message = "Jumped to Today"
        elif key in ("[", "P"):
            self.current_date -= timedelta(days=7)
            self.selected_index = 0
            self.status_message = f"Moved back 1 week to {self.current_date_str}"
        elif key in ("]", "N"):
            self.current_date += timedelta(days=7)
            self.selected_index = 0
            self.status_message = f"Moved forward 1 week to {self.current_date_str}"
        elif key in ("tab", "J"):
            next_d = self.manager.next_date_with_tasks(self.current_date_str)
            if next_d:
                self.current_date = date.fromisoformat(next_d)
                self.selected_index = 0
                self.status_message = f"Jumped to next day with tasks: {next_d}"
            else:
                self.status_message = "No later days with tasks found."
        elif key in ("shift_tab", "K"):
            prev_d = self.manager.prev_date_with_tasks(self.current_date_str)
            if prev_d:
                self.current_date = date.fromisoformat(prev_d)
                self.selected_index = 0
                self.status_message = f"Jumped to previous day with tasks: {prev_d}"
            else:
                self.status_message = "No earlier days with tasks found."
        elif key == "g":
            self.terminal.write("\n")
            target = self.terminal.prompt("Go to date (YYYY-MM-DD, +N, -N, today, tomorrow): ")
            parsed = parse_target_date(target, self.current_date)
            if parsed:
                self.current_date = parsed
                self.selected_index = 0
                self.status_message = f"Jumped to {self.current_date.isoformat()}"
            else:
                self.status_message = f"Invalid date: {target!r}"
        elif key in ("up", "k"):
            if tasks:
                self.selected_index = (self.selected_index - 1) % len(tasks)
        elif key in ("down", "j"):
            if tasks:
                self.selected_index = (self.selected_index + 1) % len(tasks)
        elif key.isdigit() and 1 <= int(key) <= len(tasks):
            self.selected_index = int(key) - 1

        # Task actions
        elif key in ("space", "d"):
            if tasks and 0 <= self.selected_index < len(tasks):
                task = tasks[self.selected_index]
                updated = self.manager.toggle_done(task.id)
                self.status_message = f"Task #{self.selected_index + 1} marked {updated.status} (synced to Notion)"
            else:
                self.status_message = "No task selected to toggle."
        elif key == "f":
            if tasks and 0 <= self.selected_index < len(tasks):
                task = tasks[self.selected_index]
                updated = self.manager.toggle_focus(task.id)
                star = "★ Focus on" if updated.focus else "Focus off"
                self.status_message = f"Task #{self.selected_index + 1}: {star}"
        elif key == "s":
            if tasks and 0 <= self.selected_index < len(tasks):
                task = tasks[self.selected_index]
                self.terminal.write("\n")
                self.terminal.write(f"Choose status for #{self.selected_index + 1}:\n")
                self.terminal.write("  [1] To do   [2] Done   [3] Not done   [4] Dropped   [5] Needs review\n")
                choice = self.terminal.prompt("Select (1-5): ")
                mapping = {"1": "To do", "2": "Done", "3": "Not done", "4": "Dropped", "5": "Needs review"}
                new_st = mapping.get(choice)
                if new_st:
                    self.manager.set_status(task.id, new_st)
                    self.status_message = f"Task #{self.selected_index + 1} status set to {new_st}"
                else:
                    self.status_message = "Cancelled or invalid status choice."
        elif key == "e":
            if tasks and 0 <= self.selected_index < len(tasks):
                task = tasks[self.selected_index]
                self.terminal.write("\n")
                new_title = self.terminal.prompt(f"Title [{task.title}]: ", default=task.title)
                new_time = self.terminal.prompt(f"Time slot [{task.time}]: ", default=task.time)
                new_notes = self.terminal.prompt(f"Notes [{task.notes}]: ", default=task.notes)
                self.manager.edit_task(task.id, title=new_title, time_str=new_time, notes=new_notes)
                self.status_message = f"Task #{self.selected_index + 1} updated."
        elif key == "m":
            if tasks and 0 <= self.selected_index < len(tasks):
                task = tasks[self.selected_index]
                self.terminal.write("\n")
                target = self.terminal.prompt(f"Move task to date (default: tomorrow): ", default="tomorrow")
                parsed = parse_target_date(target, self.current_date)
                if parsed:
                    self.manager.move_task(task.id, parsed.isoformat())
                    self.status_message = f"Moved task to {parsed.isoformat()}"
                    self.selected_index = max(0, min(self.selected_index, len(self.get_current_tasks()) - 1))
                else:
                    self.status_message = f"Invalid date: {target!r}"
        elif key == "c":
            if tasks and 0 <= self.selected_index < len(tasks):
                task = tasks[self.selected_index]
                self.terminal.write("\n")
                target = self.terminal.prompt(f"Carry over to date (default: tomorrow): ", default="tomorrow")
                parsed = parse_target_date(target, self.current_date)
                if parsed:
                    self.manager.carry_over_task(task.id, parsed.isoformat())
                    self.status_message = f"Carried over to {parsed.isoformat()} (current marked Not done)"
                else:
                    self.status_message = f"Invalid date: {target!r}"
        elif key in ("a", "+"):
            self.terminal.write("\n")
            title = self.terminal.prompt(f"New task title for {self.current_date_str}: ")
            if title:
                time_str = self.terminal.prompt("Time slot (e.g. 08:00-09:00, optional): ", default="")
                focus_raw = self.terminal.prompt("Focus priority? [y/N]: ", default="n")
                focus = focus_raw.lower().startswith("y")
                notes = self.terminal.prompt("Notes (optional): ", default="")
                new_item = self.manager.add_task(
                    date_str=self.current_date_str,
                    title=title,
                    time_str=time_str,
                    focus=focus,
                    notes=notes,
                )
                self.selected_index = len(self.get_current_tasks()) - 1
                self.status_message = f"Added task '{new_item.title}'"
            else:
                self.status_message = "Task creation cancelled (empty title)."
        elif key in ("r", "R"):
            self.status_message = "Refreshing from Notion..."
            self.manager.load()
            self.status_message = "Tasks refreshed from Notion."
        elif key in ("u", "U"):
            self.terminal.write("\nSyncing completed tasks with Contribution Calendar in Notion...\n")
            try:
                res = self.manager.sync_contribution_calendar()
                self.status_message = (
                    f"✓ Contribution Calendar updated: {res['days']} days synced "
                    f"({res['created']} created, {res['updated']} updated, {res['total_done']} tasks counted)."
                )
            except Exception as exc:
                self.status_message = f"Failed to sync Contribution Calendar: {exc}"
        elif key in ("q", "Q"):
            self.running = False
        elif key == "esc":
            self.status_message = "Ready."
        elif key == "?":
            self.show_help()

    def show_help(self) -> None:
        help_text = [
            CLEAR_SCREEN,
            f"{BOLD}{CYAN}═" * 80 + RESET,
            f"{BOLD} DAILY TASKS VIEWER — KEYBOARD SHORTCUTS {RESET}",
            f"{BOLD}{CYAN}═" * 80 + RESET,
            "",
            f"  {BOLD}Day Navigation:{RESET}",
            f"    [←] or [h] or [p]    Go to Previous Day",
            f"    [→] or [l] or [n]    Go to Next Day",
            f"    [t]                  Jump to Today",
            f"    [g]                  Go to specific date (supports YYYY-MM-DD, +N, -N, tomorrow)",
            f"    [ [ ] or [P]         Jump back 1 week (-7 days)",
            f"    [ ] ] or [N]         Jump forward 1 week (+7 days)",
            f"    [Tab] / [Shift-Tab]  Jump to next / previous day that has tasks",
            "",
            f"  {BOLD}Task Navigation & Selection:{RESET}",
            f"    [↑] or [k]           Select previous task",
            f"    [↓] or [j]           Select next task",
            f"    [1]..[9]             Select task directly by number",
            "",
            f"  {BOLD}Task Editing (updates Notion in real time):{RESET}",
            f"    [Space] or [d]       Toggle Done / To do (records Completed on date automatically)",
            f"    [f]                  Toggle Focus priority (★)",
            f"    [s]                  Change Status (To do / Done / Not done / Dropped / Needs review)",
            f"    [e]                  Edit task title, time, or notes",
            f"    [m]                  Move / reschedule task to another date",
            f"    [c]                  Carry over task (marks Not done, creates copy on new date)",
            f"    [a] or [+]           Add a new task for current day",
            "",
            f"  {BOLD}Calendar Sync & General:{RESET}",
            f"    [u] or [U]           Sync & update Contribution Calendar from completed tasks",
            f"    [r]                  Refresh all tasks from Notion",
            f"    [q]                  Quit the viewer",
            "",
            f"{GRAY}─" * 80 + RESET,
            f"  Press any key to return to daily tasks...",
        ]
        self.terminal.write("\n".join(help_text))
        self.terminal.get_key()

    def run(self) -> None:
        """Run the interactive viewer loop."""
        try:
            while self.running:
                screen = self.render()
                self.terminal.write(screen)
                key = self.terminal.get_key()
                self.handle_key(key)
        except KeyboardInterrupt:
            pass
        finally:
            self.terminal.write("\nExiting Daily Tasks Viewer. Goodbye!\n")


def create_offline_manager(
    extraction_path: Path,
    projects_path: Path,
) -> TaskManager:
    """Build an in-memory TaskManager from extraction data for offline mode."""
    import json
    from .notion_api import InMemoryNotion

    extraction = json.loads(extraction_path.read_text(encoding="utf-8"))
    projects_cfg = json.loads(projects_path.read_text(encoding="utf-8"))

    gw = InMemoryNotion()
    # Create fake databases
    tasks_ds_id = "offline-tasks-ds"
    projects_ds_id = "offline-projects-ds"
    contrib_ds_id = "offline-contrib-ds"
    gw.objects[tasks_ds_id] = {"object": "data_source", "id": tasks_ds_id, "properties": {}}
    gw.rows[tasks_ds_id] = []
    gw.objects[contrib_ds_id] = {"object": "data_source", "id": contrib_ds_id, "properties": {}}
    gw.rows[contrib_ds_id] = []

    mock_state = {
        "databases": {
            "contribution_calendar": {"data_source_id": contrib_ds_id, "database_id": "offline-contrib-db"}
        },
        "records": {"contribution_calendar": {}}
    }

    mapper = Mapper(extraction, projects_cfg)
    records = mapper.build()

    projects_map = {}
    for prec in records.get("projects", []):
        projects_map[prec.import_id] = prec.title

    for trec in records.get("tasks", []):
        body = {
            "parent": {"data_source_id": tasks_ds_id, "type": "data_source_id"},
            "properties": trec.properties,
        }
        gw.create_page(body)

    mgr = TaskManager(
        gw=gw,
        tasks_ds_id=tasks_ds_id,
        tasks_db_id="offline-tasks-db",
        projects_ds_id=projects_ds_id,
        projects_map=projects_map,
        state=mock_state,
    )
    mgr.load()
    return mgr
