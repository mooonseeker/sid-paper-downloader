"""Local browser-based download control UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any
import json
import random
import time
from urllib.parse import unquote, urlparse
import webbrowser

import httpx

from sid_paper_downloader.downloader import _validate_response, validate_pdf_file, verify_downloads
from sid_paper_downloader.library_exporter import export_library
from sid_paper_downloader.manifest import ManifestRow, read_manifest, write_manifest


@dataclass
class ControlState:
    """Mutable state shared by the local control server and worker thread."""

    manifest_path: Path
    downloads_dir: Path
    rows: list[ManifestRow]
    lock: Lock = field(default_factory=Lock)
    stop_event: Event = field(default_factory=Event)
    worker: Thread | None = None
    running: bool = False
    current_id: str = ""
    message: str = "Idle"
    selected_total: int = 0
    processed: int = 0
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    last_error: str = ""

    def snapshot(self) -> dict[str, object]:
        """Return a JSON-serializable status snapshot."""
        with self.lock:
            file_count = len(list(self.downloads_dir.rglob("*.pdf"))) if self.downloads_dir.exists() else 0
            return {
                "running": self.running,
                "current_id": self.current_id,
                "message": self.message,
                "selected_total": self.selected_total,
                "processed": self.processed,
                "downloaded": self.downloaded,
                "skipped": self.skipped,
                "failed": self.failed,
                "last_error": self.last_error,
                "file_count": file_count,
            }


def serve_control_ui(
    manifest_path: Path,
    downloads_dir: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = False,
) -> None:
    """Serve the local download control UI."""
    rows = read_manifest(manifest_path)
    _sync_rows_with_downloads(rows, downloads_dir)
    write_manifest(manifest_path, rows)
    state = ControlState(manifest_path=manifest_path, downloads_dir=downloads_dir, rows=rows)
    handler = _make_handler(state)
    server = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{server.server_port}/"
    print(f"SID paper download control UI: {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        state.stop_event.set()
    finally:
        server.server_close()


def _make_handler(state: ControlState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path in {"/", "/index.html"}:
                self._send_text(_control_html(), content_type="text/html; charset=utf-8")
                return
            if self.path == "/api/manifest":
                self._send_json({"items": _library_items(state.rows, state.downloads_dir)})
                return
            if self.path == "/api/status":
                self._send_json(state.snapshot())
                return
            if self._send_download_file():
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/api/start":
                payload = self._read_json()
                self._start_download(payload)
                return
            if self.path == "/api/stop":
                state.stop_event.set()
                with state.lock:
                    state.message = "Stopping after current request..."
                self._send_json(state.snapshot())
                return
            if self.path == "/api/export-library":
                _sync_rows_with_downloads(state.rows, state.downloads_dir)
                write_manifest(state.manifest_path, state.rows)
                target = export_library(state.rows, state.downloads_dir)
                self._send_json({"ok": True, "path": str(target), "status": state.snapshot()})
                return
            if self.path == "/api/verify":
                valid, invalid = verify_downloads(state.downloads_dir)
                _sync_rows_with_downloads(state.rows, state.downloads_dir)
                write_manifest(state.manifest_path, state.rows)
                self._send_json({"valid": len(valid), "invalid": len(invalid), "invalid_paths": [str(path) for path in invalid]})
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _start_download(self, payload: dict[str, Any]) -> None:
            with state.lock:
                if state.running:
                    self._send_json({"ok": False, "error": "A download job is already running"}, status=HTTPStatus.CONFLICT)
                    return

            ids = [str(value) for value in payload.get("ids", [])]
            item_type = payload.get("type")
            status_filter = payload.get("status")
            force = bool(payload.get("force", False))
            delay_min = float(payload.get("delay_min", 0.5))
            delay_max = float(payload.get("delay_max", 1.5))
            rows = _select_rows(state.rows, state.downloads_dir, ids=ids, item_type=item_type, status_filter=status_filter)
            if not rows:
                self._send_json({"ok": False, "error": "No rows matched the requested selection"}, status=HTTPStatus.BAD_REQUEST)
                return

            state.stop_event.clear()
            worker = Thread(
                target=_download_worker,
                args=(state, rows),
                kwargs={"force": force, "delay_min": delay_min, "delay_max": delay_max},
                daemon=True,
            )
            with state.lock:
                state.worker = worker
                state.running = True
                state.current_id = ""
                state.message = "Starting..."
                state.selected_total = len(rows)
                state.processed = 0
                state.downloaded = 0
                state.skipped = 0
                state.failed = 0
                state.last_error = ""
            worker.start()
            self._send_json({"ok": True, "status": state.snapshot()})

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("content-length", "0") or "0")
            if length == 0:
                return {}
            body = self.rfile.read(length).decode("utf-8")
            return json.loads(body)

        def _send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_text(self, payload: str, content_type: str) -> None:
            data = payload.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_download_file(self) -> bool:
            request_path = unquote(urlparse(self.path).path).lstrip("/")
            if not request_path.lower().endswith(".pdf"):
                return False

            base_dir = state.downloads_dir.resolve()
            target = (base_dir / request_path).resolve()
            try:
                target.relative_to(base_dir)
            except ValueError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return True

            if not target.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return True

            data = target.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return True

    return Handler


def _download_worker(
    state: ControlState,
    rows: list[ManifestRow],
    *,
    force: bool,
    delay_min: float,
    delay_max: float,
) -> None:
    headers = {
        "User-Agent": "Mozilla/5.0 sid-paper-downloader-control/0.1",
        "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
    }
    try:
        with httpx.Client(headers=headers, follow_redirects=True, timeout=60.0) as client:
            for row in rows:
                if state.stop_event.is_set():
                    with state.lock:
                        state.message = "Stopped"
                    break
                with state.lock:
                    state.current_id = row.paper_id
                    state.message = f"Downloading {row.paper_id}"
                target = _target_path(state.downloads_dir, row)
                if target.exists() and target.stat().st_size > 0 and not force:
                    pdf_result = validate_pdf_file(target)
                    status = "downloaded" if pdf_result.valid else "corrupt"
                    _mark_row(row, state.downloads_dir, status, "" if pdf_result.valid else pdf_result.error)
                    write_manifest(state.manifest_path, state.rows)
                    with state.lock:
                        state.skipped += 1
                        state.processed += 1
                    continue
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    response = client.get(row.url)
                    _validate_response(response)
                    target.write_bytes(response.content)
                    pdf_result = validate_pdf_file(target)
                    if not pdf_result.valid:
                        _mark_row(row, state.downloads_dir, "corrupt", pdf_result.error)
                        write_manifest(state.manifest_path, state.rows)
                        with state.lock:
                            state.failed += 1
                            state.processed += 1
                            state.last_error = f"{row.paper_id}: {pdf_result.error}"
                        continue
                    _mark_row(row, state.downloads_dir, "downloaded")
                    write_manifest(state.manifest_path, state.rows)
                    with state.lock:
                        state.downloaded += 1
                        state.processed += 1
                        state.last_error = ""
                except httpx.HTTPStatusError as exc:
                    error = f"HTTP {exc.response.status_code}"
                    _mark_row(row, state.downloads_dir, "missing", error)
                    write_manifest(state.manifest_path, state.rows)
                    with state.lock:
                        state.failed += 1
                        state.processed += 1
                        state.last_error = f"{row.paper_id}: {error}"
                except httpx.TransportError as exc:
                    with state.lock:
                        state.failed += 1
                        state.processed += 1
                        state.last_error = f"{row.paper_id}: network error: {exc}"
                except Exception as exc:  # noqa: BLE001
                    _mark_row(row, state.downloads_dir, "missing", str(exc))
                    write_manifest(state.manifest_path, state.rows)
                    with state.lock:
                        state.failed += 1
                        state.processed += 1
                        state.last_error = f"{row.paper_id}: {exc}"
                if delay_max > 0 and not state.stop_event.is_set():
                    time.sleep(random.uniform(delay_min, delay_max))
        with state.lock:
            if not state.stop_event.is_set():
                state.message = "Done"
            state.running = False
            state.current_id = ""
    except Exception as exc:  # noqa: BLE001
        with state.lock:
            state.running = False
            state.current_id = ""
            state.message = "Failed"
            state.last_error = str(exc)


def _select_rows(
    rows: list[ManifestRow],
    downloads_dir: Path,
    *,
    ids: list[str],
    item_type: str | None,
    status_filter: str | None,
) -> list[ManifestRow]:
    requested_ids = {_normalize_search_id(value) for value in ids if value}
    selected: list[ManifestRow] = []
    for row in rows:
        if requested_ids and row.paper_id.upper() not in requested_ids:
            continue
        if item_type in {"oral", "poster"} and row.item_type != item_type:
            continue
        status = _effective_status(row, downloads_dir)
        if status_filter in {"downloaded", "missing", "untried", "corrupt"} and status != status_filter:
            continue
        selected.append(row)
    return selected


def _library_items(rows: list[ManifestRow], downloads_dir: Path) -> list[dict[str, object]]:
    _sync_rows_with_downloads(rows, downloads_dir)
    items: list[dict[str, object]] = []
    for row in rows:
        target = _target_path(downloads_dir, row)
        status = _effective_status(row, downloads_dir)
        downloaded = status == "downloaded"
        items.append(
            {
                "paper_id": row.paper_id,
                "type": row.item_type,
                "title": row.title,
                "page": row.page,
                "url": row.url,
                "local_path": target.relative_to(downloads_dir).as_posix(),
                "status": status,
                "error": row.error,
                "downloaded": downloaded,
                "size_bytes": target.stat().st_size if downloaded else 0,
            }
        )
    return items


def _target_path(downloads_dir: Path, row: ManifestRow) -> Path:
    subdir = "posters" if row.paper_id.startswith("P-") else "papers"
    return downloads_dir / subdir / f"{row.paper_id}.pdf"


def _sync_rows_with_downloads(rows: list[ManifestRow], downloads_dir: Path) -> None:
    for row in rows:
        target = _target_path(downloads_dir, row)
        if target.exists() and target.stat().st_size > 0:
            pdf_result = validate_pdf_file(target)
            status = "downloaded" if pdf_result.valid else "corrupt"
            _mark_row(row, downloads_dir, status, "" if pdf_result.valid else pdf_result.error)
        elif row.status not in {"missing", "corrupt"}:
            _mark_row(row, downloads_dir, "untried")


def _mark_row(row: ManifestRow, downloads_dir: Path, status: str, error: str = "") -> None:
    row.status = status
    row.path = str(_target_path(downloads_dir, row).relative_to(downloads_dir))
    row.error = error


def _effective_status(row: ManifestRow, downloads_dir: Path) -> str:
    target = _target_path(downloads_dir, row)
    if target.exists() and target.stat().st_size > 0:
        return "downloaded" if validate_pdf_file(target).valid else "corrupt"
    if row.status in {"missing", "corrupt"}:
        return row.status
    return "untried"


def _normalize_search_id(value: str) -> str:
    cleaned = value.strip().upper().replace(".", "-")
    if cleaned.startswith("P") and not cleaned.startswith("P-"):
        cleaned = f"P-{cleaned[1:].lstrip('-')}"
    return cleaned


def _control_html() -> str:
    return r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SID Paper Download Control</title>
  <style>
    :root { --bg:#f7f8fb; --panel:#fff; --line:#d9e0ea; --text:#1f2937; --muted:#667085; --accent:#0f766e; --danger:#b42318; font-family:"Segoe UI",Arial,sans-serif; }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--bg); color:var(--text); font-size:15px; }
    main { width:min(1500px, calc(100% - 32px)); margin:0 auto; padding:22px 0 34px; }
    header { display:flex; justify-content:space-between; align-items:flex-end; gap:16px; margin-bottom:16px; }
    h1 { margin:0 0 5px; font-size:26px; }
    .muted { color:var(--muted); }
    .toolbar, .actions, .stats { display:flex; flex-wrap:wrap; gap:10px; align-items:end; }
    .toolbar { margin-bottom:12px; }
    label { display:grid; gap:5px; min-width:140px; }
    label.search { flex:1 1 320px; }
    label span { color:var(--muted); font-size:12px; font-weight:700; text-transform:uppercase; }
    input, select, button { height:38px; border:1px solid #b9c2d0; border-radius:6px; background:#fff; color:var(--text); font:inherit; }
    input, select { padding:0 10px; }
    button { padding:0 14px; cursor:pointer; font-weight:700; }
    button.primary { background:var(--accent); border-color:var(--accent); color:#fff; }
    button.danger { color:var(--danger); }
    button:disabled { opacity:.55; cursor:not-allowed; }
    .stats { margin:12px 0; }
    .stats div { flex:1 1 130px; background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:10px 12px; }
    .stats strong { display:block; font-size:22px; }
    .stats span { color:var(--muted); font-size:12px; font-weight:700; text-transform:uppercase; }
    .panel { background:var(--panel); border:1px solid var(--line); border-radius:8px; overflow:auto; }
    progress { width:100%; height:18px; }
    .statusLine { display:grid; gap:7px; margin-bottom:12px; }
    table { width:100%; min-width:980px; border-collapse:collapse; }
    th, td { padding:9px 10px; border-bottom:1px solid var(--line); text-align:left; vertical-align:middle; }
    th { position:sticky; top:0; background:#eef2f7; font-size:12px; text-transform:uppercase; z-index:1; }
    tr:hover td { background:#f9fbfd; }
    .id { width:90px; font-weight:700; white-space:nowrap; }
    .type, .page, .state, .choose, .pdf { width:96px; white-space:nowrap; }
    .badge { display:inline-flex; align-items:center; min-height:24px; border-radius:999px; padding:2px 8px; font-size:12px; font-weight:700; }
    .ok { color:#137047; background:#e7f6ef; }
    .missing { color:#9a4b00; background:#fff3df; }
    .corrupt { color:#9f1239; background:#ffe4e6; }
    .untried { color:#475467; background:#eef2f7; }
    .pdfLink { color:#115e59; font-weight:700; text-decoration:none; }
    .pdfLink:hover { text-decoration:underline; }
    .fileSize { color:#98a2b3; font-size:12px; font-weight:400; white-space:nowrap; }
    .paperKind { color:#b42318; font-weight:700; }
    .log { min-height:24px; color:var(--muted); }
    @media (max-width:760px) { main { width:min(100% - 20px, 1500px); } header { flex-direction:column; align-items:stretch; } .stats div { flex-basis:45%; } }
  </style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>SID Paper Download Control</h1>
      <div class="muted">Choose papers manually. Nothing downloads until you click a download button.</div>
    </div>
    <div class="actions">
      <button id="refresh">Refresh</button>
      <button id="exportLibrary">Export main.html</button>
      <button id="verify">Verify PDFs</button>
    </div>
  </header>

  <section class="toolbar">
    <label class="search"><span>Search</span><input id="search" type="search" placeholder="ID or title"></label>
    <label><span>Type</span><select id="type"><option value="all">All</option><option value="oral">Oral</option><option value="poster">Poster</option></select></label>
    <label><span>Status</span><select id="status"><option value="all">All</option><option value="untried">Untried</option><option value="missing">Missing</option><option value="corrupt">Corrupt</option><option value="downloaded">Downloaded</option></select></label>
    <label><span>Sort</span><select id="sort"><option value="program">Program order</option><option value="id">ID</option><option value="title">Title</option><option value="size">File size</option></select></label>
    <label><span>Delay min</span><input id="delayMin" type="number" min="0" step="0.1" value="0.2"></label>
    <label><span>Delay max</span><input id="delayMax" type="number" min="0" step="0.1" value="0.6"></label>
  </section>

  <section class="actions">
    <button class="primary" id="downloadSelected">Download selected</button>
    <button id="downloadFiltered">Download filtered not downloaded</button>
    <button class="danger" id="stop">Stop</button>
    <label><span>Force</span><select id="force"><option value="false">Skip existing</option><option value="true">Redownload</option></select></label>
  </section>

  <section class="stats">
    <div><strong id="visible">0</strong><span>Visible</span></div>
    <div><strong id="selected">0</strong><span>Selected</span></div>
    <div><strong id="downloaded">0</strong><span>Downloaded</span></div>
    <div><strong id="missing">0</strong><span>Missing</span></div>
    <div><strong id="corrupt">0</strong><span>Corrupt</span></div>
    <div><strong id="untried">0</strong><span>Untried</span></div>
    <div><strong id="files">0</strong><span>Files</span></div>
  </section>

  <section class="statusLine">
    <progress id="progress" max="1" value="0"></progress>
    <div id="job" class="log">Idle</div>
  </section>

  <section class="panel">
    <table>
      <thead><tr><th class="choose"><input id="toggleAll" type="checkbox"></th><th>ID</th><th>Type</th><th>Title</th><th>Page</th><th>Status</th><th>PDF</th></tr></thead>
      <tbody id="rows"></tbody>
    </table>
  </section>
</main>
<script>
let items = [];
const chosen = new Set();
const $ = (id) => document.getElementById(id);

function normalizeId(query) {
  const text = query.trim().toUpperCase();
  const poster = text.match(/^P[\s.-]*(\d+)$/);
  if (poster) return `P-${Number(poster[1])}`;
  const oral = text.match(/^(\d+)[.-](\d+)$/);
  if (oral) return `${Number(oral[1])}-${Number(oral[2])}`;
  return "";
}

function formatBytes(value) {
  if (!value) return "";
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(size >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function compareIds(a, b) {
  const parse = (id) => id.startsWith("P-")
    ? [1, Number(id.slice(2))]
    : [0, ...id.split("-").map(Number)];
  const left = parse(a.paper_id);
  const right = parse(b.paper_id);
  for (let i = 0; i < Math.max(left.length, right.length); i += 1) {
    const diff = (left[i] || 0) - (right[i] || 0);
    if (diff) return diff;
  }
  return 0;
}

function filtered() {
  const q = $("search").value.trim().toLowerCase();
  const qid = normalizeId(q);
  const type = $("type").value;
  const status = $("status").value;
  const visible = items.filter((item) => {
    const matchQuery = !q || (qid ? item.paper_id.toUpperCase() === qid : item.paper_id.toLowerCase().includes(q) || item.title.toLowerCase().includes(q));
    const matchType = type === "all" || item.type === type;
    const matchStatus = status === "all" || item.status === status;
    return matchQuery && matchType && matchStatus;
  });
  if ($("sort").value === "id") visible.sort(compareIds);
  if ($("sort").value === "title") visible.sort((a, b) => a.title.localeCompare(b.title));
  if ($("sort").value === "size") visible.sort((a, b) => b.size_bytes - a.size_bytes || compareIds(a, b));
  return visible;
}

function render() {
  const visible = filtered();
  const downloaded = items.filter((item) => item.downloaded).length;
  const missing = items.filter((item) => item.status === "missing").length;
  const corrupt = items.filter((item) => item.status === "corrupt").length;
  const untried = items.filter((item) => item.status === "untried").length;
  $("visible").textContent = visible.length;
  $("selected").textContent = chosen.size;
  $("downloaded").textContent = downloaded;
  $("missing").textContent = missing;
  $("corrupt").textContent = corrupt;
  $("untried").textContent = untried;
  $("rows").innerHTML = visible.map((item) => {
    const checked = chosen.has(item.paper_id) ? "checked" : "";
    const status = item.status === "downloaded"
      ? `<span class="badge ok">Downloaded</span>`
      : item.status === "missing"
        ? `<span class="badge missing">Missing</span>`
        : item.status === "corrupt"
          ? `<span class="badge corrupt">Corrupt</span>`
          : `<span class="badge untried">Untried</span>`;
    const size = item.downloaded ? ` <span class="fileSize">· ${formatBytes(item.size_bytes)}</span>` : "";
    const pdf = item.downloaded
      ? `<a class="pdfLink" href="${escapeHtml(item.local_path)}" target="_blank">Open</a>`
      : `<a class="pdfLink" href="${escapeHtml(item.url)}" target="_blank">Remote</a>`;
    return `<tr>
      <td class="choose"><input type="checkbox" data-id="${escapeHtml(item.paper_id)}" ${checked}></td>
      <td class="id">${escapeHtml(item.paper_id)}</td>
      <td class="type">${escapeHtml(item.type)}</td>
      <td>${formatTitle(item.title)}${size}</td>
      <td class="page">${item.page}</td>
      <td class="state">${status}</td>
      <td class="pdf">${pdf}</td>
    </tr>`;
  }).join("") || `<tr><td colspan="7">No matching papers</td></tr>`;
  document.querySelectorAll("input[data-id]").forEach((box) => {
    box.addEventListener("change", () => {
      if (box.checked) chosen.add(box.dataset.id); else chosen.delete(box.dataset.id);
      $("selected").textContent = chosen.size;
    });
  });
}

function escapeHtml(value) {
  return String(value).replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&#039;");
}

function formatTitle(title) {
  const match = String(title).match(/^(Invited Paper:|Distinguished Paper:|Late-News Paper:|Late-News Poster:|Panel:)\s*(.*)$/);
  if (!match) return escapeHtml(title);
  return `<span class="paperKind">${escapeHtml(match[1])}</span> ${escapeHtml(match[2])}`;
}

async function loadManifest() {
  const response = await fetch("/api/manifest");
  const data = await response.json();
  items = data.items;
  for (const id of [...chosen]) if (!items.some((item) => item.paper_id === id)) chosen.delete(id);
  render();
}

async function refreshStatus() {
  const response = await fetch("/api/status");
  const status = await response.json();
  $("files").textContent = status.file_count;
  $("progress").max = Math.max(status.selected_total || 1, 1);
  $("progress").value = status.processed || 0;
  $("job").textContent = `${status.message} ${status.current_id ? "· " + status.current_id : ""} · ${status.processed}/${status.selected_total} · downloaded ${status.downloaded}, skipped ${status.skipped}, failed ${status.failed}${status.last_error ? " · " + status.last_error : ""}`;
  $("stop").disabled = !status.running;
  $("downloadSelected").disabled = status.running;
  $("downloadFiltered").disabled = status.running;
  if (!status.running) await loadManifest();
}

async function postJson(path, body = {}) {
  const response = await fetch(path, { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok || data.ok === false) throw new Error(data.error || response.statusText);
  return data;
}

async function start(ids, statusMode) {
  const body = {
    ids,
    type: $("type").value,
    status: statusMode,
    force: $("force").value === "true",
    delay_min: Number($("delayMin").value || 0),
    delay_max: Number($("delayMax").value || 0),
  };
  await postJson("/api/start", body);
  await refreshStatus();
}

$("downloadSelected").addEventListener("click", async () => {
  if (!chosen.size) { alert("Select at least one paper first."); return; }
  try { await start([...chosen], "all"); } catch (error) { alert(error.message); }
});
$("downloadFiltered").addEventListener("click", async () => {
  const ids = filtered().filter((item) => item.status !== "downloaded").map((item) => item.paper_id);
  if (!ids.length) { alert("No untried or missing papers in the current filter."); return; }
  try { await start(ids, "all"); } catch (error) { alert(error.message); }
});
$("stop").addEventListener("click", () => postJson("/api/stop").catch((error) => alert(error.message)));
$("refresh").addEventListener("click", () => loadManifest().then(refreshStatus));
$("exportLibrary").addEventListener("click", async () => {
  try { const data = await postJson("/api/export-library"); alert(`Exported ${data.path}`); } catch (error) { alert(error.message); }
});
$("verify").addEventListener("click", async () => {
  try { const data = await postJson("/api/verify"); alert(`Valid PDFs: ${data.valid}\nInvalid PDFs: ${data.invalid}`); } catch (error) { alert(error.message); }
});
$("toggleAll").addEventListener("change", (event) => {
  for (const item of filtered()) {
    if (event.target.checked) chosen.add(item.paper_id); else chosen.delete(item.paper_id);
  }
  render();
});
["search","type","status","sort"].forEach((id) => $(id).addEventListener("input", render));

loadManifest().then(refreshStatus);
setInterval(refreshStatus, 1000);
</script>
</body>
</html>"""
