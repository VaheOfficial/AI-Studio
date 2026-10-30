"""Generated Python runs outside the server, with deadlines and bounded process output.

Process mode runs with the local user's OS authority. Optional container mode applies the configured
Docker boundary with no network and a dedicated output mount. Both use the run_python permission.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
from typing import Any
import psutil

from .. import config
from ..osenv import NO_WINDOW
from ..proc import bind_to_server_lifetime, kill_tree


def check_schema(value: Any, schema: dict[str, Any], path: str = "value") -> None:
    types = {"object": dict, "array": list, "string": str, "number": (int, float), "integer": int,
             "boolean": bool, "null": type(None)}
    kind = schema.get("type")
    if kind not in types:
        raise ValueError(f"{path}: schema needs a supported type")
    if not isinstance(value, types[kind]) or (kind in ("integer", "number") and isinstance(value, bool)):
        raise ValueError(f"{path}: expected {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path}: value is not in enum")
    if kind == "object":
        props = schema.get("properties", {})
        missing = set(schema.get("required", [])) - value.keys()
        if missing:
            raise ValueError(f"{path}: missing {sorted(missing)}")
        if schema.get("additionalProperties") is False and value.keys() - props.keys():
            raise ValueError(f"{path}: unexpected properties")
        for key, item in value.items():
            if key in props:
                check_schema(item, props[key], f"{path}.{key}")
    if kind == "array" and "items" in schema:
        for i, item in enumerate(value):
            check_schema(item, schema["items"], f"{path}[{i}]")
    if kind in ("string", "array"):
        for key, op in (("minLength" if kind == "string" else "minItems", lambda a, b: a < b),
                        ("maxLength" if kind == "string" else "maxItems", lambda a, b: a > b)):
            if key in schema and op(len(value), schema[key]):
                raise ValueError(f"{path}: violates {key}")
    if kind in ("integer", "number"):
        if "minimum" in schema and value < schema["minimum"]:
            raise ValueError(f"{path}: below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise ValueError(f"{path}: above maximum")


async def invoke(code: str, args: dict[str, Any], sid: str, timeout: float = 30, testing: bool = False) -> dict[str, Any]:
    # Sessions are generated IDs, not user-controlled filesystem paths.
    if not sid.isalnum():
        raise ValueError("Invalid chat identifier")
    cwd = (config.CACHE_DIR if testing else config.OUTPUTS_DIR) / "agentplus" / sid
    cwd.mkdir(parents=True, exist_ok=True)
    def output_files():
        return (p for p in cwd.rglob('*') if p.is_file() and '_versions' not in p.relative_to(cwd).parts
                and cwd.resolve() in p.resolve().parents)
    before = {str(p): (p.stat().st_mtime_ns, p.stat().st_size) for p in output_files()}
    from ..agents import sandbox, store as agent_store
    if agent_store.identity(sid).sandbox == "container":
        result = await sandbox.invoke(code, args, cwd, timeout)
        if not testing:
            changed = [p for p in output_files() if before.get(str(p)) != (p.stat().st_mtime_ns, p.stat().st_size)][:20]
            result["files"] = [str(p) for p in changed]
            snapshots = []
            for path in changed:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                target = cwd / "_versions" / digest / path.relative_to(cwd)
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    shutil.copy2(path, target)
                snapshots.append(str(target))
            result["artifacts"] = snapshots
        return result
    inherited = {k: v for k, v in os.environ.items() if k.upper() in
                 {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG"}}
    inherited.update(PYTHONIOENCODING="utf-8", CUDA_VISIBLE_DEVICES="-1")
    proc = await asyncio.create_subprocess_exec(
        str(config.SERVER_PYTHON), "-I", str(config.WORKERS_DIR / "chat_tool_worker.py"),
        cwd=cwd, env=inherited, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, creationflags=NO_WINDOW)

    async def read(stream: asyncio.StreamReader) -> bytes:
        chunks, size = [], 0
        while chunk := await stream.read(16384):
            size += len(chunk)
            if size > 1024 * 1024:
                raise ValueError("Tool exceeded the output limit")
            chunks.append(chunk)
        return b"".join(chunks)

    async def exchange() -> dict[str, Any]:
        assert proc.stdin and proc.stdout and proc.stderr
        payload = json.dumps({"code": code, "args": args}, allow_nan=False).encode()
        if len(payload) > 1024 * 1024:
            raise ValueError("Tool input is too large")
        proc.stdin.write(payload)
        await proc.stdin.drain()
        proc.stdin.close()
        stdout, stderr = await asyncio.gather(read(proc.stdout), read(proc.stderr))
        await proc.wait()
        if proc.returncode:
            return {"ok": False, "error": stderr.decode(errors="replace")[:16000] or f"Exit {proc.returncode}"}
        result = json.loads(stdout)
        if not isinstance(result, dict) or not isinstance(result.get("ok"), bool):
            raise ValueError("Invalid tool result")
        return result

    async def bounded() -> dict[str, Any]:
        task = asyncio.create_task(exchange())
        try:
            while not task.done():
                try:
                    parent = psutil.Process(proc.pid)
                    rss = sum(p.memory_info().rss for p in [parent, *parent.children(recursive=True)])
                    if rss > 1024 * 1024 * 1024:
                        raise ValueError("Tool exceeded the 1 GiB memory limit")
                except psutil.NoSuchProcess:
                    pass
                await asyncio.wait({task}, timeout=0.1)
            return await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    try:
        bind_to_server_lifetime(proc)  # type: ignore[arg-type]
        result = await asyncio.wait_for(bounded(), timeout=timeout)
        if not testing:
            changed = [p for p in output_files()
                       if before.get(str(p)) != (p.stat().st_mtime_ns, p.stat().st_size)][:20]
            result['files'] = [str(p) for p in changed]
            # Downloads refer to a content snapshot so later calls cannot overwrite an earlier result.
            snapshots = []
            for p in changed:
                digest = hashlib.sha256()
                with p.open('rb') as stream:
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
                snapshot = cwd / '_versions' / digest.hexdigest() / p.relative_to(cwd)
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                if not snapshot.exists():
                    shutil.copy2(p, snapshot)
                snapshots.append(str(snapshot))
            result['artifacts'] = snapshots
        return result
    except TimeoutError:
        return {"ok": False, "error": f"Tool timed out after {timeout:g} seconds"}
    except (ValueError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        if proc.returncode is None:
            await asyncio.to_thread(kill_tree, proc.pid)
            await proc.wait()
