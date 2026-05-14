SID Paper Downloader
====================

Download SID Display Week 2026 Digest PDFs from the public digest PDF URLs parsed from the symposium program.

Workflow
--------

1. Parse the symposium program into a manifest:

```powershell
uv run sid-paper-downloader parse 2026-Symposium-Program.pdf --out output/manifest.csv
```

2. Download a small smoke-test set:

```powershell
uv run sid-paper-downloader download output/manifest.csv --out downloads --id 1-1 --id P-183 --force
```

3. Download all PDFs:

```powershell
uv run sid-paper-downloader download output/manifest.csv --out downloads
```

Limit or filter a larger run:

```powershell
uv run sid-paper-downloader download output/manifest.csv --out downloads --type oral --limit 10
uv run sid-paper-downloader download output/manifest.csv --out downloads --type poster --delay-min 1 --delay-max 2
```

4. Verify downloaded files:

```powershell
uv run sid-paper-downloader verify downloads
```

5. Export a shareable paper library:

```powershell
uv run sid-paper-downloader export-library --manifest output/manifest.csv --downloads downloads
```

Share the `downloads` folder. Open `downloads/main.html` to search and open local PDFs.

Optional Authentication
-----------------------

The tested digest PDF URLs currently download without login. If SID later requires authentication, save a browser session:

```powershell
uv run playwright install chromium
uv run sid-paper-downloader login --state output/storage_state.json
```

Log in to the SID/Eventscribe web app in the browser window, then press Enter in the terminal.
If Playwright's Chromium download is slow or unavailable, use an installed browser:

```powershell
uv run sid-paper-downloader login --state output/storage_state.json --executable-path "C:\Program Files\Google\Chrome\Application\chrome.exe"
```

Then pass the saved state to `download`:

```powershell
uv run sid-paper-downloader download output/manifest.csv --state output/storage_state.json --out downloads
```

If browser storage state does not include the needed SID cookies, pass a raw browser Cookie header instead:

```powershell
uv run sid-paper-downloader download output/manifest.csv --cookie "name=value; other=value" --out downloads
```

The parser normalizes program IDs such as `1.1` to `1-1` and poster IDs such as `P..1`, `P.1`, or `P1` to `P-1`.
