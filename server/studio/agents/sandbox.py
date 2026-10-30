"""Local container execution; no fallback to host execution when isolation is selected."""
from __future__ import annotations
import asyncio
import json
import os
import shutil
import uuid
from pathlib import Path
from .. import config
from ..agent.types import ToolFailure
from ..osenv import NO_WINDOW

IMAGE = os.environ.get('STUDIO_AGENT_WORKER_IMAGE', 'grom-agent-worker:1')


def command(cwd: Path, worker: Path, name: str) -> list[str]:
    docker = shutil.which('docker')
    if not docker:
        raise ToolFailure('Container execution requires a local Docker engine. Choose process mode or configure Docker.')
    return [docker, 'run', '--rm', '--interactive', '--name', name, '--pull=never', '--network=none',
            '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit=64',
            '--memory=1g', '--cpus=2', '--user=65534:65534', '--tmpfs=/tmp:rw,noexec,nosuid,size=64m',
            '--mount', f'type=bind,source={cwd.resolve()},target=/work', '--mount',
            f'type=bind,source={worker.resolve()},target=/worker.py,readonly', '--workdir=/work',
            IMAGE, 'python', '-I', '/worker.py']


async def stop(name: str) -> None:
    docker = shutil.which('docker')
    if docker:
        proc = await asyncio.create_subprocess_exec(docker, 'rm', '-f', name,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, creationflags=NO_WINDOW)
        try:
            await asyncio.wait_for(proc.wait(), 10)
        except TimeoutError:
            proc.kill()


async def invoke(code: str, args: dict, cwd: Path, timeout: float) -> dict:
    name = 'grom-tool-' + uuid.uuid4().hex[:16]
    proc = await asyncio.create_subprocess_exec(*command(cwd, config.WORKERS_DIR / 'chat_tool_worker.py', name),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, creationflags=NO_WINDOW)
    async def read(stream):
        chunks, size = [], 0
        while chunk := await stream.read(16384):
            size += len(chunk)
            if size > 1024 * 1024:
                raise ToolFailure('Container output limit exceeded')
            chunks.append(chunk)
        return b''.join(chunks)
    async def exchange():
        payload = json.dumps({'code': code, 'args': args}, allow_nan=False).encode()
        if len(payload) > 1024 * 1024:
            raise ToolFailure('Container input limit exceeded')
        proc.stdin.write(payload)
        await proc.stdin.drain()
        proc.stdin.close()
        stdout, stderr = await asyncio.gather(read(proc.stdout), read(proc.stderr))
        await proc.wait()
        if proc.returncode:
            return {'ok': False, 'error': stderr.decode(errors='replace')[:16000] or f'Exit {proc.returncode}'}
        value = json.loads(stdout)
        if not isinstance(value, dict) or not isinstance(value.get('ok'), bool):
            raise ToolFailure('Invalid container result')
        value['execution'] = 'container'
        return value
    try:
        return await asyncio.wait_for(exchange(), timeout)
    except TimeoutError:
        return {'ok': False, 'error': f'Container timed out after {timeout:g} seconds'}
    finally:
        await stop(name)
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
