"""Parse SID program PDFs into normalized download records."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
import re

from pypdf import PdfReader


BASE_PDF_URL = "https://sid.org/Portals/5/pdf/SID-Digest/DW2026/docs"

_PAPER_ID_RE = re.compile(r"^(?P<session>\d{1,3})[.-](?P<slot>\d{1,2})$")
_POSTER_ID_RE = re.compile(r"^P\s*(?:[.\-]\s*)*(?P<number>\d{1,3})$", re.IGNORECASE)
_PROGRAM_LINE_RE = re.compile(
    r"^\s*(?P<raw_id>(?:\d{1,3}[.-]\d{1,2})|(?:P\s*(?:[.\-]\s*)*\d{1,3}))\s*:\s*(?P<title>.+?)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ProgramItem:
    """An oral presentation or poster found in the symposium program."""

    paper_id: str
    raw_id: str
    item_type: str
    title: str
    page: int

    @property
    def url(self) -> str:
        """Return the expected SID digest PDF URL."""
        return f"{BASE_PDF_URL}/{self.paper_id}.pdf"


def normalize_paper_id(raw_id: str) -> str:
    """Normalize program IDs to the filename form used by SID PDF URLs."""
    cleaned = raw_id.strip()

    paper_match = _PAPER_ID_RE.fullmatch(cleaned)
    if paper_match is not None:
        return f"{int(paper_match.group('session'))}-{int(paper_match.group('slot'))}"

    poster_match = _POSTER_ID_RE.fullmatch(cleaned)
    if poster_match is not None:
        return f"P-{int(poster_match.group('number'))}"

    raise ValueError(f"Unsupported paper id format: {raw_id!r}")


def infer_item_type(paper_id: str) -> str:
    """Infer item type from a normalized paper ID."""
    return "poster" if paper_id.startswith("P-") else "oral"


def parse_program_pdf(pdf_path: Path) -> list[ProgramItem]:
    """Extract oral and poster entries from a SID symposium program PDF."""
    reader = PdfReader(pdf_path)
    items: list[ProgramItem] = []
    seen_ids: set[str] = set()

    for page_index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        for raw_id, title in _iter_program_lines(text):
            paper_id = normalize_paper_id(raw_id)
            if paper_id in seen_ids:
                continue
            seen_ids.add(paper_id)
            items.append(
                ProgramItem(
                    paper_id=paper_id,
                    raw_id=raw_id.strip(),
                    item_type=infer_item_type(paper_id),
                    title=title.strip(),
                    page=page_index,
                )
            )

    return items


def _iter_program_lines(text: str) -> Iterable[tuple[str, str]]:
    for line in text.splitlines():
        match = _PROGRAM_LINE_RE.match(line)
        if match is None:
            continue
        yield match.group("raw_id"), match.group("title")
