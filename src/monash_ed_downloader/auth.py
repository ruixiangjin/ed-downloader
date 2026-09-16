from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from contextlib import suppress
from time import monotonic

from monash_ed_downloader.errors import LoginRequiredError
from monash_ed_downloader.session import BrowserSession
from monash_ed_downloader.settings import Settings

LOGIN_MARKER_VERSION = 1


def has_confirmed_login(settings: Settings) -> bool:
    try:
        marker = json.loads(settings.login_marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return marker.get("version") == LOGIN_MARKER_VERSION and marker.get("confirmed") is True


def mark_login_confirmed(settings: Settings) -> None:
    settings.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = settings.login_marker.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps({"version": LOGIN_MARKER_VERSION, "confirmed": True}) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    temporary.replace(settings.login_marker)


def clear_login_confirmation(settings: Settings) -> None:
    with suppress(FileNotFoundError):
        settings.login_marker.unlink()


async def interactive_login(
    settings: Settings,
    *,
    timeout_seconds: int = 600,
    prompt: Callable[[str], str] = input,
    notify: Callable[[str], None] = print,
) -> None:
    async with BrowserSession(settings, headless=False) as session:
        await session.open_dashboard()
        if await session.wait_for_logged_in(timeout_ms=3_000):
            mark_login_confirmed(settings)
            notify("The current Ed session is valid.")
            return

        clear_login_confirmation(settings)
        notify("\nComplete the login in the Chrome window that just opened.")
        deadline = monotonic() + timeout_seconds
        while monotonic() < deadline:
            await asyncio.to_thread(
                prompt,
                "When an Ed course page is visible, return here and press Enter: ",
            )
            if session.page.is_closed():
                raise LoginRequiredError("The login window was closed. Run login again.")
            if await session.wait_for_logged_in(timeout_ms=3_000):
                mark_login_confirmed(settings)
                notify("The login session has been saved on this device.")
                return
            notify(
                "\nA successful login was not detected yet. Complete the login in Chrome, "
                "then press Enter again; you do not need to restart the program."
            )
        raise LoginRequiredError("Login timed out. Run login again.")
