"""The workspace design as plain data: databases, relations, views, dashboard.

Read this file to see exactly what the builder creates. To change the design,
change it here; the builder only adds what is missing and never deletes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

Json = dict[str, Any]

SYSTEM_PAGE_TITLE = "Personal HQ System"
DASHBOARD_MARKER = "personal-hq-dashboard:v1"

# Life areas (codes are used in data/extracted/extraction.json).
AREAS = {
    "ACAD": ("Coursework", "blue"),
    "RES": ("Research & final-year project", "purple"),
    "TECH": ("Tech skills & side projects", "green"),
    "LEAD": ("Leadership & service", "orange"),
    "FAITH": ("Faith & fellowship", "yellow"),
    "HEALTH": ("Health & fitness", "red"),
    "BIZ": ("Business", "brown"),
    "PERS": ("Personal & admin", "gray"),
    "BRAND": ("Blogs & portfolio", "pink"),
}

TASK_STATUSES = [("To do", "gray"), ("Done", "green"), ("Not done", "red"),
                 ("Dropped", "default"), ("Needs review", "orange")]
GOAL_STATUSES = [("Active", "blue"), ("Achieved", "green"), ("Missed", "red"),
                 ("Dropped", "default"), ("Needs review", "orange")]
PROJECT_STATUSES = [("Active", "blue"), ("On hold", "yellow"), ("Done", "green"),
                    ("Dropped", "default"), ("Needs review", "orange")]
HORIZONS = [("Long-term", "purple"), ("Semester", "blue"), ("Month", "green"), ("Week", "yellow")]
NOTE_TYPES = [("Capture", "gray"), ("Reflection", "green"), ("Learning", "blue"), ("Log", "brown"),
              ("Day review", "yellow"), ("Reference", "purple")]
SOURCE_MARKS = [("tick", "green"), ("cross", "red"), ("marked", "blue"), ("empty", "gray"),
                ("filled", "orange"), ("unclear", "yellow")]


def _select(options: list[tuple[str, str]]) -> Json:
    return {"type": "select", "select": {"options": [{"name": n, "color": c} for n, c in options]}}


TITLE: Json = {"type": "title", "title": {}}
TEXT: Json = {"type": "rich_text", "rich_text": {}}
DATE: Json = {"type": "date", "date": {}}
CHECKBOX: Json = {"type": "checkbox", "checkbox": {}}
AREA: Json = _select(list(AREAS.values()))


@dataclass(frozen=True)
class DatabaseSpec:
    key: str
    title: str
    icon: str
    purpose: str
    properties: Json

    @property
    def title_property(self) -> str:
        return next(name for name, p in self.properties.items() if p["type"] == "title")


DATABASES: list[DatabaseSpec] = [
    DatabaseSpec("projects", "Projects", "📁", "Multi-step efforts that group tasks and goals.", {
        "Project": TITLE,
        "Status": _select(PROJECT_STATUSES),
        "Area": AREA,
        "Outcome": TEXT,
        "Next action": TEXT,
        "Start": DATE,
        "Target": DATE,
        "Import ID": TEXT,
    }),
    DatabaseSpec("weeks", "Weeks", "🗓️", "One page per week: plan on Sunday, review the next Sunday.", {
        "Week": TITLE,
        "Dates": DATE,
        "Focus": TEXT,
        "Wins": TEXT,
        "What slipped & why": TEXT,
        "Lessons": TEXT,
        "Adjustments": TEXT,
        "Import ID": TEXT,
    }),
    DatabaseSpec("goals", "Goals", "🎯", "Outcomes at any horizon, from long-term down to this week.", {
        "Goal": TITLE,
        "Horizon": _select(HORIZONS),
        "Status": _select(GOAL_STATUSES),
        "Area": AREA,
        "Target date": DATE,
        "Notes": TEXT,
        "Source": TEXT,
        "Import ID": TEXT,
    }),
    DatabaseSpec("tasks", "Tasks", "✅", "Everything you intend to do on a given day, and what happened.", {
        "Task": TITLE,
        "Status": _select(TASK_STATUSES),
        "Planned": DATE,
        "Due": DATE,
        "Focus": CHECKBOX,
        "Time": TEXT,
        "Area": AREA,
        "Carried over": CHECKBOX,
        "Notes": TEXT,
        "Source mark": _select(SOURCE_MARKS),
        "Source": TEXT,
        "Import ID": TEXT,
    }),
    DatabaseSpec("notes", "Notes", "📝", "Captures, reflections, learnings and logs.", {
        "Note": TITLE,
        "Type": _select(NOTE_TYPES),
        "Date": DATE,
        "Area": AREA,
        "Source": TEXT,
        "Import ID": TEXT,
    }),
    DatabaseSpec(
        "contribution_calendar",
        "Contribution Calendar",
        "🟩",
        "One page per day. Count of tasks marked Done (prefers Completed on, else Planned). "
        "Used for the GitHub-style activity heatmap.",
        {
            "Day": TITLE,
            "Date": DATE,
            "Completed": {"type": "number", "number": {"format": "number"}},
            "Level": _select([
                ("None", "gray"),
                ("Low", "green"),
                ("Medium", "green"),
                ("High", "green"),
                ("Very High", "green"),
            ]),
            "Notes": TEXT,
            "Import ID": TEXT,
        },
    ),
]
DATABASES_BY_KEY = {d.key: d for d in DATABASES}


@dataclass(frozen=True)
class RelationSpec:
    source: str
    name: str
    target: str
    synced_name: str | None = None   # None = one-way relation


RELATIONS: list[RelationSpec] = [
    RelationSpec("tasks", "Project", "projects", "Tasks"),
    RelationSpec("tasks", "Goal", "goals", "Tasks"),
    RelationSpec("goals", "Project", "projects", "Goals"),
    RelationSpec("goals", "Week", "weeks", "Goals"),
    RelationSpec("goals", "Parent goal", "goals", None),
    RelationSpec("notes", "Project", "projects", "Notes"),
]


@dataclass(frozen=True)
class ComputedSpec:
    db: str
    name: str
    definition: Json
    fallback_name: str | None = None
    fallback_definition: Json | None = None
    manual_if_failed: str = ""


def _rollup(function: str, prop: str = "Completed") -> Json:
    return {"type": "rollup", "rollup": {"function": function, "relation_property_name": "Tasks",
                                         "rollup_property_name": prop}}


COMPUTED: list[ComputedSpec] = [
    ComputedSpec("tasks", "Completed", {"type": "formula", "formula": {"expression": 'prop("Status") == "Done"'}},
                 manual_if_failed='In Tasks add a Formula property "Completed": prop("Status") == "Done"'),
    ComputedSpec("goals", "Task completion", _rollup("percent_checked"), "Linked tasks", _rollup("count", "Task"),
                 manual_if_failed='In Goals add a Rollup "Task completion": Tasks > Completed > Percent checked'),
    ComputedSpec("projects", "Task completion", _rollup("percent_checked"), "Linked tasks", _rollup("count", "Task"),
                 manual_if_failed='In Projects add a Rollup "Task completion": Tasks > Completed > Percent checked'),
]


@dataclass(frozen=True)
class ViewSpec:
    db: str
    name: str
    type: str = "table"
    filter: Json | None = None
    sorts: list[Json] | None = None
    date_property: str | None = None
    visible: list[str] | None = None

    def body(self, prop_ids: dict[str, str]) -> Json:
        """View body without its placement (database_id / create_database)."""
        body: Json = {"name": self.name, "type": self.type}
        if self.filter:
            body["filter"] = self.filter
        if self.sorts:
            body["sorts"] = self.sorts
        if self.type == "calendar":
            body["configuration"] = {"type": "calendar", "date_property_id": prop_ids[self.date_property]}
        elif self.visible:
            body["configuration"] = {"type": self.type, "properties": [
                {"property_id": prop_ids[p], "visible": True} for p in self.visible if p in prop_ids]}
        return body

    def manual_steps(self) -> str:
        parts = [f'in {DATABASES_BY_KEY[self.db].title} add a {self.type} view "{self.name}"']
        if self.filter:
            parts.append(f"filter: {describe_filter(self.filter)}")
        if self.sorts:
            parts.append("sort: " + ", ".join(f'{s["property"]} {s["direction"]}' for s in self.sorts))
        if self.date_property:
            parts.append(f"calendar by {self.date_property}")
        return "; ".join(parts)


def describe_filter(flt: Json) -> str:
    for joiner in ("and", "or"):
        if joiner in flt:
            return f" {joiner.upper()} ".join(describe_filter(f) for f in flt[joiner])
    prop = flt["property"]
    kind = next(k for k in flt if k != "property")
    cond, value = next(iter(flt[kind].items()))
    return f"{prop} {cond.replace('_', ' ')} {value if value not in ({}, True) else ''}".strip()


def _eq(prop: str, kind: str, value: Any) -> Json:
    return {"property": prop, kind: {"equals": value}}


TODAY = {"and": [{"property": "Planned", "date": {"equals": "today"}},
                 {"property": "Status", "select": {"does_not_equal": "Dropped"}}]}
OVERDUE = {"and": [{"property": "Planned", "date": {"before": "today"}}, _eq("Status", "select", "To do")]}
UPCOMING = {"and": [{"property": "Planned", "date": {"after": "today"}},
                    {"property": "Planned", "date": {"on_or_before": "one_week_from_now"}}]}
INBOX = {"and": [{"property": "Planned", "date": {"is_empty": True}}, _eq("Status", "select", "To do")]}
OPEN_WEEKLY_GOALS = {"and": [_eq("Horizon", "select", "Week"),
                             {"or": [_eq("Status", "select", "Active"), _eq("Status", "select", "Needs review")]}]}
ACTIVE_PROJECTS = {"or": [_eq("Status", "select", "Active"), _eq("Status", "select", "Needs review")]}
REFLECTIONS = {"or": [_eq("Type", "select", t) for t in ("Reflection", "Learning", "Log", "Day review")]}

ASC = "ascending"
DESC = "descending"
TASK_COLUMNS = ["Task", "Status", "Planned", "Time", "Focus", "Project", "Notes"]

DATABASE_VIEWS: list[ViewSpec] = [
    ViewSpec("tasks", "Today", filter=TODAY, sorts=[{"property": "Time", "direction": ASC}], visible=TASK_COLUMNS),
    ViewSpec("tasks", "Upcoming", filter=UPCOMING, sorts=[{"property": "Planned", "direction": ASC}], visible=TASK_COLUMNS),
    ViewSpec("tasks", "Overdue", filter=OVERDUE, sorts=[{"property": "Planned", "direction": ASC}], visible=TASK_COLUMNS),
    ViewSpec("tasks", "Inbox (unplanned)", filter=INBOX, visible=TASK_COLUMNS),
    ViewSpec("tasks", "Calendar", type="calendar", date_property="Planned"),
    ViewSpec("tasks", "Carried over", filter=_eq("Carried over", "checkbox", True),
             sorts=[{"property": "Planned", "direction": DESC}], visible=TASK_COLUMNS),
    ViewSpec("tasks", "Slipped (not done)", filter=_eq("Status", "select", "Not done"),
             sorts=[{"property": "Area", "direction": ASC}, {"property": "Planned", "direction": DESC}],
             visible=TASK_COLUMNS),
    ViewSpec("tasks", "Completed", filter=_eq("Status", "select", "Done"),
             sorts=[{"property": "Planned", "direction": DESC}], visible=TASK_COLUMNS),
    ViewSpec("tasks", "Needs review", filter=_eq("Status", "select", "Needs review"),
             sorts=[{"property": "Planned", "direction": DESC}],
             visible=["Task", "Planned", "Source mark", "Notes", "Source"]),
    ViewSpec("goals", "Open weekly goals", filter=OPEN_WEEKLY_GOALS,
             sorts=[{"property": "Target date", "direction": DESC}]),
    ViewSpec("goals", "All goals by horizon",
             sorts=[{"property": "Horizon", "direction": ASC}, {"property": "Target date", "direction": DESC}]),
    ViewSpec("projects", "Active projects", filter=ACTIVE_PROJECTS, sorts=[{"property": "Area", "direction": ASC}]),
    ViewSpec("notes", "Capture inbox", filter=_eq("Type", "select", "Capture"),
             sorts=[{"property": "Date", "direction": DESC}]),
    ViewSpec("notes", "Reflections & learnings", filter=REFLECTIONS, sorts=[{"property": "Date", "direction": DESC}]),
    ViewSpec("weeks", "All weeks", sorts=[{"property": "Dates", "direction": DESC}]),
    ViewSpec("contribution_calendar", "Calendar", type="calendar", date_property="Date"),
    ViewSpec("contribution_calendar", "Table",
             sorts=[{"property": "Date", "direction": DESC}],
             visible=["Day", "Date", "Completed", "Level", "Notes"]),
]


@dataclass(frozen=True)
class DashboardSection:
    heading: str
    hint: str
    view: ViewSpec | None = None
    extra: list[str] = field(default_factory=list)


DASHBOARD_INTRO = (
    "Start here every day.\n"
    "Morning: check Today, tick Focus on the 1-3 tasks that matter most, and decide what to do "
    "with anything Overdue (do it, move its Planned date, or mark it Dropped).\n"
    "Evening: mark each task Done or Not done - don't delete it, that history powers your weekly "
    "review - and put reflections in Capture."
)

DASHBOARD_SECTIONS: list[DashboardSection] = [
    DashboardSection("☀️ Today", "Tasks planned for today. Add new ones with the + New button.",
                     ViewSpec("tasks", "Today", filter=TODAY, sorts=[{"property": "Time", "direction": ASC}],
                              visible=["Task", "Status", "Time", "Focus", "Project"])),
    DashboardSection("⏰ Overdue", "Planned before today and still To do. Do, reschedule or drop each one.",
                     ViewSpec("tasks", "Overdue", filter=OVERDUE, sorts=[{"property": "Planned", "direction": ASC}],
                              visible=["Task", "Planned", "Project", "Notes"])),
    DashboardSection("📅 Next 7 days", "What's coming up.",
                     ViewSpec("tasks", "Next 7 days", filter=UPCOMING,
                              sorts=[{"property": "Planned", "direction": ASC}],
                              visible=["Task", "Planned", "Time", "Project"])),
    DashboardSection("🎯 This week's goals", "Open weekly goals. Set them on Sunday with Horizon = Week.",
                     ViewSpec("goals", "Open weekly goals", filter=OPEN_WEEKLY_GOALS,
                              sorts=[{"property": "Target date", "direction": DESC}],
                              visible=["Goal", "Status", "Project", "Task completion"])),
    DashboardSection("📁 Active projects", "Where your effort is going. Task completion = share of linked tasks Done.",
                     ViewSpec("projects", "Active projects", filter=ACTIVE_PROJECTS,
                              sorts=[{"property": "Area", "direction": ASC}],
                              visible=["Project", "Status", "Area", "Next action", "Task completion"])),
    DashboardSection("📥 Capture", "Quick thoughts to sort later. New note > Type = Capture.",
                     ViewSpec("notes", "Capture", filter=_eq("Type", "select", "Capture"),
                              sorts=[{"property": "Date", "direction": DESC}])),
    DashboardSection("🔁 Weekly review", "Every Sunday:",
                     ViewSpec("weeks", "Weeks", sorts=[{"property": "Dates", "direction": DESC}],
                              visible=["Week", "Dates", "Focus", "Wins", "What slipped & why"]),
                     extra=["Open the Tasks > Slipped (not done) view: what keeps slipping, and why?",
                            "Fill in this week's Wins, What slipped & why, Lessons and Adjustments.",
                            "Mark this week's goals Achieved or Missed; create next week's Week page and goals.",
                            "Plan Monday's tasks."]),
]
