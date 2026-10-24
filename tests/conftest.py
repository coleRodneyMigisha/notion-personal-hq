import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from personal_hq.notion_api import InMemoryNotion  # noqa: E402
from personal_hq.report import Report  # noqa: E402
from personal_hq.state import State  # noqa: E402

PARENT = "401dc3e5-c724-80ea-bce6-dcd3961cdf79"


@pytest.fixture
def real_extraction():
    return json.loads((ROOT / "data" / "extracted" / "extraction.json").read_text(encoding="utf-8"))


@pytest.fixture
def projects_cfg():
    return json.loads((ROOT / "data" / "mapping" / "projects.json").read_text(encoding="utf-8"))


@pytest.fixture
def small_extraction():
    """Two pages: a daily page and a weekly-goals page, covering each kind of item."""
    def item(iid, page, text, section="daily", mark="tick", status="done", **kw):
        return {"item_id": iid, "page_id": page, "source_file": f"{page}.jpeg", "page_date": None,
                "section": section, "parent_item_id": None, "text": text, "box_mark": mark,
                "struck_through": False, "carried_marker": False, "ink": "black", "time_noted": None,
                "annotation": None, "proposed_area": "ACAD", "proposed_thread": None, "uncertain": False,
                "uncertainty_note": None, "proposed_status": status, **kw}
    return {
        "expected_screenshots": 2, "inspected_screenshots": 2,
        "pages": [
            {"page_id": "P01", "source_file": "P01.jpeg", "date_written": "16/09/2026", "date_iso": "2026-09-16",
             "date_confidence": "high", "page_type": "daily", "week_range": None, "day_score": "1/2 done",
             "page_note": ""},
            {"page_id": "P02", "source_file": "P02.jpeg", "date_written": "no date", "date_iso": None,
             "date_confidence": "inferred", "page_type": "weekly", "week_range": "2026-10-05..2026-10-11",
             "day_score": None, "page_note": ""},
        ],
        "items": [
            item("P01-01", "P01", "wake up at 05:00", mark="cross", status="not_done", annotation="woke at 06:17",
                 time_noted="05:00"),
            item("P01-02", "P01", "lab 03 data science", proposed_thread="ds_course"),
            item("P01-03", "P01", "continue zindi", mark="empty", status="not_done_on_page", carried_marker=True,
                 proposed_thread="zindi"),
            item("P01-04", "P01", "assignment", mark="marked", status="likely_done"),
            item("P01-05", "P01", "title", section="subtask", mark="none", status="n/a", parent_item_id="P01-04"),
            item("P01-06", "P01", "Kobel ice cream", mark="filled", status="unclear", uncertain=True,
                 uncertainty_note="name unclear"),
            item("P01-07", "P01", "Started on functions in opencv", section="note", mark="none", status="n/a"),
            item("P02-01", "P02", "Finish structured review", section="weekly_goal", mark="filled", status="unclear",
                 proposed_thread="lit_review"),
            item("P02-02", "P02", "draft 01", section="weekly_subgoal", parent_item_id="P02-01"),
        ],
    }


@pytest.fixture
def notion():
    mem = InMemoryNotion()
    mem.add_page(PARENT, "Personal HQ")
    return mem


@pytest.fixture
def make_state(tmp_path):
    def _make(read_only=False):
        return State.load(tmp_path / "state.json", read_only=read_only)
    return _make


@pytest.fixture
def report():
    return Report("test", dry_run=False)
