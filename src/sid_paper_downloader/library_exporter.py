"""Export a self-contained HTML paper library."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import json

from sid_paper_downloader.manifest import ManifestRow


def export_library(
    rows: list[ManifestRow],
    downloads_dir: Path,
    output_file: Path | None = None,
    session_topics: dict[int, str] | None = None,
) -> Path:
    """Write a standalone HTML library into the downloads directory."""
    downloads_dir.mkdir(parents=True, exist_ok=True)
    target = output_file or downloads_dir / "main.html"
    items = [_row_to_library_item(row, downloads_dir) for row in rows]
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "items": items,
        "session_topics": session_topics or {},
    }
    target.write_text(_render_html(payload), encoding="utf-8")
    return target


def _row_to_library_item(row: ManifestRow, downloads_dir: Path) -> dict[str, object]:
    local_path = _local_pdf_path(row)
    absolute_path = downloads_dir / local_path
    effective_status = _effective_status(row, absolute_path)
    downloaded = effective_status == "downloaded"
    return {
        "paper_id": row.paper_id,
        "raw_id": row.raw_id,
        "type": row.item_type,
        "title": row.title,
        "session": _session_number(row.paper_id),
        "remote_url": row.url,
        "local_path": local_path.as_posix(),
        "status": effective_status,
        "error": row.error,
        "downloaded": downloaded,
        "size_bytes": absolute_path.stat().st_size if downloaded else 0,
    }


def _session_number(paper_id: str) -> int | None:
    if paper_id.startswith("P-"):
        return None
    return int(paper_id.split("-", maxsplit=1)[0])


def _local_pdf_path(row: ManifestRow) -> Path:
    subdir = "posters" if row.paper_id.startswith("P-") else "papers"
    return Path(subdir) / f"{row.paper_id}.pdf"


def _effective_status(row: ManifestRow, absolute_path: Path) -> str:
    if absolute_path.exists() and absolute_path.stat().st_size > 0:
        return "downloaded"
    if row.status == "missing":
        return "missing"
    return "untried"


def _render_html(payload: dict[str, object]) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SID Display Week 2026 Papers</title>
  <style>
{_css()}
  </style>
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div>
        <h1>SID Display Week 2026 Papers</h1>
        <p class="summary">Unofficial navigation entry by @mooonseeker.</p>
      </div>
      <section class="stats" aria-label="Library statistics">
        <div class="statCard statVisible"><strong id="statVisible">0</strong><span>Visible</span></div>
        <div class="statCard statDownloaded"><strong id="statDownloaded">0</strong><span>Downloaded</span></div>
        <div class="statCard statMissing"><strong id="statMissing">0</strong><span>Missing</span></div>
        <div class="statCard statUntried"><strong id="statUntried">0</strong><span>Untried</span></div>
        <div class="statCard statOral"><strong id="statOral">0</strong><span>Oral</span></div>
        <div class="statCard statPoster"><strong id="statPoster">0</strong><span>Poster</span></div>
      </section>
    </header>

    <section class="toolbar" aria-label="Filters">
      <nav id="tagBar" class="tagBar" aria-label="Paper groups"></nav>
      <button id="resetFilters" type="button">Reset</button>
      <label class="search">
        <span>Search</span>
        <input id="searchInput" type="search" autocomplete="off" placeholder="ID or title">
      </label>
      <label>
        <span>Status</span>
        <select id="statusFilter">
          <option value="all">All</option>
          <option value="untried">Untried</option>
          <option value="downloaded">Downloaded</option>
          <option value="missing">Missing</option>
        </select>
      </label>
      <label>
        <span>Sort</span>
        <select id="sortMode">
          <option value="program">Program order</option>
          <option value="id">ID</option>
          <option value="title">Title</option>
          <option value="size">File size</option>
        </select>
      </label>
    </section>

    <section class="tableWrap" aria-label="Papers">
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Title</th>
            <th>Status</th>
            <th>PDF</th>
          </tr>
        </thead>
        <tbody id="paperRows"></tbody>
      </table>
    </section>
  </main>

  <script id="library-data" type="application/json">{data}</script>
  <script>
{_js()}
  </script>
</body>
</html>
"""


def _css() -> str:
    return r"""
:root {
  color-scheme: light;
  --bg: #f7f8fb;
  --panel: #ffffff;
  --text: #1f2937;
  --muted: #667085;
  --line: #d8dee8;
  --line-strong: #b9c2d0;
  --soft: #f3f6f9;
  --accent: #0f766e;
  --accent-dark: #115e59;
  --accent-soft: #dff4ef;
  --ok-bg: #e7f6ef;
  --ok-text: #137047;
  --miss-bg: #fff3df;
  --miss-text: #9a4b00;
  --untried-bg: #eef2f7;
  --untried-text: #475467;
  font-family: "Segoe UI", Arial, sans-serif;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-size: 15px;
}

.shell {
  width: min(1500px, calc(100% - 32px));
  margin: 0 auto;
  padding: 24px 0 32px;
}

.topbar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

h1 {
  margin: 0 0 6px;
  font-size: 28px;
  line-height: 1.15;
  font-weight: 700;
}

.summary {
  margin: 0;
  color: var(--muted);
  line-height: 1.4;
}

.toolbar {
  display: flex;
  align-items: end;
  gap: 10px;
  flex-wrap: wrap;
}

button,
select,
input {
  height: 38px;
  border: 1px solid var(--line-strong);
  background: #fff;
  color: var(--text);
  border-radius: 6px;
  font: inherit;
}

button {
  padding: 0 14px;
  cursor: pointer;
  font-weight: 600;
}

button:hover {
  border-color: var(--accent);
  color: var(--accent-dark);
}

input,
select {
  padding: 0 10px;
}

label {
  display: grid;
  gap: 5px;
  min-width: 150px;
}

label span {
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
}

.search {
  flex: 1 1 320px;
}

.toolbar {
  margin-bottom: 14px;
  align-items: end;
}

.tagBar {
  flex: 1 0 100%;
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 8px;
}

.tagButton {
  height: auto;
  min-height: 46px;
  padding: 9px 8px;
  text-align: center;
  background: var(--panel);
}

.tagButton.primaryGroup {
  border-color: #0f766e;
  background: #f0fdfa;
}

.tagButton.posterGroup {
  border-color: #7c3aed;
  background: #f5f3ff;
}

.tagButton[aria-selected="true"] {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent-dark);
}

.tagButton.posterGroup[aria-selected="true"] {
  border-color: #7c3aed;
  background: #ede9fe;
  color: #5b21b6;
}

.tagButton strong {
  display: block;
}

.tagButton strong {
  font-size: 14px;
  line-height: 1.2;
}

.stats {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 8px;
  flex: 1 1 760px;
  max-width: 900px;
}

.statCard {
  background: var(--panel);
  border: 1px solid var(--line);
  border-left: 5px solid var(--line-strong);
  border-radius: 8px;
  padding: 8px 10px;
}

.statVisible {
  background: #f8fafc;
  border-left-color: #64748b;
}

.statDownloaded {
  background: #f0fdf4;
  border-left-color: #16a34a;
}

.statMissing {
  background: #fff7ed;
  border-left-color: #ea580c;
}

.statUntried {
  background: #f1f5f9;
  border-left-color: #94a3b8;
}

.statOral {
  background: #ecfeff;
  border-left-color: #0891b2;
}

.statPoster {
  background: #f5f3ff;
  border-left-color: #7c3aed;
}

.stats strong {
  display: block;
  font-size: 18px;
  line-height: 1.1;
}

.stats span {
  display: block;
  margin-top: 3px;
  color: var(--muted);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
}

.tableWrap {
  overflow: auto;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
}

table {
  width: 100%;
  min-width: 900px;
  border-collapse: collapse;
}

th,
td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--line);
  text-align: left;
  vertical-align: middle;
}

th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: #eef2f7;
  color: #384252;
  font-size: 12px;
  text-transform: uppercase;
}

tr:hover td {
  background: #f9fbfd;
}

td.id {
  width: 92px;
  font-weight: 700;
  white-space: nowrap;
}

td.status,
td.pdf {
  width: 110px;
  white-space: nowrap;
}

.sessionRow td {
  background: var(--soft);
  border-bottom-color: var(--line-strong);
  padding-top: 12px;
  padding-bottom: 12px;
}

.sessionLabel {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  color: #111827;
  font-size: 14px;
  font-weight: 700;
  line-height: 1.35;
}

.badge {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}

.badge.ok {
  background: var(--ok-bg);
  color: var(--ok-text);
}

.badge.missing {
  background: var(--miss-bg);
  color: var(--miss-text);
}

.badge.untried {
  background: var(--untried-bg);
  color: var(--untried-text);
}

a.pdfLink {
  color: var(--accent-dark);
  font-weight: 700;
  text-decoration: none;
}

a.pdfLink:hover {
  text-decoration: underline;
}

.fileSize {
  color: #98a2b3;
  font-size: 12px;
  font-weight: 400;
  white-space: nowrap;
}

.paperKind {
  color: #b42318;
  font-weight: 700;
}

.empty {
  padding: 26px 12px;
  color: var(--muted);
  text-align: center;
}

@media (max-width: 760px) {
  .shell {
    width: min(100% - 20px, 1500px);
    padding-top: 14px;
  }

  .topbar {
    align-items: stretch;
    flex-direction: column;
  }

  .stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    max-width: none;
  }

  .tagBar {
    grid-template-columns: 1fr;
  }

  h1 {
    font-size: 22px;
  }
}
"""


def _js() -> str:
    return r"""
const library = JSON.parse(document.getElementById("library-data").textContent);
const items = library.items.map((item, index) => ({ ...item, index }));
const sessionTopics = library.session_topics || {};
const tags = [
  { id: "all", label: "All", all: true, featured: true },
  { id: "oral-all", label: "Oral", start: 1, end: 118, featured: true },
  { id: "oral-1", label: "Session 1-30", start: 1, end: 30 },
  { id: "oral-2", label: "Session 31-60", start: 31, end: 60 },
  { id: "oral-3", label: "Session 61-90", start: 61, end: 90 },
  { id: "oral-4", label: "Session 91-118", start: 91, end: 118 },
  { id: "posters", label: "Poster", poster: true, featured: true },
];
let activeTag = "oral-all";

const controls = {
  search: document.getElementById("searchInput"),
  status: document.getElementById("statusFilter"),
  sort: document.getElementById("sortMode"),
  reset: document.getElementById("resetFilters"),
  tagBar: document.getElementById("tagBar"),
};

const nodes = {
  rows: document.getElementById("paperRows"),
  visible: document.getElementById("statVisible"),
  downloaded: document.getElementById("statDownloaded"),
  missing: document.getElementById("statMissing"),
  untried: document.getElementById("statUntried"),
  oral: document.getElementById("statOral"),
  poster: document.getElementById("statPoster"),
};

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

function normalizeQueryId(query) {
  const trimmed = query.trim().toUpperCase();
  const poster = trimmed.match(/^P[\s.-]*(\d+)$/);
  if (poster) return `P-${Number(poster[1])}`;
  const oral = trimmed.match(/^(\d+)[.-](\d+)$/);
  if (oral) return `${Number(oral[1])}-${Number(oral[2])}`;
  return "";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatTitle(title) {
  const match = String(title).match(/^(Invited Paper:|Distinguished Paper:)\s*(.*)$/);
  if (!match) return escapeHtml(title);
  return `<span class="paperKind">${escapeHtml(match[1])}</span> ${escapeHtml(match[2])}`;
}

function itemInTag(item, tag) {
  if (tag.all) return true;
  if (tag.poster) return item.type === "poster";
  return item.type === "oral" && item.session >= tag.start && item.session <= tag.end;
}

function currentTag() {
  return tags.find((tag) => tag.id === activeTag) || tags[0];
}

function sessionTitle(session) {
  return sessionTopics[String(session)] || "Session topic not found in program PDF";
}

function renderTags() {
  controls.tagBar.innerHTML = tags.map((tag) => {
    const selected = tag.id === activeTag ? "true" : "false";
    const className = tag.all || tag.id === "oral-all" ? "tagButton primaryGroup" : tag.poster ? "tagButton posterGroup" : "tagButton";
    return `<button class="${className}" type="button" role="tab" aria-selected="${selected}" data-tag="${tag.id}">
      <strong>${escapeHtml(tag.label)}</strong>
    </button>`;
  }).join("");

  controls.tagBar.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      activeTag = button.dataset.tag;
      render();
    });
  });
}

function filteredItems() {
  const query = controls.search.value.trim().toLowerCase();
  const normalizedId = normalizeQueryId(query);
  const status = controls.status.value;
  const tag = currentTag();

  const filtered = items.filter((item) => {
    const topic = item.session ? sessionTitle(item.session).toLowerCase() : "";
    const matchesQuery = !query || (normalizedId
      ? item.paper_id.toUpperCase() === normalizedId
      : item.paper_id.toLowerCase().includes(query) || item.title.toLowerCase().includes(query) || topic.includes(query));
    const matchesTag = itemInTag(item, tag);
    const matchesStatus = status === "all"
      || item.status === status;
    return matchesTag && matchesQuery && matchesStatus;
  });

  if (controls.sort.value === "id") filtered.sort(compareIds);
  if (controls.sort.value === "title") filtered.sort((a, b) => a.title.localeCompare(b.title));
  if (controls.sort.value === "size") filtered.sort((a, b) => b.size_bytes - a.size_bytes || compareIds(a, b));
  if (controls.sort.value === "program") filtered.sort((a, b) => a.index - b.index);
  return filtered;
}

function renderSessionRows(session, rows) {
  const header = `<tr class="sessionRow"><td colspan="4">
    <div class="sessionLabel">
      <span>Session ${session}</span>
      <span>${escapeHtml(sessionTitle(session))}</span>
    </div>
  </td></tr>`;
  return header + rows.map(renderPaperRow).join("");
}

function renderPaperRow(item) {
  const status = item.status === "downloaded"
    ? `<span class="badge ok">Downloaded</span>`
    : item.status === "missing"
      ? `<span class="badge missing">Missing</span>`
      : `<span class="badge untried">Untried</span>`;
  const pdf = item.downloaded
    ? `<a class="pdfLink" href="${escapeHtml(item.local_path)}" target="_blank">Open</a>`
    : `<a class="pdfLink" href="${escapeHtml(item.remote_url)}" target="_blank">Remote</a>`;
  const size = item.downloaded ? ` <span class="fileSize">· ${formatBytes(item.size_bytes)}</span>` : "";
  return `<tr>
    <td class="id">${escapeHtml(item.paper_id)}</td>
    <td>${formatTitle(item.title)}${size}</td>
    <td class="status">${status}</td>
    <td class="pdf">${pdf}</td>
  </tr>`;
}

function render() {
  renderTags();
  const visible = filteredItems();
  const totalDownloaded = items.filter((item) => item.downloaded).length;
  const totalMissing = items.filter((item) => item.status === "missing").length;
  const totalUntried = items.filter((item) => item.status === "untried").length;
  const totalOral = items.filter((item) => item.type === "oral").length;
  const totalPoster = items.filter((item) => item.type === "poster").length;
  const tag = currentTag();

  nodes.visible.textContent = String(visible.length);
  nodes.downloaded.textContent = String(totalDownloaded);
  nodes.missing.textContent = String(totalMissing);
  nodes.untried.textContent = String(totalUntried);
  nodes.oral.textContent = String(totalOral);
  nodes.poster.textContent = String(totalPoster);

  if (!visible.length) {
    nodes.rows.innerHTML = `<tr><td class="empty" colspan="4">No matching papers</td></tr>`;
    return;
  }

  if (tag.all || tag.id === "oral-all" || tag.poster) {
    nodes.rows.innerHTML = visible.map(renderPaperRow).join("");
    return;
  }

  const bySession = new Map();
  visible.forEach((item) => {
    if (!bySession.has(item.session)) bySession.set(item.session, []);
    bySession.get(item.session).push(item);
  });
  nodes.rows.innerHTML = [...bySession.entries()]
    .sort(([a], [b]) => a - b)
    .map(([session, rows]) => renderSessionRows(session, rows))
    .join("");
}

controls.search.addEventListener("input", () => {
  if (controls.search.value.trim()) activeTag = "all";
  render();
});
controls.status.addEventListener("change", render);
controls.sort.addEventListener("change", render);
controls.reset.addEventListener("click", () => {
  controls.search.value = "";
  controls.status.value = "all";
  controls.sort.value = "program";
  activeTag = "oral-all";
  render();
});

render();
"""
