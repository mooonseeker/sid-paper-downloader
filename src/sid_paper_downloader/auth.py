"""Authentication helpers for browser-saved SID sessions."""

from __future__ import annotations

from pathlib import Path
import json

import httpx


SID_APP_URL = "https://displayweek2026.eventscribe.net/"
WINDOWS_BROWSER_PATHS = [
    Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
    Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
]


def add_storage_state_cookies(client: httpx.Client, storage_state_path: Path) -> None:
    """Load Playwright storage-state cookies into an httpx client."""
    data = json.loads(storage_state_path.read_text(encoding="utf-8"))
    for cookie in data.get("cookies", []):
        name = cookie.get("name")
        value = cookie.get("value")
        domain = cookie.get("domain")
        path = cookie.get("path", "/")
        if not name or value is None:
            continue
        client.cookies.set(name, value, domain=domain, path=path)


def save_login_state(
    storage_state_path: Path,
    start_url: str = SID_APP_URL,
    *,
    browser_channel: str | None = None,
    executable_path: Path | None = None,
) -> None:
    """Open a browser for manual login and save Playwright storage state."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    storage_state_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        try:
            launch_options: dict[str, object] = {"headless": False}
            if browser_channel is not None:
                launch_options["channel"] = browser_channel
            if executable_path is not None:
                launch_options["executable_path"] = str(executable_path)
            browser = playwright.chromium.launch(**launch_options)
        except PlaywrightError:
            if browser_channel is not None or executable_path is not None:
                raise
            browser = _launch_common_windows_browser(playwright)
        context = browser.new_context()
        page = context.new_page()
        page.goto(start_url, wait_until="domcontentloaded")
        input("Log in in the browser window, then press Enter here to save session state...")
        context.storage_state(path=str(storage_state_path))
        browser.close()


def _launch_common_windows_browser(playwright: object) -> object:
    """Launch an installed Windows browser when bundled Chromium is unavailable."""
    from playwright.sync_api import Error as PlaywrightError

    for executable_path in WINDOWS_BROWSER_PATHS:
        if not executable_path.exists():
            continue
        try:
            return playwright.chromium.launch(headless=False, executable_path=str(executable_path))
        except PlaywrightError:
            continue
    raise RuntimeError(
        "Could not launch Playwright Chromium or a common Windows Chrome/Edge install. "
        "Run `uv run playwright install chromium` or pass --executable-path."
    )
