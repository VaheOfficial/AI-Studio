"""User-started browser demonstrations become editable skill drafts."""
from __future__ import annotations
import json
import time
from ..schemas_agents import SkillCreate
from . import store
from .. import db
from ..agent.types import ToolFailure, ToolOutcome, ToolSpec
from .tools import obj, S, O

SPECS=[ToolSpec('replay_demonstration','Replay a reviewed enabled browser demonstration using recorded stable selectors and explicit new inputs. Coordinates are never replayed blindly. Each step retains ordinary approval and user takeover. Secure-input steps require human handoff.',obj({'skill_id':S,'inputs':O},['skill_id','inputs']),needs_approval=True)]


def init():
    db.execute('CREATE TABLE IF NOT EXISTS agent_browser_demonstrations (skill_id TEXT PRIMARY KEY, data TEXT NOT NULL)')

_recordings: dict[str, dict] = {}


def start(sid: str):
    if sid in _recordings:
        raise ValueError('A demonstration is already recording')
    _recordings[sid] = {'started': time.monotonic(), 'events': []}
    return {'recording': True, 'maximum_seconds': 600}


async def record(sid: str, page, data: dict):
    recording = _recordings.get(sid)
    if not recording or time.monotonic() - recording['started'] > 600 or len(recording['events']) >= 1200:
        return
    value = {**data, 'url': page.url, 'at_seconds': round(time.monotonic() - recording['started'], 2)}
    if data.get('type') in ('click','text'):
        try:
            locator=await page.evaluate('''(a) => {
              let e=a.type==='click'?document.elementFromPoint(a.x,a.y):document.activeElement;
              e=e?.closest('input,textarea,button,a,select,[role="button"],[contenteditable="true"]')||e;
              if(!e)return null;
              let selector=e.id?'#'+CSS.escape(e.id):e.getAttribute('data-testid')?'[data-testid='+JSON.stringify(e.getAttribute('data-testid'))+']':e.getAttribute('aria-label')?'[aria-label='+JSON.stringify(e.getAttribute('aria-label'))+']':e.name?e.tagName.toLowerCase()+'[name='+JSON.stringify(e.name)+']':null;
              return {selector,unique:selector?document.querySelectorAll(selector).length===1:false,input:e.name||e.id||e.getAttribute('aria-label')||'value'};
            }''',data)
            if locator and locator['unique']:
                value['selector']=locator['selector'];value['input_name']=locator['input']
        except Exception: pass
    if data.get('type') == 'text':
        try:
            element = await page.evaluate('''() => { const e=document.activeElement; return e ? {type:e.type||'',name:e.name||'',autocomplete:e.autocomplete||'',id:e.id||'',tag:e.tagName} : {}; }''')
            import re
            private = re.search(r'password|passcode|token|secret|one-time|credit|card|cvv|otp', ' '.join(str(v) for v in element.values()), re.I)
            value['text'] = '[private input omitted]' if private else str(data.get('text', ''))[:2000]
            value['field'] = element
        except Exception:
            value['text'] = '[input omitted: field could not be inspected]'
    recording['events'].append(value)


def finish(sid: str, name: str):
    recording = _recordings.pop(sid, None)
    if not recording:
        raise ValueError('No demonstration is recording')
    if not recording['events']:
        raise ValueError('No browser actions were recorded')
    instructions = ('Draft captured from a browser demonstration. Review selectors and values before reuse. '
        'Use current page snapshots rather than assuming coordinates stay valid. Private inputs require a secure user handoff. '
        'Verify the actual requested outcome.\n\nRecorded actions:\n' + json.dumps(recording['events'], ensure_ascii=False, indent=2))
    value = store.add_skill(SkillCreate(name=name, description='Browser demonstration draft', instructions=instructions[:32000],
                                      permissions=['browser_click', 'browser_type']))
    value.enabled = False
    db.execute('INSERT INTO agent_browser_demonstrations VALUES(?,?)',(value.id,json.dumps({'events':recording['events'],'scope':sid})))
    db.execute('UPDATE agent_skills SET data=? WHERE id=?', (value.model_dump_json(), value.id))
    store.notify('skills', sid)
    return value


async def replay(a,ctx):
    from urllib.parse import urlsplit
    skill=store.skill(a['skill_id'])
    if not skill.enabled: raise ToolFailure('Review and enable the recorded skill before replay')
    row=db.query_one('SELECT data FROM agent_browser_demonstrations WHERE skill_id=?',(skill.id,))
    if not row or not ctx.invoke: raise ToolFailure('A recorded demonstration and active dispatcher are required')
    events=json.loads(row['data'])['events']
    if len(events)>100: raise ToolFailure('Replay at most 100 reviewed steps')
    unsupported=[]
    for index,event in enumerate(events):
        if event['type'] in ('click','text') and not event.get('selector'): unsupported.append(index)
        if event['type']=='text' and str(event.get('text','')).startswith(('[private input omitted]', '[input omitted:')): unsupported.append(index)
        if event['type'] not in ('click','text','key','scroll'): unsupported.append(index)
        if event['type']=='text' and event.get('input_name') not in a['inputs']: unsupported.append(index)
    if unsupported: raise ToolFailure('Review unsupported or secure-input steps before replay: '+str(sorted(set(unsupported))))
    receipts=[]
    first=events[0]['url'] if events else None
    if first:
        outcome=await ctx.invoke('browser_navigate',{'url':first})
        if not outcome.ok: return outcome
    for event in events:
        current=await ctx.invoke('browser_action',{'action':'list_tabs'})
        if not current.ok: return current
        actual=urlsplit(json.loads(current.output)['url']);expected=urlsplit(event['url'])
        if (actual.scheme,actual.netloc,actual.path)!=(expected.scheme,expected.netloc,expected.path):
            raise ToolFailure('The page changed from the reviewed demonstration; inspect it before continuing')
        if event['type']=='click': args={'action':'click','selector':event['selector']}
        elif event['type']=='text': args={'action':'form_input','selector':event['selector'],'value':a['inputs'][event['input_name']]}
        elif event['type']=='key': args={'action':'key','key':event['key']}
        else: args={'action':'scroll','dy':event.get('deltaY',event.get('dy',0))}
        outcome=await ctx.invoke('browser_action',args)
        receipts.append({'step':len(receipts)+1,'ok':outcome.ok,'output':outcome.output})
        if not outcome.ok: return ToolOutcome(False,json.dumps(receipts))
    return ToolOutcome(True,json.dumps({'steps':receipts,'next':'Read the resulting page and verify the requested outcome; replay completion is not outcome validation.'}))


IMPL={'replay_demonstration':replay}


def cancel(sid: str):
    _recordings.pop(sid, None)
