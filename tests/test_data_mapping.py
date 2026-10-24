from personal_hq.data_mapper import Mapper, rich
from personal_hq.importer import plain_value

CFG = {"projects": [{"thread": "ds_course", "name": "Data Science course", "area": "ACAD"},
                    {"thread": "lit_review", "name": "Structured literature review", "area": "RES"},
                    {"thread": "unused", "name": "Unused", "area": "PERS"}]}


def _by_id(records):
    return {r.import_id: r for r in records}


def test_task_status_mapping_never_invents_completion(small_extraction):
    tasks = _by_id(Mapper(small_extraction, CFG).tasks())
    status = {iid: plain_value(r.properties["Status"]) for iid, r in tasks.items()}
    assert status == {"P01-01": "Not done", "P01-02": "Done", "P01-03": "Not done",
                      "P01-04": "Done", "P01-06": "Needs review"}
    assert plain_value(tasks["P01-03"].properties["Carried over"]) is True
    assert plain_value(tasks["P01-06"].properties["Source mark"]) == "filled"


def test_source_and_import_id_are_kept(small_extraction):
    task = _by_id(Mapper(small_extraction, CFG).tasks())["P01-01"]
    assert plain_value(task.properties["Import ID"]) == "P01-01"
    assert plain_value(task.properties["Source"]) == "P01-01 · P01.jpeg"
    assert "woke at 06:17" in plain_value(task.properties["Notes"])
    assert plain_value(task.properties["Time"]) == "05:00"


def test_subtasks_fold_into_parent_notes_and_uncertainty_is_visible(small_extraction):
    tasks = _by_id(Mapper(small_extraction, CFG).tasks())
    assert "P01-05" not in tasks
    assert "Sub-points: title" in plain_value(tasks["P01-04"].properties["Notes"])
    assert "Uncertain reading: name unclear" in plain_value(tasks["P01-06"].properties["Notes"])


def test_project_relations_only_for_mapped_threads(small_extraction):
    tasks = _by_id(Mapper(small_extraction, CFG).tasks())
    assert tasks["P01-02"].relations == {"Project": [("projects", "PRJ-ds_course")]}
    assert tasks["P01-03"].relations == {}   # 'zindi' is not in this mapping


def test_projects_only_for_threads_in_use(small_extraction):
    names = [r.title for r in Mapper(small_extraction, CFG).project_records()]
    assert names == ["Data Science course", "Structured literature review"]


def test_weekly_goals_link_week_parent_and_project(small_extraction):
    goals = _by_id(Mapper(small_extraction, CFG).goals())
    parent, sub = goals["P02-01"], goals["P02-02"]
    assert list(goals) == ["P02-01", "P02-02"]          # parents first
    assert plain_value(parent.properties["Status"]) == "Needs review"
    assert plain_value(sub.properties["Status"]) == "Achieved"
    assert plain_value(parent.properties["Target date"]) == ("2026-10-11", None)
    assert parent.relations["Week"] == [("weeks", "W2026-10-05")]
    assert sub.relations["Parent goal"] == [("goals", "P02-01")]
    assert parent.relations["Project"] == [("projects", "PRJ-lit_review")]


def test_weeks_and_notes(small_extraction):
    m = Mapper(small_extraction, CFG)
    weeks = m.weeks()
    assert [w.import_id for w in weeks] == ["W2026-10-05"]
    assert plain_value(weeks[0].properties["Dates"]) == ("2026-10-05", "2026-10-11")
    notes = _by_id(m.notes())
    assert set(notes) == {"P01-07", "P01-score"}
    assert plain_value(notes["P01-score"].properties["Type"]) == "Day review"
    assert notes["P01-07"].children[0]["paragraph"]["rich_text"][0]["text"]["content"].startswith("Started")


def test_rich_text_is_chunked_to_notion_limits():
    value = rich("x" * 4500)["rich_text"]
    assert [len(p["text"]["content"]) for p in value] == [2000, 2000, 500]


def test_inferred_dates_are_labelled(real_extraction, projects_cfg):
    tasks = _by_id(Mapper(real_extraction, projects_cfg).tasks())
    weekend = tasks["P07-01"]
    assert plain_value(weekend.properties["Planned"]) == ("2026-09-26", None)
    assert "inferred" in plain_value(weekend.properties["Notes"])


def test_full_dataset_counts(real_extraction, projects_cfg):
    records = Mapper(real_extraction, projects_cfg).build()
    counts = {db: len(r) for db, r in records.items()}
    assert counts == {"weeks": 3, "projects": 23, "goals": 37, "tasks": 248, "notes": 27}
    all_ids = [r.import_id for recs in records.values() for r in recs]
    assert len(all_ids) == len(set(all_ids))
