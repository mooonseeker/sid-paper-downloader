"""Command-line interface for SID paper downloads."""

from __future__ import annotations

from pathlib import Path

import typer

from sid_paper_downloader.auth import SID_APP_URL, save_login_state
from sid_paper_downloader.control_server import serve_control_ui
from sid_paper_downloader.downloader import download_rows, verify_downloads, write_report
from sid_paper_downloader.library_exporter import export_library as export_library_html
from sid_paper_downloader.manifest import ManifestRow, read_manifest, rows_from_program_items, write_manifest
from sid_paper_downloader.program_parser import extract_session_topics, parse_program_pdf


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
    channel: str | None = typer.Option(None, "--channel", help="Installed browser channel, e.g. chrome or msedge."),
    executable_path: Path | None = typer.Option(None, "--executable-path", help="Path to Chrome or Edge executable."),
) -> None:
    """Open Chromium for manual login and save browser session state."""
    save_login_state(state, url, browser_channel=channel, executable_path=executable_path)
    typer.echo(f"Saved login state to {state}.")


@app.command()
def download(
    manifest: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    out: Path = typer.Option(Path("downloads"), "--out", "-o", help="Download directory."),
    cookie: str | None = typer.Option(None, "--cookie", help="Raw Cookie header copied from the browser."),
    state: Path | None = typer.Option(None, "--state", help="Playwright storage_state.json path."),
    force: bool = typer.Option(False, "--force", help="Redownload files that already exist."),
    retry_failed: bool = typer.Option(False, "--retry-failed", help="Only retry rows already marked as failed."),
    item_type: str | None = typer.Option(None, "--type", help="Filter manifest rows by type: oral or poster."),
    paper_id: list[str] | None = typer.Option(None, "--id", help="Download one or more normalized IDs, e.g. 1-1 or P-183."),
    limit: int | None = typer.Option(None, "--limit", min=1, help="Download at most N rows after filtering."),
    delay_min: float = typer.Option(0.5, "--delay-min", min=0.0, help="Minimum delay between requests, in seconds."),
    delay_max: float = typer.Option(1.5, "--delay-max", min=0.0, help="Maximum delay between requests, in seconds."),
    write_status: bool = typer.Option(True, "--write-status/--no-write-status", help="Update manifest status columns."),
    report: Path = typer.Option(Path("output/download-report.json"), "--report", help="JSON report path."),
) -> None:
    """Download PDFs from a manifest, optionally using saved authentication."""
    rows = read_manifest(manifest)
    rows_to_download = _filter_rows(rows, item_type=item_type, paper_ids=paper_id, limit=limit)
    if not rows_to_download:
        typer.echo("No manifest rows matched the requested filters.")
        raise typer.Exit(code=1)
    summary = download_rows(
        rows_to_download,
        out,
        cookie=cookie,
        storage_state=state,
        force=force,
        retry_failed=retry_failed,
        delay_min=delay_min,
        delay_max=delay_max,
    )
    if write_status:
        write_manifest(manifest, rows)
    write_report(report, summary, rows_to_download)
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


@app.command()
def export_library(
    manifest: Path = typer.Option(Path("output/manifest.csv"), "--manifest", help="Manifest CSV path."),
    downloads: Path = typer.Option(Path("downloads"), "--downloads", help="Downloads folder to make shareable."),
    output: Path | None = typer.Option(None, "--output", help="HTML output path. Defaults to downloads/main.html."),
    program: Path | None = typer.Option(
        Path("2026-Symposium-Program.pdf"),
        "--program",
        help="Program PDF used to add oral session topics. Topics are skipped when the file is missing.",
    ),
) -> None:
    """Export a standalone HTML library into the downloads folder."""
    rows = read_manifest(manifest)
    session_topics = extract_session_topics(program) if program is not None and program.exists() else {}
    target = export_library_html(rows, downloads, output_file=output, session_topics=session_topics)
    typer.echo(f"Wrote {target}")


@app.command()
def serve(
    manifest: Path = typer.Option(Path("output/manifest.csv"), "--manifest", help="Manifest CSV path."),
    downloads: Path = typer.Option(Path("downloads"), "--downloads", help="Downloads folder."),
    host: str = typer.Option("127.0.0.1", "--host", help="Server host."),
    port: int = typer.Option(8765, "--port", min=1, max=65535, help="Server port."),
    open_browser: bool = typer.Option(False, "--open", help="Open the control UI in the default browser."),
) -> None:
    """Serve a local browser UI for manually controlled downloads."""
    serve_control_ui(manifest, downloads, host=host, port=port, open_browser=open_browser)


def _filter_rows(
    rows: list[ManifestRow],
    *,
    item_type: str | None,
    paper_ids: list[str] | None,
    limit: int | None,
) -> list[ManifestRow]:
    if item_type is not None and item_type not in {"oral", "poster"}:
        raise typer.BadParameter("--type must be either 'oral' or 'poster'.")

    requested_ids = {value.upper() for value in paper_ids or []}
    filtered = [
        row
        for row in rows
        if (item_type is None or row.item_type == item_type)
        and (not requested_ids or row.paper_id.upper() in requested_ids)
    ]
    return filtered[:limit] if limit is not None else filtered
