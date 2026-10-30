"""Browser interaction, diagnostics, tabs, uploads and authenticated downloads."""
from __future__ import annotations
import asyncio
import json
import uuid
from collections import deque
from pathlib import Path
from .. import config
from ..agent.types import ToolFailure, ToolOutcome, ToolSpec
from ..workspace import files, state
from ..workspace.browser import browser, normalize_url, SHOTS_DIR
from .tools import obj, S

READ = {'find', 'console', 'network', 'screenshot', 'zoom', 'list_tabs', 'wait'}
ACTIONS = sorted(READ | {'hover', 'click', 'drag', 'mouse_down', 'mouse_up', 'mouse_move', 'scroll', 'scroll_to',
    'key', 'hold_key', 'form_input', 'upload', 'javascript', 'new_tab', 'switch_tab', 'close_tab', 'back', 'forward', 'reload', 'download'})
SPECS = [ToolSpec('browser_action', 'Extended browser control: pointer, scrolling, keyboard, forms, file upload, tabs, crop/zoom, console/network, JavaScript and authenticated downloads. Use current selectors or aria refs. User takeover is respected.',
    obj({'action': {'type': 'string', 'enum': ACTIONS}, 'selector': S, 'ref': S, 'text': S, 'key': S,
         'x': {'type': 'number'}, 'y': {'type': 'number'}, 'to_x': {'type': 'number'}, 'to_y': {'type': 'number'},
         'dx': {'type': 'number'}, 'dy': {'type': 'number'}, 'width': {'type': 'number'}, 'height': {'type': 'number'},
         'button': {'type': 'string', 'enum': ['left', 'right', 'middle']}, 'count': {'type': 'integer'},
         'seconds': {'type': 'number'}, 'value': {}, 'paths': {'type': 'array', 'items': S}, 'script': S,
         'url': S, 'tab_id': S, 'filename': S}, ['action']),
    asks_like=lambda a: None if a.get('action') in READ else ('run_python' if a.get('action') == 'javascript' else 'browser_click'))]

_tabs: dict[str, dict[str, object]] = {}
_network: dict[int, deque] = {}


def locator(page, a):
    if a.get('ref'):
        return page.locator('aria-ref=' + a['ref'].strip('[]').removeprefix('ref='))
    if a.get('selector'):
        return page.locator(a['selector'])
    if a.get('text'):
        return page.get_by_text(a['text'], exact=False)
    raise ToolFailure('Provide a selector, ref or visible text')


def observe(page):
    key = id(page)
    if key in _network:
        return
    entries = _network[key] = deque(maxlen=200)
    # No headers, cookies or response bodies are captured.
    page.on('response', lambda response: entries.append({'url': response.url, 'status': response.status, 'method': response.request.method}))
    page.on('requestfailed', lambda request: entries.append({'url': request.url, 'error': request.failure, 'method': request.method}))


async def switch(s, page):
    old = s.page
    if old is page:
        return
    watchers = s.watchers
    s.watchers = set()
    await browser._sync_screencast(s)
    s.page, s.watchers = page, watchers
    await browser._sync_screencast(s)
    browser._publish(s)


def attach(s, page):
    tabs = _tabs.setdefault(s.session_id, {})
    if page in tabs.values():
        return
    tabs[uuid.uuid4().hex[:10]] = page
    observe(page)
    page.set_default_timeout(10000)
    page.on('console', lambda msg: browser._on_console(s, msg))
    page.on('pageerror', lambda err: browser._add_console(s, 'error', str(err)))
    page.on('dialog', lambda d: asyncio.ensure_future(browser._on_dialog(s, d)))
    page.on('popup', lambda p: asyncio.ensure_future(browser._fold_popup(s, p)))
    page.on('framenavigated', lambda f: f == page.main_frame and page is s.page and browser._publish(s))
    page.on('close', lambda _: browser._on_page_closed(s, page))


async def adopt_popup(s, page):
    async with s.lock:
        tabs = _tabs.setdefault(s.session_id, {})
        if s.page not in tabs.values():
            tabs[uuid.uuid4().hex[:10]] = s.page
            observe(s.page)
        if len([p for p in tabs.values() if not p.is_closed()]) >= 12:
            await page.close()
            browser._add_console(s, 'warn', 'Popup closed: conversation tab limit reached')
            return
        attach(s, page)
        await switch(s, page)


async def close_session(sid):
    tabs = _tabs.pop(sid, {})
    for page in tabs.values():
        _network.pop(id(page), None)
        if not page.is_closed():
            try:
                await page.close()
            except Exception:
                pass


async def action(a, ctx):
    required = {'javascript': ['script'], 'key': ['key'], 'hold_key': ['key'],
                'switch_tab': ['tab_id'], 'download': ['url'], 'find': ['text']}
    missing = [key for key in required.get(a['action'], []) if key not in a]
    if missing:
        raise ToolFailure('This browser action requires: ' + ', '.join(missing))
    s = await browser.agent_page(ctx.session_id)
    page = s.page
    observe(page)
    tabs = _tabs.setdefault(ctx.session_id, {})
    tabs = {k: p for k, p in tabs.items() if not p.is_closed()}
    _tabs[ctx.session_id] = tabs
    if page not in tabs.values():
        tabs[uuid.uuid4().hex[:10]] = page
    name = a['action']
    value = None
    async with s.lock:
        if name in ('list_tabs', 'new_tab', 'switch_tab', 'close_tab'):
            if name == 'new_tab':
                if len(tabs) >= 12:
                    raise ToolFailure('Close a tab before opening another (limit 12)')
                new_page = await browser._new_page(await browser._ctx())
                attach(s, new_page)
                await new_page.goto(normalize_url(a.get('url', 'about:blank')), wait_until='domcontentloaded')
                await switch(s, new_page)
            elif name in ('switch_tab', 'close_tab'):
                selected = tabs.get(a.get('tab_id'))
                if selected is None:
                    raise ToolFailure('Tab not found in this conversation')
                if name == 'switch_tab':
                    await switch(s, selected)
                else:
                    if len(tabs) == 1:
                        raise ToolFailure('Keep one tab open; use the browser close control to close the browser')
                    if selected is s.page:
                        await switch(s, next(p for p in tabs.values() if p is not selected))
                    tabs.pop(a['tab_id'])
                    await selected.close()
                    _network.pop(id(selected), None)
            value = [{'id': tid, 'url': p.url, 'title': await p.title(), 'active': p is s.page} for tid, p in tabs.items()]
        elif name in ('hover', 'scroll_to', 'form_input', 'upload', 'find'):
            target = locator(page, a)
            if name == 'hover':
                await target.hover()
            elif name == 'scroll_to':
                await target.scroll_into_view_if_needed()
            elif name == 'form_input':
                v = a.get('value')
                if isinstance(v, bool):
                    await target.set_checked(v)
                elif isinstance(v, list):
                    await target.select_option(v)
                else:
                    await target.fill(str(v if v is not None else a.get('text', '')))
            elif name == 'upload':
                root = state.require_root(ctx.session_id)
                paths = [files.resolve(root, p) for p in a.get('paths', [])]
                if not paths or any(not p.is_file() for p in paths):
                    raise ToolFailure('Upload requires existing workspace files')
                await target.set_input_files([str(p) for p in paths])
            else:
                value = [{'text': (await target.nth(i).inner_text())[:4000], 'box': await target.nth(i).bounding_box()} for i in range(min(await target.count(), 20))]
        elif name == 'click':
            options = {'button': a.get('button', 'left'), 'click_count': max(1, min(int(a.get('count', 1)), 3))}
            if a.get('selector') or a.get('ref') or a.get('text'):
                await locator(page, a).click(**options)
            else:
                await page.mouse.click(float(a['x']), float(a['y']), **options)
        elif name == 'drag':
            await page.mouse.move(a['x'], a['y'])
            await page.mouse.down()
            try:
                await page.mouse.move(a['to_x'], a['to_y'], steps=12)
            finally:
                await page.mouse.up()
        elif name == 'mouse_move':
            await page.mouse.move(a['x'], a['y'])
        elif name == 'mouse_down':
            await page.mouse.down(button=a.get('button', 'left'))
        elif name == 'mouse_up':
            await page.mouse.up(button=a.get('button', 'left'))
        elif name == 'scroll':
            await page.mouse.wheel(a.get('dx', 0), a.get('dy', 600))
        elif name == 'key':
            await page.keyboard.press(a['key'])
        elif name == 'hold_key':
            await page.keyboard.down(a['key'])
            try:
                await asyncio.sleep(max(0, min(float(a.get('seconds', 0.5)), 5)))
            finally:
                await page.keyboard.up(a['key'])
        elif name == 'wait':
            await asyncio.sleep(max(0, min(float(a.get('seconds', 1)), 10)))
        elif name == 'javascript':
            value = await page.evaluate(a['script'])
        elif name == 'console':
            value = [v.model_dump() for v in browser.console_tail(ctx.session_id, False, 100)]
        elif name == 'network':
            value = list(_network[id(page)])
        elif name in ('back', 'forward', 'reload'):
            method = {'back': page.go_back, 'forward': page.go_forward, 'reload': page.reload}[name]
            await method(wait_until='domcontentloaded')
        elif name in ('screenshot', 'zoom'):
            folder = SHOTS_DIR / ctx.session_id
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / (uuid.uuid4().hex[:12] + '.png')
            options = {}
            if name == 'zoom':
                options['clip'] = {k: float(a[k]) for k in ('x', 'y', 'width', 'height')}
            await page.screenshot(path=str(path), **options)
            value = {'url': f'/files/workspace/browser/{ctx.session_id}/{path.name}'}
            return ToolOutcome(True, json.dumps(value), images=[path] if ctx.vision else [])
        elif name == 'download':
            folder = config.OUTPUTS_DIR / 'agents' / ctx.session_id / 'downloads'
            folder.mkdir(parents=True, exist_ok=True)
            async with page.expect_download(timeout=30000) as pending:
                await locator(page, a).click()
            downloaded = await pending.value
            filename = Path(a.get('filename') or downloaded.suggested_filename).name
            if filename in ('', '.', '..'):
                raise ToolFailure('Invalid download filename')
            path = folder / (uuid.uuid4().hex[:8] + '-' + filename)
            await downloaded.save_as(str(path))
            value = {'path': str(path), 'url': f'/files/outputs/agents/{ctx.session_id}/downloads/{path.name}'}
        else:
            raise ToolFailure('Unsupported browser action')
    browser._publish(s)
    return ToolOutcome(True, json.dumps({'action': name, 'url': s.page.url, 'result': value}, ensure_ascii=False, default=str)[:32000])


IMPL = {'browser_action': action}


async def shutdown():
    for tabs in list(_tabs.values()):
        for page in list(tabs.values()):
            if not page.is_closed():
                try:
                    await page.close()
                except Exception:
                    pass
    _tabs.clear()
    _network.clear()
