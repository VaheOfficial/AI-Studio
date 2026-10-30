"""Programmatic composition through the normal permission and receipt dispatcher."""
from __future__ import annotations
import asyncio
import json
import os
import uuid
from .. import config
from ..agent.types import ToolFailure, ToolOutcome, ToolSpec
from ..osenv import NO_WINDOW
from ..proc import kill_tree
from . import registry, sandbox, store
from .tools import obj, O, S

SPECS = [ToolSpec('run_tool_script', 'Run bounded Python orchestration. tools.NAME(**args) invokes the approved registry; inputs contains input JSON. Set result to the compact final JSON. All nested tools retain approval, scope and receipts.',
    obj({'code': S, 'inputs': O, 'timeout_s': {'type': 'integer'}}, ['code']), asks_like=lambda _: 'run_python')]


async def run(a, ctx):
    if not ctx.invoke:
        raise ToolFailure('An active agent dispatcher is required')
    if len(a['code']) > 64000:
        raise ToolFailure('Script exceeds 64000 characters')
    cwd = config.OUTPUTS_DIR / 'agents' / ctx.session_id / 'scripts'
    cwd.mkdir(parents=True, exist_ok=True)
    name = 'grom-script-' + uuid.uuid4().hex[:16]
    worker = config.WORKERS_DIR / 'tool_script_worker.py'
    isolated = store.identity(ctx.session_id).sandbox == 'container'
    command = sandbox.command(cwd, worker, name) if isolated else [str(config.SERVER_PYTHON), '-I', str(worker)]
    environment = {k: v for k, v in os.environ.items() if k.upper() in {'SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP', 'LANG'}}
    environment.update(PYTHONIOENCODING='utf-8', CUDA_VISIBLE_DEVICES='-1')
    proc = await asyncio.create_subprocess_exec(*command, cwd=cwd, env=environment,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        limit=1024 * 1024, creationflags=NO_WINDOW)
    allowed = {s.name for s in registry.catalog(ctx.session_id)} - {'run_tool_script', 'execute_tools'}
    async def stderr_tail():
        tail = b''
        while chunk := await proc.stderr.read(16384):
            tail = (tail + chunk)[-16000:]
        return tail
    errors = asyncio.create_task(stderr_tail())
    async def exchange():
        proc.stdin.write(json.dumps({'code': a['code'], 'inputs': a.get('inputs', {})}, allow_nan=False).encode() + b'\n')
        await proc.stdin.drain()
        calls = 0
        while line := await proc.stdout.readline():
            message = json.loads(line)
            if message.get('type') == 'result':
                proc.stdin.close()
                await proc.wait()
                message['execution'] = 'container' if isolated else 'process'
                return message
            if message.get('type') != 'call' or message.get('name') not in allowed:
                raise ToolFailure('Script requested an unavailable or recursive tool')
            calls += 1
            if calls > 20:
                raise ToolFailure('Script exceeded the 20-call limit')
            outcome = await ctx.invoke(message['name'], message.get('args', {}))
            proc.stdin.write(json.dumps({'ok': outcome.ok, 'output': outcome.output}).encode() + b'\n')
            await proc.stdin.drain()
        await proc.wait()
        tail = await errors
        raise ToolFailure('Script ended without a result: ' + tail.decode(errors='replace'))
    try:
        timeout = max(5, min(int(a.get('timeout_s', 120)), 600))
        value = await asyncio.wait_for(exchange(), timeout)
        return ToolOutcome(bool(value.get('ok')), json.dumps(value, ensure_ascii=False))
    finally:
        if isolated:
            await sandbox.stop(name)
        if proc.returncode is None:
            await asyncio.to_thread(kill_tree, proc.pid)
            await proc.wait()
        await asyncio.gather(errors, return_exceptions=True)


IMPL = {'run_tool_script': run}
