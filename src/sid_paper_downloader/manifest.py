"""CSV manifest helpers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
import csv

from sid_paper_downloader.program_parser import ProgramItem


MANIFEST_FIELDS = [
    "paper_id",
    "raw_id",
    "type",
    "title",
    "page",
    "url",
    "status",
    "path",
    "error",
]


@dataclass
class ManifestRow:
    """A manifest row with mutable download status."""

    paper_id: str
    raw_id: str
    item_type: str
    title: str
    page: int
    url: str
    status: str = "pending"
    path: str = ""
    error: str = ""


def rows_from_program_items(items: Iterable[ProgramItem]) -> list[ManifestRow]:
    """Convert parsed program items to manifest rows."""
    return [
        ManifestRow(
            paper_id=item.paper_id,
            raw_id=item.raw_id,
            item_type=item.item_type,
            title=item.title,
            page=item.page,
            url=item.url,
        )
        for item in items
    ]


def read_manifest(path: Path) -> list[ManifestRow]:
    """Read a CSV manifest."""
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows: list[ManifestRow] = []
        for row in reader:
            rows.append(
                ManifestRow(
                    paper_id=row["paper_id"],
                    raw_id=row.get("raw_id", ""),
                    item_type=row.get("type", ""),
                    title=row.get("title", ""),
                    page=int(row.get("page") or 0),
                    url=row["url"],
                    status=row.get("status") or "pending",
                    path=row.get("path") or "",
                    error=row.get("error") or "",
                )
            )
    return rows


def write_manifest(path: Path, rows: Iterable[ManifestRow]) -> None:
    """Write a CSV manifest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "paper_id": row.paper_id,
                    "raw_id": row.raw_id,
                    "type": row.item_type,
                    "title": row.title,
                    "page": row.page,
                    "url": row.url,
                    "status": row.status,
                    "path": row.path,
                    "error": row.error,
                }
            )
