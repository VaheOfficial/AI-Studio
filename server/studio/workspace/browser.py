"""The agent's browser, one page per chat session, driven with Playwright.

Under the desktop app it is the app's own browser: Electron is Chromium, and the shell keeps windowless
(offscreen) pages for the agent in a session of their own (see ``apps/desktop/src/main.js``, "the agent's browser").
The server reaches them over the DevTools protocol at ``STUDIO_BROWSER_CDP``. They are real browser pages that are
never a window on any system, so there is nothing to hide and nothing a headless browser would give away.

Run without the shell (``pnpm server``), it is the installed Edge (or Chrome / Playwright's Chromium) started
headless on a persistent profile. A headless browser says so in its user agent, and many sites answer that with a
challenge, an empty page or wrong results.

Ported from OpenMuse ``apps/worker/src/browser.ts`` (viewport 1280×800, per-session serial queue, dialogs
dismissed, popups folded into the session page, fixed ``innerText`` read) with their polling screenshot
console replaced by a CDP ``Page.startScreencast`` JPEG stream to watching WebSocket clients and user
takeover forwarded as input events.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import os
import re
import time
import uuid
from collections import deque
from typing import Any

from playwright.async_api import (BrowserContext, CDPSession, ConsoleMessage, Dialog, Error as PlaywrightError, Page,
                                  Playwright, async_playwright)

from .. import config, db, events
from ..events import Subscriber, bus
from ..schemas_workspace import (BrowserInput, BrowserSnapshot, BrowserState, ConsoleEntry, EvBrowserConsole,
                                 EvBrowserFrame, EvBrowserUpdate, KeyInput, MouseInput, TextInput, WheelInput)
from .state import WorkspaceError

WIDTH, HEIGHT = 1280, 800
PROFILE_DIR = config.DATA_DIR / "browser" / "profile"
SHOTS_DIR = config.WORKSPACE_DIR / "browser"
NAV_TIMEOUT_MS = 30_000
# Set by the desktop shell: where its browser answers the DevTools protocol, and the title of the page of the
# agent's session that new pages are opened from
EMBEDDED = os.environ.get("STUDIO_BROWSER_CDP", "")
ANCHOR_TITLE = "grom-agent-browser"
READ_LIMIT = 16_000  # chars of page text / snapshot per read (~5K tokens): pages are long, context is not
_SNAP_NOISE = re.compile(r" \[cursor=pointer\]| \[active\]")
_SNAP_EMPTY = re.compile(r"^\s*- (generic|group|none|presentation|list|listitem)( \[ref=\w+\])?:?$")
_SNAP_REF = re.compile(r" \[ref=\w+\]")
_SNAP_INTERACTIVE = {"link", "button", "textbox", "searchbox", "combobox", "checkbox", "radio", "switch", "slider",
                     "spinbutton", "tab", "menuitem", "menuitemcheckbox", "menuitemradio", "option", "treeitem",
                     "listbox", "gridcell", "row", "article", "dialog", "iframe"}
FRAME_INTERVAL_S = 0.1  # ≤10 fps per watched page
FRAME_BACKLOG = 6  # skip frames for clients this far behind
_CONSOLE_LEVELS = {"log": "log", "info": "info", "warning": "warning", "error": "error", "debug": "debug"}
_MODIFIER_KEYS = {"Shift", "Control", "Alt", "Meta", "CapsLock"}


def normalize_url(value: str) -> str:
    """OpenMuse ``browserAddress``: add https:// when missing; only http(s) and about:blank are allowed."""
    text = value.strip()
    if text == "about:blank":
        return text
    if "://" not in text:
        text = "https://" + text
    scheme = text.split("://", 1)[0].lower()
    if scheme not in ("http", "https") or any(c.isspace() for c in text):
        raise WorkspaceError("Enter a web address like example.com or https://example.com (http/https only)")
    return text


class _Session:
    def __init__(self, session_id: str, page: Page) -> None:
        self.session_id = session_id
        self.page = page
        self.lock = asyncio.Lock()
        self.console: deque[ConsoleEntry] = deque(maxlen=300)
        self.takeover = False
        self.watchers: set[Subscriber] = set()
        self.cdp: CDPSession | None = None
        self.last_frame = 0.0
        self.pending_frame: dict[str, Any] | None = None
        self.frame_timer: asyncio.TimerHandle | None = None


class BrowserManager:
    def __init__(self) -> None:
        self._pw: Playwright | None = None
        self._context: BrowserContext | None = None
        self._start_lock = asyncio.Lock()
        self._sessions: dict[str, _Session] = {}
        self.engine = ""
        self._anchor: Page | None = None  # in the app's browser: the page new pages are opened from

    # ------------------------------ lifecycle ------------------------------

    async def _ctx(self) -> BrowserContext:
        async with self._start_lock:
            if self._context is not None:
                return self._context
            self._pw = await async_playwright().start()
            try:
                ctx = await (self._embedded() if EMBEDDED else self._launched())
            except BaseException:
                await self._pw.stop()
                self._pw = None
                raise
            self._context = ctx
            events.log("info", "browser", f"Agent browser started ({self.engine})")
            return ctx

    async def _embedded(self) -> BrowserContext:
        """The app's own browser. Its pages are the shell's: nothing here is closed that this class did not open."""
        assert self._pw is not None
        try:
            connected = await self._pw.chromium.connect_over_cdp(EMBEDDED)
        except PlaywrightError as exc:
            raise WorkspaceError(f"Could not reach the app's browser: {str(exc).splitlines()[0]}") from exc
        ctx = connected.contexts[0]
        self._anchor = None
        for page in ctx.pages:
            with contextlib.suppress(PlaywrightError):
                if await page.title() == ANCHOR_TITLE:
                    self._anchor = page
        if self._anchor is None:
            await connected.close()
            raise WorkspaceError("The app's browser has no page for the agent; restart the app")
        connected.on("disconnected", lambda _b: self._on_context_closed())
        self.engine = "the app's browser"
        return ctx

    async def _launched(self) -> BrowserContext:
        """An installed browser, headless, on a profile in the data folder."""
        assert self._pw is not None
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        errors = []
        for channel in ("msedge", "chrome", None):
            try:
                ctx = await self._pw.chromium.launch_persistent_context(
                    str(PROFILE_DIR), channel=channel, headless=True, accept_downloads=False,
                    viewport={"width": WIDTH, "height": HEIGHT}, args=["--disable-extensions"])
            except PlaywrightError as exc:
                errors.append(f"{channel or 'chromium'}: {str(exc).splitlines()[0]}")
                continue
            self.engine = f"{channel or 'chromium'}, headless"
            break
        else:
            raise WorkspaceError("No browser could be started (tried Edge, Chrome and Playwright's Chromium). "
                                 "Install Microsoft Edge or run `playwright install chromium` in the server "
                                 "venv. " + "; ".join(errors))
        for stale in ctx.pages:
            await stale.close()
        self._anchor = None
        ctx.on("close", lambda _ctx: self._on_context_closed())
        return ctx

    async def _new_page(self, ctx: BrowserContext) -> Page:
        """A page for one chat. In the app's browser a page cannot be created from outside: the anchor page opens
        it, and the shell makes everything opened in the agent's session another windowless page."""
        if self._anchor is None:
            return await ctx.new_page()
        try:
            async with self._anchor.expect_popup(timeout=10_000) as opened:
                await self._anchor.evaluate("window.open('about:blank')")
            return await opened.value
        except PlaywrightError as exc:
            raise WorkspaceError(f"The app's browser could not open a page: {str(exc).splitlines()[0]}") from exc

    def _on_context_closed(self) -> None:
        self._context = None
        for sid in list(self._sessions):
            self._sessions.pop(sid)
            bus.publish(EvBrowserUpdate(state=self._closed_state(sid)))

    async def shutdown(self) -> None:
        ctx, pw, sessions = self._context, self._pw, list(self._sessions.values())
        self._context, self._pw = None, None
        self._sessions.clear()
        if ctx is not None and self._anchor is not None:
            # The app's browser stays; only the pages opened here go
            for s in sessions:
                with contextlib.suppress(Exception):
                    await s.page.close()
        elif ctx is not None:
            with contextlib.suppress(Exception):
                await ctx.close()
        if pw is not None:
            with contextlib.suppress(Exception):
                await pw.stop()

    async def _session(self, session_id: str) -> _Session:
        s = self._sessions.get(session_id)
        if s is not None and not s.page.is_closed():
            return s
        ctx = await self._ctx()
        page = await self._new_page(ctx)
        page.set_default_timeout(10_000)
        s = _Session(session_id, page)
        self._sessions[session_id] = s
        page.on("console", lambda msg: self._on_console(s, msg))
        page.on("pageerror", lambda err: self._add_console(s, "error", f"Uncaught: {err}"))
        page.on("dialog", lambda d: asyncio.ensure_future(self._on_dialog(s, d)))
        page.on("popup", lambda popup: asyncio.ensure_future(self._fold_popup(s, popup)))
        page.on("framenavigated", lambda frame: frame == page.main_frame and self._publish(s))
        page.on("load", lambda _p: self._publish(s))
        page.on("close", lambda _p: self._on_page_closed(s))
        return s

    def _on_page_closed(self, s: _Session) -> None:
        if self._sessions.get(s.session_id) is s:
            del self._sessions[s.session_id]
            bus.publish(EvBrowserUpdate(state=self._closed_state(s.session_id)))

    async def _fold_popup(self, s: _Session, popup: Page) -> None:
        """A link opening a new window navigates the session's page instead (one page per chat)."""
        with contextlib.suppress(PlaywrightError):
            await popup.wait_for_load_state("commit", timeout=10_000)
            url = popup.url
            await popup.close()
            if url and url != "about:blank":
                async with s.lock:
                    await s.page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)

    async def _on_dialog(self, s: _Session, dialog: Dialog) -> None:
        self._add_console(s, "warning", f"Dismissed {dialog.type} dialog: {dialog.message}")
        with contextlib.suppress(PlaywrightError):
            await dialog.dismiss()

    def _on_console(self, s: _Session, msg: ConsoleMessage) -> None:
        self._add_console(s, _CONSOLE_LEVELS.get(msg.type, "log"), msg.text)

    def _add_console(self, s: _Session, level: str, text: str) -> None:
        entry = ConsoleEntry(level=level, text=text[:2000], ts=db.now_iso())  # type: ignore[arg-type]
        s.console.append(entry)
        for sub in list(s.watchers):
            sub.send(EvBrowserConsole(session_id=s.session_id, entry=entry))

    # ------------------------------ state ------------------------------

    @staticmethod
    def _closed_state(session_id: str) -> BrowserState:
        return BrowserState(session_id=session_id, open=False, url="", title="", takeover=False, width=WIDTH,
                            height=HEIGHT)

    def _state(self, s: _Session, title: str | None = None) -> BrowserState:
        return BrowserState(session_id=s.session_id, open=True, url=s.page.url, title=title or "",
                            takeover=s.takeover, width=WIDTH, height=HEIGHT)

    def _publish(self, s: _Session) -> None:
        async def send() -> None:
            title = ""
            with contextlib.suppress(PlaywrightError):
                title = await s.page.title()
            bus.publish(EvBrowserUpdate(state=self._state(s, title)))

        asyncio.ensure_future(send())

    async def snapshot(self, session_id: str) -> BrowserSnapshot:
        s = self._sessions.get(session_id)
        if s is None or s.page.is_closed():
            return BrowserSnapshot(state=self._closed_state(session_id), console=[])
        title = ""
        with contextlib.suppress(PlaywrightError):
            title = await s.page.title()
        return BrowserSnapshot(state=self._state(s, title), console=list(s.console))

    # ------------------------------ user actions ------------------------------

    async def navigate(self, session_id: str, url: str, *, agent: bool = False) -> BrowserState:
        target = normalize_url(url)
        s = await self._session(session_id)
        if agent:
            self._check_control(s)
        async with s.lock:
            try:
                await s.page.goto(target, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            except PlaywrightError as exc:
                raise WorkspaceError(f"Could not load {target}: {str(exc).splitlines()[0]}") from exc
            await self._settle(s.page)
        return (await self.snapshot(session_id)).state

    async def history(self, session_id: str, action: str) -> BrowserState:
        s = await self._session(session_id)
        async with s.lock:
            with contextlib.suppress(PlaywrightError):
                if action == "back":
                    await s.page.go_back(wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                elif action == "forward":
                    await s.page.go_forward(wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                else:
                    await s.page.reload(wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        return (await self.snapshot(session_id)).state

    async def set_takeover(self, session_id: str, on: bool) -> BrowserState:
        s = await self._session(session_id)
        s.takeover = on
        state = (await self.snapshot(session_id)).state
        bus.publish(EvBrowserUpdate(state=state))
        return state

    async def close(self, session_id: str) -> None:
        s = self._sessions.get(session_id)
        if s is not None:
            with contextlib.suppress(PlaywrightError):
                await s.page.close()

    async def user_input(self, session_id: str, ev: BrowserInput) -> None:
        s = self._sessions.get(session_id)
        if s is None or s.page.is_closed():
            raise WorkspaceError("The browser is not open")
        if not s.takeover:
            raise WorkspaceError("Take control of the browser first")
        mouse, keyboard = s.page.mouse, s.page.keyboard
        async with s.lock:
            try:
                if isinstance(ev, MouseInput):
                    x, y = min(max(ev.x, 0), WIDTH - 1), min(max(ev.y, 0), HEIGHT - 1)
                    await mouse.move(x, y)
                    if ev.action == "down":
                        await mouse.down(button=ev.button or "left", click_count=ev.click_count or 1)
                    elif ev.action == "up":
                        await mouse.up(button=ev.button or "left", click_count=ev.click_count or 1)
                elif isinstance(ev, WheelInput):
                    await mouse.move(ev.x, ev.y)
                    await mouse.wheel(ev.dx, ev.dy)
                elif isinstance(ev, TextInput):
                    await keyboard.insert_text(ev.text)
                elif isinstance(ev, KeyInput) and ev.action == "down" and ev.key not in _MODIFIER_KEYS:
                    await keyboard.press(_combo(ev))
            except PlaywrightError as exc:
                raise WorkspaceError(f"Browser input failed: {str(exc).splitlines()[0]}") from exc

    # ------------------------------ live view ------------------------------

    async def watch(self, session_id: str, sub: Subscriber, watching: bool) -> None:
        if not watching:
            s = self._sessions.get(session_id)
            if s is not None:
                s.watchers.discard(sub)
                await self._sync_screencast(s)
            return
        s = self._sessions.get(session_id)
        if s is None or s.page.is_closed():
            return  # nothing to show yet; the client re-sends watch once the browser opens
        s.watchers.add(sub)
        await self._sync_screencast(s)
        with contextlib.suppress(PlaywrightError):
            shot = await s.page.screenshot(type="jpeg", quality=70)
            sub.send(EvBrowserFrame(session_id=session_id, data=base64.b64encode(shot).decode("ascii"),
                                    width=WIDTH, height=HEIGHT))

    async def release(self, sub: Subscriber) -> None:
        for s in list(self._sessions.values()):
            if sub in s.watchers:
                s.watchers.discard(sub)
                await self._sync_screencast(s)

    async def _sync_screencast(self, s: _Session) -> None:
        try:
            if s.watchers and s.cdp is None:
                assert self._context is not None
                s.cdp = await self._context.new_cdp_session(s.page)
                s.cdp.on("Page.screencastFrame", lambda p: self._on_frame(s, p))
                await s.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 70, "maxWidth": WIDTH,
                                                          "maxHeight": HEIGHT})
            elif not s.watchers and s.cdp is not None:
                cdp, s.cdp = s.cdp, None
                with contextlib.suppress(PlaywrightError):
                    await cdp.send("Page.stopScreencast")
                    await cdp.detach()
        except PlaywrightError as exc:
            events.log("warn", "browser", f"Live view failed: {exc}")
            s.cdp = None

    def _on_frame(self, s: _Session, params: dict[str, Any]) -> None:
        cdp = s.cdp
        if cdp is not None:
            asyncio.ensure_future(_ack(cdp, params["sessionId"]))
        s.pending_frame = params
        wait = FRAME_INTERVAL_S - (time.monotonic() - s.last_frame)
        if wait <= 0:
            self._send_frame(s)
        elif s.frame_timer is None:
            s.frame_timer = asyncio.get_running_loop().call_later(wait, self._send_frame, s)

    def _send_frame(self, s: _Session) -> None:
        s.frame_timer = None
        params, s.pending_frame = s.pending_frame, None
        if params is None:
            return
        s.last_frame = time.monotonic()
        meta = params.get("metadata", {})
        frame = EvBrowserFrame(session_id=s.session_id, data=params["data"],
                               width=int(meta.get("deviceWidth", WIDTH)), height=int(meta.get("deviceHeight", HEIGHT)))
        for sub in list(s.watchers):
            if sub.backlog < FRAME_BACKLOG:
                sub.send(frame)

    # ------------------------------ agent tools ------------------------------

    @staticmethod
    def _check_control(s: _Session) -> None:
        if s.takeover:
            raise WorkspaceError("The user has taken control of the browser. Wait for them to hand it back, or ask "
                                 "them what to do next.")

    async def agent_page(self, session_id: str) -> _Session:
        s = self._sessions.get(session_id)
        if s is None or s.page.is_closed():
            raise WorkspaceError("The browser is not open; call browser_navigate first")
        self._check_control(s)
        return s

    async def click(self, session_id: str, selector: str | None, text: str | None, x: float | None,
                    y: float | None, ref: str | None = None) -> None:
        s = await self.agent_page(session_id)
        async with s.lock:
            try:
                if ref:
                    await s.page.locator(f"aria-ref={ref.strip('[]').removeprefix('ref=')}").click(timeout=10_000)
                elif selector:
                    await s.page.locator(selector).first.click(timeout=10_000)
                elif text:
                    await s.page.get_by_text(text, exact=False).first.click(timeout=10_000)
                elif x is not None and y is not None:
                    await s.page.mouse.click(x, y)
                else:
                    raise WorkspaceError("Give a ref from browser_read's snapshot, a selector, the visible text, or "
                                         "x/y coordinates to click")
            except PlaywrightError as exc:
                raise WorkspaceError(f"Click failed: {str(exc).splitlines()[0]}") from exc
            await self._settle(s.page)

    async def type(self, session_id: str, text: str, selector: str | None, submit: bool,
                   ref: str | None = None) -> None:
        s = await self.agent_page(session_id)
        async with s.lock:
            try:
                if ref:
                    await s.page.locator(f"aria-ref={ref.strip('[]').removeprefix('ref=')}").fill(text,
                                                                                               timeout=10_000)
                elif selector:
                    await s.page.locator(selector).first.fill(text, timeout=10_000)
                else:
                    await s.page.keyboard.insert_text(text)
                if submit:
                    await s.page.keyboard.press("Enter")
            except PlaywrightError as exc:
                raise WorkspaceError(f"Typing failed: {str(exc).splitlines()[0]}") from exc
            await self._settle(s.page)

    async def read(self, session_id: str, mode: str) -> tuple[str, str, str, bool]:
        """(url, title, content, truncated). ``mode``: text (innerText) or snapshot (accessibility tree)."""
        s = await self.agent_page(session_id)
        async with s.lock:
            try:
                if mode == "snapshot":  # with [ref=eN] ids that browser_click/browser_type accept
                    content = _compact_snapshot(await s.page.locator("body").aria_snapshot(timeout=15_000, mode="ai"))
                else:
                    content = await s.page.evaluate("() => document.body ? document.body.innerText : ''")
                title = await s.page.title()
            except PlaywrightError as exc:
                raise WorkspaceError(f"Could not read the page: {str(exc).splitlines()[0]}") from exc
        return s.page.url, title, content[:READ_LIMIT], len(content) > READ_LIMIT

    async def page(self, session_id: str, script: str | None = None) -> tuple[str, str, str, str, Any]:
        """(url, title, html, visible text, value of ``script``) of the chat's page: what a tool needs to work out
        what on the page is worth handing to the model. ``script`` is a JavaScript function evaluated in the page."""
        s = await self.agent_page(session_id)
        async with s.lock:
            try:
                html = await s.page.content()
                text = await s.page.evaluate("() => document.body ? document.body.innerText : ''")
                value = await s.page.evaluate(script) if script else None
                title = await s.page.title()
            except PlaywrightError as exc:
                raise WorkspaceError(f"Could not read the page: {str(exc).splitlines()[0]}") from exc
        return s.page.url, title, html, text, value

    def console_tail(self, session_id: str, errors_only: bool = True, limit: int = 20) -> list[ConsoleEntry]:
        s = self._sessions.get(session_id)
        if s is None:
            return []
        items = [c for c in s.console if not errors_only or c.level in ("error", "warning")]
        return items[-limit:]

    async def screenshot(self, session_id: str) -> str:
        """Save a JPEG of the page; returns its public URL (``/files/workspace/browser/...``)."""
        s = self._sessions.get(session_id)
        if s is None or s.page.is_closed():
            raise WorkspaceError("The browser is not open")
        folder = SHOTS_DIR / session_id
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex[:12]}.jpg"
        try:
            await s.page.screenshot(path=str(folder / name), type="jpeg", quality=70)
        except PlaywrightError as exc:
            raise WorkspaceError(f"Screenshot failed: {str(exc).splitlines()[0]}") from exc
        return f"/files/workspace/browser/{session_id}/{name}"

    async def title(self, session_id: str) -> tuple[str, str]:
        s = self._sessions.get(session_id)
        if s is None or s.page.is_closed():
            return "", ""
        with contextlib.suppress(PlaywrightError):
            return s.page.url, await s.page.title()
        return s.page.url, ""

    @staticmethod
    async def _settle(page: Page) -> None:
        """Give client-side navigation/rendering a moment after an action (bounded)."""
        with contextlib.suppress(PlaywrightError):
            await page.wait_for_load_state("domcontentloaded", timeout=5_000)
        with contextlib.suppress(PlaywrightError):
            await page.wait_for_load_state("networkidle", timeout=2_000)


def _compact_snapshot(snapshot: str) -> str:
    """Shrink the accessibility tree for the model: anonymous wrappers and styling flags go, refs stay only on
    elements that can be clicked or typed into, indentation is halved and long link targets are cut."""
    out = []
    for ln in snapshot.splitlines():
        if _SNAP_EMPTY.match(ln):
            continue
        body = ln.lstrip(" ")
        indent = (len(ln) - len(body)) // 2
        body = _SNAP_NOISE.sub("", body)
        role = body[2:].split(" ", 1)[0].rstrip(":") if body.startswith("- ") else ""
        if role not in _SNAP_INTERACTIVE:
            body = _SNAP_REF.sub("", body)
        if body.startswith("- /url:") and len(body) > 110:
            body = body[:110] + "…"
        if body.strip() not in ("-", "- text:", "- paragraph:", "- img"):
            out.append(" " * indent + body)
    return "\n".join(out)


async def _ack(cdp: CDPSession, frame_session: int) -> None:
    with contextlib.suppress(PlaywrightError):
        await cdp.send("Page.screencastFrameAck", {"sessionId": frame_session})


def _combo(ev: KeyInput) -> str:
    mods = ev.modifiers or 0
    parts = [name for bit, name in ((2, "Control"), (1, "Alt"), (4, "Meta"), (8, "Shift")) if mods & bit]
    key = ev.key
    if len(key) == 1 and "Shift" in parts and not ({"Control", "Alt", "Meta"} & set(parts)):
        parts.remove("Shift")  # the character already carries the shift state
    return "+".join([*parts, "Space" if key == " " else key])


browser = BrowserManager()
