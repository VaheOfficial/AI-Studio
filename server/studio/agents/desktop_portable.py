"""Optional macOS/X11 primary-display input; OS access grants remain user-controlled."""
from __future__ import annotations
import time
import uuid
from .. import config, osenv
from ..agent.types import ToolFailure
from . import store


def perform(a,sid):
    available,reason=osenv.desktop_backend()
    if not available: raise ToolFailure(reason)
    if not store.identity(sid).desktop_control: raise ToolFailure('Enable desktop control in Agent settings first')
    import pyautogui as gui
    gui.FAILSAFE=True
    # PyAutoGUI uses logical points on Retina; model coordinates use the screenshot's physical pixels.
    shot=gui.screenshot();width,height=gui.size();sx,sy=shot.width/width,shot.height/height
    def point(x,y):
        if not 0<=x<shot.width or not 0<=y<shot.height: raise ToolFailure('Coordinates must be on the primary display')
        return x/sx,y/sy
    action=a['action']
    if action in ('screenshot','zoom'):
        left,top=0,0
        if action=='zoom':
            left,top=a['x'],a['y'];right,bottom=left+a['width'],top+a['height']
            if left<0 or top<0 or right>shot.width or bottom>shot.height: raise ToolFailure('Crop is outside the primary display')
            shot=shot.crop((left,top,right,bottom))
        directory=config.WORKSPACE_DIR/'desktop'/sid;directory.mkdir(parents=True,exist_ok=True)
        path=directory/(uuid.uuid4().hex[:12]+'.png');shot.save(path)
        return {'url':'/files/'+path.relative_to(config.DATA_DIR).as_posix(),'width':shot.width,'height':shot.height,
                'origin_x':left,'origin_y':top,'coordinates':'physical primary-display pixels','scale_x':sx,'scale_y':sy},path
    if action=='cursor_position':
        x,y=gui.position();return {'x':round(x*sx),'y':round(y*sy)},None
    if action=='wait': time.sleep(max(0,min(a.get('seconds',1),10)))
    elif action=='mouse_move': gui.moveTo(*point(a['x'],a['y']))
    elif action in ('left_click','right_click','middle_click','double_click','triple_click'):
        location=point(a['x'],a['y']) if 'x' in a and 'y' in a else gui.position()
        gui.click(*location,clicks=2 if action=='double_click' else 3 if action=='triple_click' else 1,
                  interval=0.1,button='right' if action=='right_click' else 'middle' if action=='middle_click' else 'left')
    elif action=='left_mouse_down': gui.mouseDown()
    elif action=='left_mouse_up': gui.mouseUp()
    elif action=='left_click_drag':
        gui.moveTo(*point(a['x'],a['y']));gui.dragTo(*point(a['to_x'],a['to_y']),duration=0.4,button='left')
    elif action=='scroll': gui.scroll(max(-100,min(a.get('amount',-3),100)))
    elif action=='type':
        text=a['text']
        if len(text)>16000: raise ToolFailure('Desktop text exceeds 16,000 characters')
        if not text.isascii(): raise ToolFailure('This backend cannot type Unicode reliably; use a structured application tool or browser form input')
        gui.write(text,interval=0.001)
    elif action in ('key','hold_key'):
        aliases={'ctrl':'ctrl','control':'ctrl','cmd':'command','meta':'command','enter':'enter','return':'enter','esc':'esc','escape':'esc','shift':'shift','alt':'alt','super':'win'}
        keys=[aliases.get(part.lower(),part.lower()) for part in a['key'].split('+')]
        if not keys or any(key not in gui.KEYBOARD_KEYS for key in keys): raise ToolFailure('Unsupported key combination')
        if action=='key': gui.hotkey(*keys)
        else:
            try:
                for key in keys: gui.keyDown(key)
                time.sleep(max(0,min(a.get('seconds',1),10)))
            finally:
                for key in reversed(keys): gui.keyUp(key)
    else: raise ToolFailure('Unsupported portable desktop action')
    return {'action':action,'completed':True,'display':'primary'},None
