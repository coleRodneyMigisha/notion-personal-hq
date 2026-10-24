from PIL import Image

from personal_hq.sources import inspect_folder, summarise, write_manifest


def _img(path, color):
    Image.new("RGB", (20, 30), color).save(path)


def test_counts_readable_images_and_flags_problems(tmp_path):
    for i in range(3):
        _img(tmp_path / f"page{i}.jpg", (i * 40, 0, 0))
    (tmp_path / "zcopy.jpg").write_bytes((tmp_path / "page0.jpg").read_bytes())  # exact duplicate (sorts last)
    (tmp_path / "broken.png").write_bytes(b"not an image")
    (tmp_path / "notes.txt").write_text("ignored")

    results = inspect_folder(tmp_path)
    status = {r.source_file: r.status for r in results}
    assert status["broken.png"] == "unreadable"
    assert status["zcopy.jpg"] == "duplicate"
    assert "notes.txt" not in status
    assert sum(s == "inspected" for s in status.values()) == 3
    assert next(r for r in results if r.source_file == "page1.jpg").width == 20


def test_summary_reports_missing_against_expected_32(tmp_path):
    for i in range(5):
        _img(tmp_path / f"p{i}.jpg", (0, i * 40, 0))
    summary = summarise(inspect_folder(tmp_path), expected=32)
    assert summary["inspected"] == 5
    assert summary["missing"] == 27
    assert summary["complete"] is False


def test_summary_complete_and_extra(tmp_path):
    for i in range(4):
        _img(tmp_path / f"p{i}.jpg", (0, 0, i * 40))
    summary = summarise(inspect_folder(tmp_path), expected=3)
    assert summary["complete"] is True and summary["extra"] == 1


def test_manifest_written(tmp_path):
    _img(tmp_path / "a.jpg", (1, 2, 3))
    out = tmp_path / "out" / "manifest.csv"
    write_manifest(inspect_folder(tmp_path), out)
    assert "a.jpg" in out.read_text()


def test_committed_manifest_has_33_distinct_inspected_pages():
    import csv
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "data" / "manifests" / "source_manifest.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert len(rows) == 33
    assert {r["status"] for r in rows} == {"inspected"}
    assert len({r["sha256"] for r in rows}) == 33
