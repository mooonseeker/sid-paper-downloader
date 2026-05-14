"""Authentication helpers for browser-saved SID sessions."""

from __future__ import annotations

from pathlib import Path
import json

import httpx


SID_APP_URL = "https://displayweek2026.eventscribe.net/"


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


def save_login_state(storage_state_path: Path, start_url: str = SID_APP_URL) -> None:
    """Open a browser for manual login and save Playwright storage state."""
    from playwright.sync_api import sync_playwright

    storage_state_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(start_url, wait_until="domcontentloaded")
        input("Log in in the browser window, then press Enter here to save session state...")
        context.storage_state(path=str(storage_state_path))
        browser.close()
