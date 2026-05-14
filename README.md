SID Paper Downloader
====================

Download SID Display Week 2026 Digest PDFs from an authenticated browser session.

Workflow
--------

1. Parse the symposium program into a manifest:

```powershell
uv run sid-paper-downloader parse 2026-Symposium-Program.pdf --out output/manifest.csv
```

2. Save an authenticated browser session:

```powershell
uv run playwright install chromium
uv run sid-paper-downloader login --state output/storage_state.json
```

Log in to the SID/Eventscribe web app in the browser window, then press Enter in the terminal.

3. Download PDFs:

```powershell
uv run sid-paper-downloader download output/manifest.csv --state output/storage_state.json --out downloads
```

If browser storage state does not include the needed SID cookies, pass a raw browser Cookie header instead:

```powershell
uv run sid-paper-downloader download output/manifest.csv --cookie "name=value; other=value" --out downloads
```

4. Verify downloaded files:

```powershell
uv run sid-paper-downloader verify downloads
```

The parser normalizes program IDs such as `1.1` to `1-1` and poster IDs such as `P..1`, `P.1`, or `P1` to `P-1`.
