"""
Sign in to TrainingPeaks with a real Chrome window, so nobody has to dig a cookie out of the
developer tools.

The window uses its own Chrome profile in data/tp_browser, kept between runs. The rider signs
in there as they normally would; the app never sees the password, it only reads the
Production_tpAuth cookie TrainingPeaks sets afterwards. Because the profile remembers the
sign in, refresh() can usually fetch a fresh cookie later with no window at all.

Uses Playwright with the installed Google Chrome (channel "chrome"), so no browser download.
"""
from __future__ import annotations

import os
import shutil
import time

from config import DB_PATH

COOKIE = "Production_tpAuth"
START_URL = "https://app.trainingpeaks.com/"
PROFILE_DIR = os.path.join(os.path.dirname(DB_PATH), "tp_browser")
INSTALL_HINT = ("Signing in needs Playwright. Run `./venv/bin/python -m pip install playwright` "
                "(or `uv pip install playwright`) and restart the app.")


class LoginError(Exception):
    """A readable reason the sign in window didn't produce a cookie."""


def available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    return True


def _cookie(context) -> str | None:
    for c in context.cookies():
        if c.get("name") == COOKIE and c.get("value"):
            return c["value"]
    return None


def _open(p, headless: bool):
    os.makedirs(PROFILE_DIR, exist_ok=True)
    try:
        return p.chromium.launch_persistent_context(PROFILE_DIR, channel="chrome", headless=headless)
    except Exception as e:
        raise LoginError("Couldn't open Google Chrome. Install Chrome, or use the paste a cookie "
                         f"option instead. ({e})") from e


def sign_in(timeout: int = 300, sync_playwright=None) -> str:
    """Open a Chrome window on TrainingPeaks and wait for the rider to sign in. Returns the cookie."""
    if sync_playwright is None:
        if not available():
            raise LoginError(INSTALL_HINT)
        from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        context = _open(p, headless=False)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(START_URL)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if cookie := _cookie(context):
                    return cookie
                if not context.pages:
                    raise LoginError("The sign in window was closed before you signed in.")
                time.sleep(1)
            raise LoginError("Timed out waiting for you to sign in. Try again.")
        finally:
            try:
                context.close()
            except Exception:
                pass


def refresh(sync_playwright=None) -> str | None:
    """A fresh cookie without a window, when TrainingPeaks still remembers this profile's sign in.
    None when it doesn't (or Chrome or Playwright isn't there)."""
    if not os.path.isdir(PROFILE_DIR):
        return None
    if sync_playwright is None:
        if not available():
            return None
        from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            context = _open(p, headless=True)
            try:
                page = context.new_page()
                page.goto(START_URL, timeout=30000)
                page.wait_for_load_state("networkidle", timeout=15000)
                if "/login" in page.url:
                    return None
                return _cookie(context)
            finally:
                context.close()
    except Exception:
        return None


def forget() -> None:
    """Delete the saved Chrome profile, signing the app out of TrainingPeaks."""
    shutil.rmtree(PROFILE_DIR, ignore_errors=True)
