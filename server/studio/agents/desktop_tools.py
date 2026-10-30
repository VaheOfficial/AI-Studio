"""Native Windows desktop input. Calls are opt-in and use normal agent approvals."""
from __future__ import annotations
import asyncio
import ctypes
import json
import sys
import time
import threading
import uuid
from .. import config
from ..agent.types import ToolFailure, ToolOutcome, ToolSpec
from . import store
from .tools import obj, S

ACTIONS = ['screenshot', 'zoom', 'cursor_position', 'left_click', 'right_click', 'middle_click', 'double_click',
           'triple_click', 'left_click_drag', 'mouse_move', 'left_mouse_down', 'left_mouse_up', 'scroll', 'type', 'key', 'hold_key', 'wait']
SPECS = [ToolSpec('computer_action', 'Operate the native desktop: screenshot, crop, cursor, pointer, scrolling, typing and keys. Requires desktop control enabled in Agents settings; Windows implementation.',
    obj({'action': {'type': 'string', 'enum': ACTIONS}, 'x': {'type': 'integer'}, 'y': {'type': 'integer'},
         'to_x': {'type': 'integer'}, 'to_y': {'type': 'integer'}, 'width': {'type': 'integer'}, 'height': {'type': 'integer'},
         'text': S, 'key': S, 'amount': {'type': 'integer'}, 'seconds': {'type': 'number'}}, ['action']),
    asks_like=lambda a: None if a.get('action') in ('screenshot', 'zoom', 'cursor_position', 'wait') else 'computer_action')]


def _perform(a, sid):
    if sys.platform != 'win32':
        raise ToolFailure('Native desktop control is available on Windows')
    if not store.identity(sid).desktop_control:
        raise ToolFailure('Enable desktop control in Agents settings first')
    from ctypes import wintypes
    user = ctypes.WinDLL('user32', use_last_error=True)
    ULONG_PTR = ctypes.c_size_t
    class Mouse(ctypes.Structure):
        _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG), ('mouseData', wintypes.DWORD), ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD), ('dwExtraInfo', ULONG_PTR)]
    class Keyboard(ctypes.Structure):
        _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD), ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD), ('dwExtraInfo', ULONG_PTR)]
    class Hardware(ctypes.Structure):
        _fields_ = [('uMsg', wintypes.DWORD), ('wParamL', wintypes.WORD), ('wParamH', wintypes.WORD)]
    class Data(ctypes.Union):
        _fields_ = [('mi', Mouse), ('ki', Keyboard), ('hi', Hardware)]
    class Input(ctypes.Structure):
        _anonymous_ = ('data',)
        _fields_ = [('type', wintypes.DWORD), ('data', Data)]
    user.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int)
    user.SendInput.restype = wintypes.UINT
    def send(item):
        if user.SendInput(1, ctypes.byref(item), ctypes.sizeof(Input)) != 1:
            raise ToolFailure('Windows refused input; elevated windows may require human interaction')
    def mouse(flags, data=0):
        item = Input(type=0)
        item.mi = Mouse(0, 0, data & 0xffffffff, flags, 0, 0)
        send(item)
    def key(code, up=False, unicode=False):
        item = Input(type=1)
        item.ki = Keyboard(0 if unicode else code, code if unicode else 0, (2 if up else 0) | (4 if unicode else 0), 0, 0)
        send(item)
    def move(x, y):
        if not user.SetCursorPos(int(x), int(y)):
            raise ToolFailure('Could not move cursor')
    name = a['action']
    origin_x, origin_y = user.GetSystemMetrics(76), user.GetSystemMetrics(77)
    if name in ('screenshot', 'zoom'):
        from PIL import ImageGrab
        shot = ImageGrab.grab(all_screens=True)
        if name == 'zoom':
            x, y, w, h = (int(a[k]) for k in ('x', 'y', 'width', 'height'))
            if w <= 0 or h <= 0:
                raise ToolFailure('Crop dimensions must be positive')
            shot = shot.crop((x - origin_x, y - origin_y, x - origin_x + w, y - origin_y + h))
        folder = config.WORKSPACE_DIR / 'desktop' / sid
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (uuid.uuid4().hex[:12] + '.png')
        shot.save(path)
        return {'url': f'/files/workspace/desktop/{sid}/{path.name}', 'width': shot.width, 'height': shot.height, 'origin_x': a.get('x', origin_x) if name == 'zoom' else origin_x, 'origin_y': a.get('y', origin_y) if name == 'zoom' else origin_y, 'coordinates': 'physical desktop pixels'}, path
    if name == 'cursor_position':
        point = wintypes.POINT()
        user.GetCursorPos(ctypes.byref(point))
        return {'x': point.x, 'y': point.y}, None
    if name == 'mouse_move':
        move(a['x'], a['y'])
    elif name in ('left_click', 'right_click', 'middle_click', 'double_click', 'triple_click'):
        if 'x' in a and 'y' in a:
            move(a['x'], a['y'])
        flags = (8, 16) if name == 'right_click' else ((32, 64) if name == 'middle_click' else (2, 4))
        for _ in range(2 if name == 'double_click' else 3 if name == 'triple_click' else 1):
            mouse(flags[0]); mouse(flags[1]); time.sleep(0.07)
    elif name in ('left_mouse_down', 'left_mouse_up'):
        mouse(2 if name.endswith('down') else 4)
    elif name == 'left_click_drag':
        move(a['x'], a['y']); mouse(2)
        try:
            for i in range(1, 13):
                move(a['x'] + (a['to_x'] - a['x']) * i / 12, a['y'] + (a['to_y'] - a['y']) * i / 12)
                time.sleep(0.025)
        finally:
            mouse(4)
    elif name == 'scroll':
        mouse(0x0800, max(-100, min(int(a.get('amount', -3)), 100)) * 120)
    elif name == 'type':
        encoded = a['text'][:16000].encode('utf-16-le')
        for i in range(0, len(encoded), 2):
            code = int.from_bytes(encoded[i:i+2], 'little')
            key(code, unicode=True); key(code, up=True, unicode=True)
    elif name in ('key', 'hold_key'):
        special = {'ctrl': 0x11, 'control': 0x11, 'alt': 0x12, 'shift': 0x10, 'win': 0x5b, 'super': 0x5b,
                   'enter': 0x0d, 'return': 0x0d, 'tab': 9, 'escape': 0x1b, 'esc': 0x1b, 'space': 0x20,
                   'backspace': 8, 'delete': 0x2e, 'home': 0x24, 'end': 0x23, 'pageup': 0x21, 'pagedown': 0x22,
                   'left': 0x25, 'up': 0x26, 'right': 0x27, 'down': 0x28}
        codes = []
        for name_part in a['key'].lower().split('+'):
            code = special.get(name_part)
            if code is None and len(name_part) == 1 and name_part.isascii() and name_part.isalnum():
                code = ord(name_part.upper())
            if code is None and name_part.startswith('f') and name_part[1:].isdigit() and 1 <= int(name_part[1:]) <= 24:
                code = 0x6f + int(name_part[1:])
            if code is None:
                raise ToolFailure('Unsupported key: ' + name_part)
            codes.append(code)
        pressed = []
        try:
            for code in codes:
                key(code); pressed.append(code)
            if a['action'] == 'hold_key':
                time.sleep(max(0, min(float(a.get('seconds', 0.5)), 5)))
        finally:
            for code in reversed(pressed):
                key(code, up=True)
    elif name == 'wait':
        time.sleep(max(0, min(float(a.get('seconds', 1)), 10)))
    else:
        raise ToolFailure('Unsupported native action')
    return {'action': a['action'], 'completed': True}, None


_desktop_lock = threading.RLock()


def _perform_platform(a, sid):
    if sys.platform != 'win32':
        from . import desktop_portable
        return desktop_portable.perform(a,sid)
    user = ctypes.WinDLL('user32', use_last_error=True)
    awareness = getattr(user, 'SetThreadDpiAwarenessContext', None)
    previous = None
    if awareness:
        awareness.argtypes = [ctypes.c_void_p]
        awareness.restype = ctypes.c_void_p
        previous = awareness(ctypes.c_void_p(-4))
    try:
        return _perform(a, sid)
    finally:
        if awareness and previous:
            awareness(previous)


def perform(a,sid):
    with _desktop_lock:
        try:
            return _perform_platform(a,sid)
        except ToolFailure:
            raise
        except Exception as exc:
            raise ToolFailure('Native input failed; check OS permissions and display access: ' + str(exc)[:500]) from exc


async def action(a, ctx):
    value, path = await asyncio.to_thread(perform, a, ctx.session_id)
    return ToolOutcome(True, json.dumps(value), images=[path] if path and ctx.vision else [])


IMPL = {'computer_action': action}
