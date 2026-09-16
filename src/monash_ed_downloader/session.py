from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic
from urllib.parse import urlparse

from playwright.async_api import BrowserContext, Page, Playwright, Route, async_playwright
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from monash_ed_downloader.errors import BrowserUnavailableError, LoginRequiredError
from monash_ed_downloader.settings import Settings


@dataclass(frozen=True, slots=True)
class SessionStatus:
    authenticated: bool
    current_url: str
    message: str


class BrowserSession:
    def __init__(self, settings: Settings, *, headless: bool) -> None:
        self.settings = settings
        self.headless = headless
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def __aenter__(self) -> BrowserSession:
        await self.start()
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.close()

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Browser session is not running.")
        return self._page

    @property
    def context(self) -> BrowserContext:
        if self._context is None:
            raise RuntimeError("Browser session is not running.")
        return self._context

    async def start(self) -> None:
        self.settings.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.settings.browser_profile.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._playwright = await async_playwright().start()
        try:
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=self.settings.browser_profile,
                channel="chrome",
                headless=self.headless,
                locale="en-AU",
                accept_downloads=False,
                viewport={"width": 1440, "height": 1000} if self.headless else None,
            )
            await self._context.route("**/*", self._route)
        except PlaywrightError as error:
            await self._playwright.stop()
            self._playwright = None
            detail = str(error)
            if "ProcessSingleton" in detail or "SingletonLock" in detail:
                message = (
                    "The ED Downloader Chrome profile is already in use. Close the other "
                    "downloader Chrome window and try again."
                )
            else:
                message = "Google Chrome could not be opened. Check that Chrome is installed."
            raise BrowserUnavailableError(message) from error
        self._page = (
            self._context.pages[0] if self._context.pages else await self._context.new_page()
        )

    async def close(self) -> None:
        context, playwright = self._context, self._playwright
        self._context = None
        self._page = None
        self._playwright = None
        try:
            if context is not None:
                try:
                    await context.storage_state(path=self.settings.storage_state)
                    self.settings.storage_state.chmod(0o600)
                finally:
                    await context.close()
        finally:
            if playwright is not None:
                await playwright.stop()

    async def _route(self, route: Route) -> None:
        request = route.request
        parsed = urlparse(request.url)
        if parsed.hostname and parsed.hostname.endswith("edstem.org"):
            if "/new" in parsed.path or "/edit" in parsed.path:
                await route.abort("blockedbyclient")
                return
            if (
                request.method == "GET"
                and "/api/lessons/" in parsed.path
                and "view=1" in parsed.query
            ):
                await route.continue_(url=request.url.replace("view=1", "view=0"))
                return
        if parsed.hostname and any(
            parsed.hostname == host or parsed.hostname.endswith(f".{host}")
            for host in ("panopto.com", "youtube.com", "youtu.be", "vimeo.com")
        ):
            await route.abort("blockedbyclient")
            return
        if self.headless and request.resource_type in {"image", "media", "font"}:
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    async def open_dashboard(self) -> None:
        try:
            await self.page.goto(
                f"{self.settings.ed_base_url}/{self.settings.region}/dashboard",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
        except PlaywrightError as error:
            raise LoginRequiredError(
                "Ed could not be reached. Check the network and try again."
            ) from error

    async def is_logged_in(self) -> bool:
        try:
            return await self.page.locator('[data-testid="appbar-user"]').is_visible()
        except PlaywrightError:
            return False

    async def wait_for_logged_in(self, *, timeout_ms: int = 4_000) -> bool:
        if await self.is_logged_in():
            return True
        try:
            await self.page.locator('[data-testid="appbar-user"]').wait_for(
                state="visible", timeout=timeout_ms
            )
        except PlaywrightTimeoutError:
            return False
        return await self.is_logged_in()

    async def status(self, *, navigate: bool = True) -> SessionStatus:
        if navigate:
            await self.open_dashboard()
        authenticated = await self.wait_for_logged_in()
        return SessionStatus(
            authenticated,
            self.page.url,
            "Authenticated with Ed."
            if authenticated
            else "The saved Ed session is missing or expired.",
        )

    async def ensure_authenticated(self) -> None:
        if not (await self.status()).authenticated:
            raise LoginRequiredError("Ed login is required. Run `ed-downloader login`.")

    async def wait_for_login(self, *, timeout_seconds: int) -> SessionStatus:
        deadline = monotonic() + timeout_seconds
        while monotonic() < deadline:
            if self.page.is_closed():
                raise LoginRequiredError("The login window was closed before login completed.")
            if await self.is_logged_in():
                return await self.status(navigate=False)
            await asyncio.sleep(0.5)
        raise LoginRequiredError("Login was not completed before the timeout.")
