"""Command-line interface for SID paper downloads."""

from __future__ import annotations

from pathlib import Path

import typer

from sid_paper_downloader.auth import SID_APP_URL, save_login_state
from sid_paper_downloader.downloader import download_rows, verify_downloads, write_report
from sid_paper_downloader.manifest import read_manifest, rows_from_program_items, write_manifest
from sid_paper_downloader.program_parser import parse_program_pdf


app = typer.Typer(help="Parse and download SID Display Week 2026 paper PDFs.")


@app.command()
def parse(
    pdf: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    out: Path = typer.Option(Path("output/manifest.csv"), "--out", "-o", help="Manifest CSV path."),
) -> None:
    """Parse the symposium program PDF and write a download manifest."""
    items = parse_program_pdf(pdf)
    rows = rows_from_program_items(items)
    write_manifest(out, rows)
    oral_count = sum(1 for row in rows if row.item_type == "oral")
    poster_count = sum(1 for row in rows if row.item_type == "poster")
    typer.echo(f"Wrote {len(rows)} entries to {out} ({oral_count} oral, {poster_count} posters).")


@app.command()
def login(
    state: Path = typer.Option(Path("output/storage_state.json"), "--state", help="Playwright storage state path."),
    url: str = typer.Option(SID_APP_URL, "--url", help="Initial login URL."),
) -> None:
    """Open Chromium for manual login and save browser session state."""
    save_login_state(state, url)
    typer.echo(f"Saved login state to {state}.")


@app.command()
def download(
    manifest: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    out: Path = typer.Option(Path("downloads"), "--out", "-o", help="Download directory."),
    cookie: str | None = typer.Option(None, "--cookie", help="Raw Cookie header copied from the browser."),
    state: Path | None = typer.Option(None, "--state", help="Playwright storage_state.json path."),
    force: bool = typer.Option(False, "--force", help="Redownload files that already exist."),
    retry_failed: bool = typer.Option(False, "--retry-failed", help="Only retry rows already marked as failed."),
    write_status: bool = typer.Option(True, "--write-status/--no-write-status", help="Update manifest status columns."),
    report: Path = typer.Option(Path("output/download-report.json"), "--report", help="JSON report path."),
) -> None:
    """Download PDFs from a manifest using an authenticated session."""
    rows = read_manifest(manifest)
    summary = download_rows(rows, out, cookie=cookie, storage_state=state, force=force, retry_failed=retry_failed)
    if write_status:
        write_manifest(manifest, rows)
    write_report(report, summary, rows)
    typer.echo(
        f"Done: {summary.downloaded} downloaded, {summary.skipped} skipped, "
        f"{summary.failed} failed, {summary.total} total. Report: {report}"
    )


@app.command()
def verify(
    root: Path = typer.Argument(Path("downloads"), exists=True, file_okay=False, readable=True),
) -> None:
    """Verify downloaded files by checking their PDF header."""
    valid, invalid = verify_downloads(root)
    typer.echo(f"Valid PDFs: {len(valid)}")
    typer.echo(f"Invalid PDFs: {len(invalid)}")
    if invalid:
        for path in invalid:
            typer.echo(f"INVALID {path}")
