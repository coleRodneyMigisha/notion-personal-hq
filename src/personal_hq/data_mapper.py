"""Turns the reviewed extraction (extraction.json) into Notion records.

Decisions applied here (see docs/DESIGN.md, "Interpretation defaults"):
  * a tick or an unidentifiable mark in a box = Done; a cross = Not done
  * an empty box on a past page = Not done; on today's page / this week = To do
  * filled or unreadable boxes = Needs review (never guessed)
  * a leading "-" before the box = Carried over
  * undated pages get the inferred date, and the Notes field says so
Every record keeps its source file, its original mark and a stable Import ID.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .schema import AREAS

Json = dict[str, Any]

TASK_STATUS = {"done": "Done", "likely_done": "Done", "not_done": "Not done", "not_done_on_page": "Not done",
               "open": "To do", "unclear": "Needs review", "dropped": "Dropped"}
GOAL_STATUS = {"done": "Achieved", "likely_done": "Achieved", "not_done": "Missed", "not_done_on_page": "Missed",
               "open": "Active", "unclear": "Needs review", "dropped": "Dropped"}
INFERRED_DATES = {"P07": ("2026-09-26", "Undated 'weekend' page; 26-27 Sep inferred from page order"),
                  "P15": ("2026-10-04", "Undated items above the 05-11 Oct weekly goals; 4/5 Oct inferred")}
IMPORT_ORDER = ["weeks", "projects", "goals", "tasks", "notes"]


@dataclass
class Record:
    db: str
    import_id: str
    title: str
    properties: Json
    relations: dict[str, list[tuple[str, str]]] = field(default_factory=dict)  # prop -> [(db, import_id)]
    children: list[Json] = field(default_factory=list)


# ---------------------------------------------------------------- property helpers
def rich(value: str | None) -> Json:
    value = value or ""
    chunks = [value[i:i + 2000] for i in range(0, len(value), 2000)][:100]
    return {"rich_text": [{"type": "text", "text": {"content": c}} for c in chunks]}


def title(value: str) -> Json:
    return {"title": [{"type": "text", "text": {"content": value[:2000]}}]}


def select(value: str | None) -> Json:
    return {"select": {"name": value} if value else None}


def date_prop(start: str | None, end: str | None = None) -> Json:
    if not start:
        return {"date": None}
    return {"date": {"start": start, **({"end": end} if end else {})}}


def area(code: str | None) -> Json:
    return select(AREAS[code][0] if code in AREAS else None)


def paragraph(content: str) -> Json:
    return {"type": "paragraph", "paragraph": rich(content)}


def short_title(text: str, limit: int = 90) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# ---------------------------------------------------------------- mapping
class Mapper:
    def __init__(self, extraction: Json, projects_cfg: Json):
        self.x = extraction
        self.pages = {p["page_id"]: p for p in extraction["pages"]}
        self.projects = {p["thread"]: p for p in projects_cfg["projects"]}
        self.children_of: dict[str, list[Json]] = {}
        for item in extraction["items"]:
            if item.get("parent_item_id"):
                self.children_of.setdefault(item["parent_item_id"], []).append(item)

    def page_date(self, page_id: str) -> tuple[str | None, str | None]:
        page = self.pages[page_id]
        if page.get("date_iso"):
            return page["date_iso"], None
        return INFERRED_DATES.get(page_id, (None, "Page undated"))

    def project_ref(self, item: Json) -> dict[str, list[tuple[str, str]]]:
        thread = item.get("proposed_thread")
        return {"Project": [("projects", f"PRJ-{thread}")]} if thread in self.projects else {}

    @staticmethod
    def source(item: Json) -> Json:
        return rich(f'{item["item_id"]} · {item["source_file"]}')

    def notes_text(self, item: Json, extra: list[str] | None = None) -> str:
        parts = list(extra or [])
        if item.get("time_noted") and item["section"] != "daily":
            parts.append(f"Time: {item['time_noted']}")
        if item.get("annotation"):
            parts.append(f"Margin note: {item['annotation']}")
        subs = [c["text"] for c in self.children_of.get(item["item_id"], []) if c["section"] == "subtask"]
        if subs:
            parts.append("Sub-points: " + "; ".join(subs))
        if item.get("struck_through"):
            parts.append("Struck through in the notebook")
        if item.get("uncertain"):
            parts.append(f"Uncertain reading: {item.get('uncertainty_note')}")
        return " | ".join(parts)

    # -- each database
    def weeks(self) -> list[Record]:
        out = []
        for page in self.x["pages"]:
            if not page.get("week_range"):
                continue
            start, end = page["week_range"].split("..")
            label = f"Week of {date.fromisoformat(start):%d %b} - {date.fromisoformat(end):%d %b %Y}"
            out.append(Record("weeks", f"W{start}", label, {
                "Week": title(label), "Dates": date_prop(start, end),
                "Import ID": rich(f"W{start}")}))
        return out

    def project_records(self) -> list[Record]:
        used = {i.get("proposed_thread") for i in self.x["items"]}
        out = []
        for thread, cfg in self.projects.items():
            if thread not in used:
                continue
            out.append(Record("projects", f"PRJ-{thread}", cfg["name"], {
                "Project": title(cfg["name"]), "Status": select("Needs review"), "Area": area(cfg.get("area")),
                "Outcome": rich(cfg.get("outcome", "")), "Import ID": rich(f"PRJ-{thread}")}))
        return out

    def goals(self) -> list[Record]:
        out = []
        goal_items = [i for i in self.x["items"] if i["section"] in ("weekly_goal", "weekly_subgoal")]
        goal_items.sort(key=lambda i: i["section"] != "weekly_goal")  # parents before sub-goals
        for item in goal_items:
            page = self.pages[item["page_id"]]
            start, end = page["week_range"].split("..")
            rels = {"Week": [("weeks", f"W{start}")], **self.project_ref(item)}
            if item.get("parent_item_id"):
                rels["Parent goal"] = [("goals", item["parent_item_id"])]
            out.append(Record("goals", item["item_id"], item["text"], {
                "Goal": title(item["text"]), "Horizon": select("Week"),
                "Status": select(GOAL_STATUS[item["proposed_status"]]),
                "Area": area(item.get("proposed_area")), "Target date": date_prop(end),
                "Notes": rich(self.notes_text(item, [f"Box mark: {item['box_mark']}"])),
                "Source": self.source(item), "Import ID": rich(item["item_id"])}, rels))
        return out

    def tasks(self) -> list[Record]:
        out = []
        for item in self.x["items"]:
            if item["section"] != "daily":
                continue
            planned, date_note = self.page_date(item["page_id"])
            extra = [date_note] if date_note else []
            page_note = self.pages[item["page_id"]].get("page_note") or ""
            if "covers" in page_note:
                extra.append(page_note)
            out.append(Record("tasks", item["item_id"], item["text"], {
                "Task": title(item["text"]), "Status": select(TASK_STATUS[item["proposed_status"]]),
                "Planned": date_prop(planned), "Time": rich(item.get("time_noted")),
                "Area": area(item.get("proposed_area")), "Carried over": {"checkbox": bool(item.get("carried_marker"))},
                "Notes": rich(self.notes_text(item, extra)), "Source mark": select(item["box_mark"]),
                "Source": self.source(item), "Import ID": rich(item["item_id"])}, self.project_ref(item)))
        return out

    def notes(self) -> list[Record]:
        out = []
        for item in self.x["items"]:
            if item["section"] != "note":
                continue
            when, date_note = self.page_date(item["page_id"])
            body = [paragraph(item["text"])]
            if item.get("uncertain"):
                body.append(paragraph(f"Uncertain reading: {item['uncertainty_note']}"))
            if date_note:
                body.append(paragraph(date_note))
            out.append(Record("notes", item["item_id"], short_title(item["text"]), {
                "Note": title(short_title(item["text"])), "Type": select("Reflection"), "Date": date_prop(when),
                "Area": area(item.get("proposed_area")), "Source": self.source(item),
                "Import ID": rich(item["item_id"])}, self.project_ref(item), body))
        for page in self.x["pages"]:
            if page.get("day_score"):
                iid = f'{page["page_id"]}-score'
                label = f"Day score {page['date_iso']}: {page['day_score']}"
                out.append(Record("notes", iid, label, {
                    "Note": title(label), "Type": select("Day review"), "Date": date_prop(page["date_iso"]),
                    "Source": rich(f'{page["page_id"]} · {page["source_file"]}'), "Import ID": rich(iid)}))
        return out

    def build(self) -> dict[str, list[Record]]:
        return {"weeks": self.weeks(), "projects": self.project_records(), "goals": self.goals(),
                "tasks": self.tasks(), "notes": self.notes()}
