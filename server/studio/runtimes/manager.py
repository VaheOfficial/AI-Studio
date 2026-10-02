"""Starts, health-checks, proxies and stops runtime worker processes (one process per runtime)."""

from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from ..osenv import detached
from .. import config, db, events, settings
from ..events import bus
from ..jobs import jobs
from ..localhttp import client
from ..proc import kill_tree
from ..schemas import EvRuntimeUpdate, ModelKind, RuntimeId, RuntimeInfo
from . import envs


@dataclass(frozen=True)
class RuntimeDef:
    id: RuntimeId
    name: str
    kinds: list[ModelKind]
    env: str | None = None  # data/envs/<env>; None = no Python env (ollama, remote)
    worker: str | None = None  # script in server/workers


RUNTIMES: dict[str, RuntimeDef] = {r.id: r for r in [
    RuntimeDef("ollama", "Ollama", ["text"]),
    RuntimeDef("lmstudio", "LM Studio", ["text"]),
    RuntimeDef("llamacpp", "llama.cpp", ["text"]),
    RuntimeDef("remote", "Remote API (OpenAI-compatible)", ["text"]),
    RuntimeDef("diffusers", "Diffusers", ["image"], "image", "image_worker.py"),
    RuntimeDef("hunyuan-image3", "HunyuanImage 3", ["image"], "image", "image_worker.py"),
    RuntimeDef("diffusers-video", "Video (Wan 2.2, LTX-2.5)", ["video"], "image", "video_worker.py"),
    RuntimeDef("tencent-cloud", "Tencent Cloud (HY-Image)", ["image"]),
    RuntimeDef("kokoro", "Kokoro TTS", ["voice"], "voice", "voice_worker.py"),
    RuntimeDef("chatterbox", "Chatterbox TTS", ["voice"], "voice", "voice_worker.py"),
    RuntimeDef("faster-whisper", "faster-whisper STT", ["stt"], "voice", "voice_worker.py"),
    RuntimeDef("omnivoice", "OmniVoice TTS", ["voice"], "omnivoice", "omnivoice_worker.py"),
    RuntimeDef("ace-step", "ACE-Step", ["music"], "music", "music_worker.py"),
    RuntimeDef("dub", "Dubbing & audio tools (Demucs, Whisper, pyannote, NLLB)", ["stt"], "dub", "dub_worker.py"),
    # No models: the environment the agent's run_python kernels use (pandas, matplotlib, docx/xlsx/pptx/pdf)
    RuntimeDef("python", "Python tools (analysis, charts, documents)", [], "python"),
]}

_STARTUP_TIMEOUT_S = 180


class WorkerError(RuntimeError):
    """A worker request failed; message is user-facing."""


class RuntimeNotReady(WorkerError):
    pass


@dataclass
class _Worker:
    proc: subprocess.Popen[str]
    port: int
    loaded_model: str | None = None
    healthy: bool = False


def _free_port() -> int:
    with socket.socket() as s:
        s.bind((config.HOST, 0))
        return s.getsockname()[1]


@dataclass(frozen=True)
class ExternalStatus:
    """State of a runtime whose process the studio doesn't run as a Python worker (LM Studio, llama-server)."""

    installed: bool
    running: bool
    port: int | None = None
    loaded_model: str | None = None


class RuntimeManager:
    def __init__(self) -> None:
        self._workers: dict[str, _Worker] = {}
        self._locks: dict[str, threading.Lock] = {rid: threading.Lock() for rid in RUNTIMES}
        self._ollama_status: tuple[bool, bool] = (False, False)  # (installed, running), refreshed by ollama module
        self._external: dict[str, Callable[[], ExternalStatus]] = {}

    def register_external(self, runtime_id: RuntimeId, status: Callable[[], ExternalStatus]) -> None:
        """Let a module that manages its own process report the runtime's state (must be cheap to call)."""
        self._external[runtime_id] = status

    # ------------------------------ info ------------------------------

    def get_def(self, runtime_id: str) -> RuntimeDef:
        rdef = RUNTIMES.get(runtime_id)
        if rdef is None:
            raise KeyError(runtime_id)
        return rdef

    def env_ready(self, runtime_id: str) -> bool:
        rdef = self.get_def(runtime_id)
        if rdef.id == "ollama":
            return self._ollama_status[0]
        if rdef.id in self._external:
            return self._external[rdef.id]().installed
        if rdef.env is None:
            return True
        return envs.is_ready(rdef.env)

    def info(self, runtime_id: str) -> RuntimeInfo:
        rdef = self.get_def(runtime_id)
        if rdef.id in self._external:
            st = self._external[rdef.id]()
            return RuntimeInfo(id=rdef.id, name=rdef.name, kinds=rdef.kinds, env_ready=st.installed,
                               running=st.running, port=st.port, loaded_model=st.loaded_model)
        w = self._workers.get(runtime_id)
        alive = w is not None and w.proc.poll() is None
        running = self._ollama_status[1] if rdef.id == "ollama" else (rdef.id in ("remote", "tencent-cloud") or alive)
        return RuntimeInfo(
            id=rdef.id, name=rdef.name, kinds=rdef.kinds, env_ready=self.env_ready(runtime_id), running=running,
            port=w.port if alive and w else (11434 if rdef.id == "ollama" and running else None),
            loaded_model=w.loaded_model if alive and w else None,
        )

    def all_info(self) -> list[RuntimeInfo]:
        return [self.info(rid) for rid in RUNTIMES]

    def publish(self, runtime_id: str) -> None:
        bus.publish(EvRuntimeUpdate(runtime=self.info(runtime_id)))

    def publish_env(self, env_name: str) -> None:
        for rdef in RUNTIMES.values():
            if rdef.env == env_name:
                self.publish(rdef.id)

    def set_ollama_status(self, installed: bool, running: bool) -> None:
        changed = self._ollama_status != (installed, running)
        self._ollama_status = (installed, running)
        if changed:
            self.publish("ollama")

    def loaded_model(self, runtime_id: str) -> str | None:
        if runtime_id in self._external:
            return self._external[runtime_id]().loaded_model
        w = self._workers.get(runtime_id)
        return w.loaded_model if w and w.proc.poll() is None else None

    # --------------------------- lifecycle ---------------------------

    def ensure_running(self, runtime_id: str) -> _Worker:
        rdef = self.get_def(runtime_id)
        if rdef.worker is None or rdef.env is None:
            raise WorkerError(f"Runtime '{runtime_id}' has no worker process")
        if envs.is_outdated(rdef.env):
            self._update_env(rdef)
        if not envs.is_ready(rdef.env):
            raise RuntimeNotReady(
                f"The '{rdef.env}' Python environment for {rdef.name} is not installed yet. "
                f"Install it with POST /api/runtimes/{runtime_id}/install (installing a model does this too)."
            )
        with self._locks[runtime_id]:
            w = self._workers.get(runtime_id)
            if w and w.proc.poll() is None and w.healthy:
                return w
            if w and w.proc.poll() is None:
                self._kill(w)
            return self._spawn(rdef)

    def _update_env(self, rdef: RuntimeDef) -> None:
        """The env was installed for an earlier version of the app: bring it up to date before it is used, instead
        of refusing to load anything until the user does it by hand. Workers running on it are stopped first (they
        hold the old packages); the install only changes what differs."""
        assert rdef.env
        events.log("info", "runtimes", f"Updating the '{rdef.env}' environment: this version of the app needs "
                                       "newer packages in it")
        for other in RUNTIMES.values():
            if other.env == rdef.env and other.id in self._workers:
                self.stop(other.id)
        job = envs.ensure_env_job(rdef.env, rdef.id)
        if job is None:
            return
        result = jobs.wait_blocking(job.id)
        if result.status != "done":
            raise RuntimeNotReady(f"Updating the '{rdef.env}' environment for {rdef.name} failed: "
                                  f"{result.error or result.status}. Retry under Models → Runtimes.")

    def _spawn(self, rdef: RuntimeDef) -> _Worker:
        assert rdef.env and rdef.worker
        port = _free_port()
        env = dict(os.environ)
        env.update({
            "PYTHONUNBUFFERED": "1",
            "PYTHONUTF8": "1",
            "HF_HOME": str(config.CACHE_DIR / "hf"),
            "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
            "HF_HUB_DISABLE_PROGRESS_BARS": "1",
            "TOKENIZERS_PARALLELISM": "false",
            "STUDIO_DATA_DIR": str(config.DATA_DIR),
        })
        token = settings.load().hf_token
        if token:
            env["HF_TOKEN"] = token
        cmd = [str(envs.env_python(rdef.env)), "-u", str(config.WORKERS_DIR / rdef.worker),
               "--runtime", rdef.id, "--port", str(port), "--parent-pid", str(os.getpid())]
        events.log("info", rdef.id, f"Starting worker on port {port}")
        proc = subprocess.Popen(cmd, cwd=config.WORKERS_DIR, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                **detached())
        w = _Worker(proc=proc, port=port)
        self._workers[rdef.id] = w
        tail: list[str] = []
        threading.Thread(target=self._pump_logs, args=(rdef.id, w, tail), daemon=True,
                         name=f"log-{rdef.id}").start()
        deadline = time.monotonic() + _STARTUP_TIMEOUT_S
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                time.sleep(0.2)  # let the log pump drain the traceback
                raise WorkerError(f"{rdef.name} worker exited during startup (code {proc.returncode}):\n"
                                  + "\n".join(tail[-20:]))
            try:
                r = client.get(f"http://{config.HOST}:{port}/health", timeout=1.0)
                if r.status_code == 200:
                    w.healthy = True
                    events.log("info", rdef.id, "Worker ready")
                    self.publish(rdef.id)
                    return w
            except httpx.TransportError:
                pass
            time.sleep(0.5)
        self._kill(w)
        raise WorkerError(f"{rdef.name} worker did not become healthy within {_STARTUP_TIMEOUT_S}s")

    def _pump_logs(self, runtime_id: str, w: _Worker, tail: list[str]) -> None:
        assert w.proc.stdout is not None
        for raw in w.proc.stdout:
            line = raw.rstrip()
            if not line:
                continue
            tail.append(line)
            del tail[:-50]
            level: events.LogLevel = "error" if ("Traceback" in line or "Error" in line) else "info"
            events.log(level, runtime_id, line)
        code = w.proc.wait()
        if self._workers.get(runtime_id) is w:
            self._workers.pop(runtime_id, None)
            events.log("warn" if code else "info", runtime_id, f"Worker exited (code {code})")
            self._reset_model_status(runtime_id)
            self.publish(runtime_id)

    def _reset_model_status(self, runtime_id: str) -> None:
        from ..models import models  # late import: models depends on this module

        for m in db.list_installed():
            if m.runtime == runtime_id and m.status in ("loaded", "loading"):
                models.set_status(m.id, "ready")

    def _kill(self, w: _Worker) -> None:
        kill_tree(w.proc)
        try:
            w.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            events.log("warn", "runtimes", f"Worker pid {w.proc.pid} did not exit after kill")

    def stop(self, runtime_id: str) -> RuntimeInfo:
        self.get_def(runtime_id)
        with self._locks[runtime_id]:
            w = self._workers.pop(runtime_id, None)
            if w:
                events.log("info", runtime_id, "Stopping worker")
                self._kill(w)
        self._reset_model_status(runtime_id)
        self.publish(runtime_id)
        return self.info(runtime_id)

    def stop_all(self) -> None:
        for rid in list(self._workers):
            w = self._workers.pop(rid, None)
            if w:
                self._kill(w)

    # ----------------------------- requests -----------------------------

    def request(self, runtime_id: str, method: str, path: str, json: dict[str, Any] | None = None,
                timeout: float | None = 30.0, start: bool = True) -> dict[str, Any]:
        w = self.ensure_running(runtime_id) if start else self._workers.get(runtime_id)
        if w is None or w.proc.poll() is not None:
            raise WorkerError(f"{runtime_id} worker is not running")
        try:
            r = httpx.request(method, f"http://{config.HOST}:{w.port}{path}", json=json, timeout=timeout)
        except httpx.TransportError as exc:
            alive = w.proc.poll() is None
            raise WorkerError(f"{runtime_id} worker {'did not respond' if alive else 'crashed'} "
                              f"on {path}: {exc}") from exc
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except ValueError:
                detail = r.text
            raise WorkerError(f"{runtime_id}: {detail}")
        body: dict[str, Any] = r.json()
        return body

    def set_loaded(self, runtime_id: str, model_id: str | None) -> None:
        w = self._workers.get(runtime_id)
        if w:
            w.loaded_model = model_id
        self.publish(runtime_id)


runtimes = RuntimeManager()
