"""Phase 1 checks on the screenshot folder: count, open, de-duplicate."""
from __future__ import annotations

import csv
import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif", ".bmp", ".tif", ".tiff"}


@dataclass
class SourceFile:
    source_file: str
    status: str            # inspected | unreadable | duplicate | unsupported
    sha256: str = ""
    width: int = 0
    height: int = 0
    issue: str = ""


def inspect_folder(folder: Path) -> list[SourceFile]:
    """Open every image in `folder` (not recursive) and report its status."""
    from PIL import Image, UnidentifiedImageError

    results: list[SourceFile] = []
    seen: dict[str, str] = {}
    for path in sorted(p for p in Path(folder).iterdir() if p.is_file()):
        ext = path.suffix.lower()
        if ext not in IMAGE_EXTENSIONS:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in seen:
            results.append(SourceFile(path.name, "duplicate", digest, issue=f"identical to {seen[digest]}"))
            continue
        try:
            with Image.open(path) as im:
                im.verify()
            with Image.open(path) as im:
                width, height = im.size
        except (UnidentifiedImageError, OSError, SyntaxError) as exc:
            status = "unsupported" if ext == ".heic" else "unreadable"
            results.append(SourceFile(path.name, status, digest, issue=str(exc)[:200]))
            continue
        seen[digest] = path.name
        results.append(SourceFile(path.name, "inspected", digest, width, height))
    return results


def summarise(results: list[SourceFile], expected: int) -> dict[str, object]:
    ok = [r for r in results if r.status == "inspected"]
    return {
        "expected": expected,
        "inspected": len(ok),
        "unreadable": [r.source_file for r in results if r.status in ("unreadable", "unsupported")],
        "duplicates": [r.source_file for r in results if r.status == "duplicate"],
        "missing": max(expected - len(ok), 0),
        "extra": max(len(ok) - expected, 0),
        "complete": len(ok) >= expected,
    }


def write_manifest(results: list[SourceFile], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(asdict(results[0]).keys()) if results else ["source_file"])
        writer.writeheader()
        for r in results:
            writer.writerow(asdict(r))
