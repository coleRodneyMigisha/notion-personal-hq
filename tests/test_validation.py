import copy

from personal_hq.validation import validate_extraction


def test_real_extraction_is_valid(real_extraction, projects_cfg):
    errors, warnings = validate_extraction(real_extraction, projects_cfg)
    assert errors == []
    assert any("Expected 32" in w for w in warnings)   # 33 vs 32 stays visible


def test_small_extraction_is_valid(small_extraction):
    errors, _ = validate_extraction(small_extraction)
    assert errors == []


def _errors(x):
    return validate_extraction(x)[0]


def test_duplicate_item_ids(small_extraction):
    x = copy.deepcopy(small_extraction)
    x["items"].append(copy.deepcopy(x["items"][0]))
    assert any("duplicate item_id" in e for e in _errors(x))


def test_empty_box_can_never_be_done(small_extraction):
    x = copy.deepcopy(small_extraction)
    x["items"][2]["proposed_status"] = "done"
    assert any("empty box" in e for e in _errors(x))


def test_invalid_and_missing_dates(small_extraction):
    x = copy.deepcopy(small_extraction)
    x["pages"][0]["date_iso"] = "2026-02-30"
    assert any("invalid date_iso" in e for e in _errors(x))
    x = copy.deepcopy(small_extraction)
    x["pages"][1]["date_confidence"] = "high"     # undated, no week range, not flagged as inferred
    x["pages"][1]["week_range"] = None
    x["items"] = [i for i in x["items"] if i["page_id"] != "P02"]
    assert any("no date" in w for w in validate_extraction(x)[1])
    x["pages"][1]["week_range"] = "2026-10-05..2026-10-11"   # a weekly page needs no single date
    assert not any("no date" in w for w in validate_extraction(x)[1])


def test_source_file_mismatch_and_unknown_page(small_extraction):
    x = copy.deepcopy(small_extraction)
    x["items"][0]["source_file"] = "other.jpeg"
    x["items"][1]["page_id"] = "P99"
    errs = _errors(x)
    assert any("source_file does not match" in e for e in errs)
    assert any("unknown page_id" in e for e in errs)


def test_bad_parent_and_vocabulary(small_extraction):
    x = copy.deepcopy(small_extraction)
    x["items"][4]["parent_item_id"] = "P01-99"
    x["items"][0]["box_mark"] = "smudge"
    x["items"][1]["proposed_area"] = "SPORT"
    errs = _errors(x)
    assert any("parent_item_id" in e for e in errs)
    assert any("box_mark" in e for e in errs)
    assert any("unknown area" in e for e in errs)


def test_count_mismatch_is_an_error(small_extraction):
    x = copy.deepcopy(small_extraction)
    x["inspected_screenshots"] = 3
    assert any("inspected_screenshots" in e for e in _errors(x))


def test_uncertain_without_note_warns(small_extraction):
    x = copy.deepcopy(small_extraction)
    x["items"][5]["uncertainty_note"] = None
    assert any("no note" in w for w in validate_extraction(x)[1])
