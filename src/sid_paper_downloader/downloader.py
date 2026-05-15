"""Download and verify SID paper PDFs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import json
import logging
import random
import time

import httpx
from pypdf import PdfReader

from sid_paper_downloader.auth import add_storage_state_cookies
from sid_paper_downloader.manifest import ManifestRow


logging.getLogger("pypdf").setLevel(logging.ERROR)


@dataclass(frozen=True)
class DownloadSummary:
    """Aggregate result for a download run."""

    total: int
    downloaded: int
    skipped: int
    failed: int


@dataclass(frozen=True)
class PdfValidationResult:
    """Structured result for local PDF integrity checks."""

    valid: bool
    error: str = ""


def download_rows(
    rows: list[ManifestRow],
    output_dir: Path,
    *,
    cookie: str | None = None,
    storage_state: Path | None = None,
    force: bool = False,
    retry_failed: bool = False,
    delay_min: float = 0.5,
    delay_max: float = 1.5,
) -> DownloadSummary:
    """Download PDFs listed in manifest rows."""
    if delay_min < 0 or delay_max < 0:
        raise ValueError("Download delays must be non-negative.")
    if delay_min > delay_max:
        raise ValueError("Minimum delay cannot be greater than maximum delay.")

    headers = {
        "User-Agent": "Mozilla/5.0 sid-paper-downloader/0.1",
        "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
    }
    if cookie:
        headers["Cookie"] = cookie

    downloaded = 0
    skipped = 0
    failed = 0

    with httpx.Client(headers=headers, follow_redirects=True, timeout=60.0) as client:
        if storage_state is not None:
            add_storage_state_cookies(client, storage_state)

        for row in rows:
            if retry_failed and row.status not in {"failed", "unauthorized", "invalid_pdf", "http_error"}:
                skipped += 1
                continue

            target = _target_path(output_dir, row)
            row.path = str(target)
            if target.exists() and target.stat().st_size > 0 and not force:
                pdf_result = validate_pdf_file(target)
                row.status = "skipped" if pdf_result.valid else "corrupt"
                row.error = "" if pdf_result.valid else pdf_result.error
                skipped += 1
                continue

            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                response = client.get(row.url)
                _validate_response(response)
                target.write_bytes(response.content)
                pdf_result = validate_pdf_file(target)
                if not pdf_result.valid:
                    row.status = "corrupt" if is_pdf_file(target) else "invalid_pdf"
                    row.error = pdf_result.error
                    failed += 1
                    continue
                row.status = "downloaded"
                row.error = ""
                downloaded += 1
            except httpx.HTTPStatusError as exc:
                row.status = "unauthorized" if exc.response.status_code in {401, 403} else "http_error"
                row.error = f"HTTP {exc.response.status_code}"
                failed += 1
            except Exception as exc:  # noqa: BLE001
                row.status = "failed"
                row.error = str(exc)
                failed += 1

            time.sleep(random.uniform(delay_min, delay_max))

    return DownloadSummary(total=downloaded + skipped + failed, downloaded=downloaded, skipped=skipped, failed=failed)


def verify_downloads(root: Path) -> tuple[list[Path], list[Path]]:
    """Return valid and invalid PDF files below a download root."""
    valid: list[Path] = []
    invalid: list[Path] = []
    for path in root.rglob("*.pdf"):
        if validate_pdf_file(path).valid:
            valid.append(path)
        else:
            invalid.append(path)
    return valid, invalid


def write_report(path: Path, summary: DownloadSummary, rows: list[ManifestRow]) -> None:
    """Write a JSON report for a download run."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": asdict(summary),
        "failed": [asdict(row) for row in rows if row.status not in {"downloaded", "skipped"}],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def is_pdf_file(path: Path) -> bool:
    """Check whether a file starts with a PDF header."""
    with path.open("rb") as handle:
        return handle.read(5) == b"%PDF-"


def validate_pdf_file(path: Path) -> PdfValidationResult:
    """Check whether a local file is a parseable PDF, not just PDF-looking bytes."""
    if not is_pdf_file(path):
        return PdfValidationResult(valid=False, error="File does not start with %PDF-")
    try:
        reader = PdfReader(path, strict=True)
        page_count = len(reader.pages)
        if page_count == 0:
            return PdfValidationResult(valid=False, error="PDF contains no pages")
        # Force pypdf to resolve at least one page object. Some broken placeholders
        # have a valid header but fail when the cross-reference table is read.
        _ = reader.pages[0]
    except Exception as exc:  # noqa: BLE001
        return PdfValidationResult(valid=False, error=str(exc))
    return PdfValidationResult(valid=True)


def _target_path(output_dir: Path, row: ManifestRow) -> Path:
    subdir = "posters" if row.paper_id.startswith("P-") else "papers"
    return output_dir / subdir / f"{row.paper_id}.pdf"


def _validate_response(response: httpx.Response) -> None:
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()
    if "text/html" in content_type:
        raise RuntimeError("Received HTML instead of a PDF; session may be expired")
    if not response.content.startswith(b"%PDF-"):
        raise RuntimeError(f"Received non-PDF content type: {content_type or 'unknown'}")
