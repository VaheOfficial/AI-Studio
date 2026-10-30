"""Temporary UI acceptance server with scripted model responses; no model inference."""
from __future__ import annotations

import os
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

temporary = tempfile.TemporaryDirectory(prefix='agentplus-ui-')
os.environ['STUDIO_DATA_DIR'] = temporary.name
os.environ['STUDIO_PORT'] = '8877'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_agent_plus import ScriptedProvider
from studio import agent_plus, automations, connectors, db, memories, openrouter_catalog, openrouter_usage, swarm, workspace
from studio.game import store as game_store
from studio.agent import agent, web_tools
from studio.agent_plus import store
from studio.agent_plus.controller import controller
from studio.agent.types import ToolOutcome
from studio.events import bus
from studio.main import app
from studio.routes import agent_plus as routes
from studio.schemas import ChatModelOption
from studio.schemas_agent_plus import AgentPlusCreate


class PreviewProvider(ScriptedProvider):
    async def stream(self, system, history, tools):
        active = next((m for m in store.list_all() if m.status == 'running'), None)
        if active:
            ScriptedProvider.sid = active.session_id
        async for event in super().stream(system, history, tools):
            yield event


async def models():
    return [ChatModelOption(id='ollama:scripted', provider='ollama', name='Local acceptance fixture', tools=True, available=True)]


async def source(args, ctx):
    return ToolOutcome(True, 'csv.reader returns lists of strings; int parses signed integers. Documentation fixture.')


@asynccontextmanager
async def lifespan(_app):
    import asyncio
    db.init()
    game_store.init()
    workspace.init()
    memories.init()
    openrouter_catalog.init()
    openrouter_usage.init()
    swarm.init()
    automations.init()
    connectors.init()
    agent_plus.init()
    bus.bind_loop(asyncio.get_running_loop())
    controller.start(agent)
    db.set_setting_value('agent_auto_approve', ['run_python'])
    db.set_setting_value('default_chat_model', 'ollama:scripted')
    patches = [patch('studio.agent.loop.get_provider', return_value=PreviewProvider()),
               patch('studio.agent_plus.learning.get_provider', return_value=PreviewProvider()),
               patch('studio.agent.prompt.build', return_value='Complete the mission with tools.'),
               patch('studio.routes.agent.list_chat_models', models),
               patch('studio.agent.tools.all_specs', return_value=web_tools.SPECS),
               patch.dict(web_tools.IMPL, {'fetch_url': source})]
    for p in patches:
        p.start()
    d = await routes.create(AgentPlusCreate(model='ollama:scripted', objective='Create a verified CSV sum report',
                                           criteria=['Report sums signed CSV inputs correctly']))
    print('UI acceptance mission:', d.mission.session_id, flush=True)
    try:
        yield
    finally:
        await controller.shutdown()
        await agent.shutdown()
        await workspace.shutdown()
        for p in reversed(patches):
            p.stop()
        db._conn.close()
        db._conn = None


app.router.lifespan_context = lifespan

if __name__ == '__main__':
    import uvicorn
    try:
        uvicorn.run(app, host='127.0.0.1', port=8877, log_level='warning')
    finally:
        if db._conn:
            db._conn.close()
            db._conn = None
        temporary.cleanup()
