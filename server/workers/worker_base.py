"""Minimal JSON-over-HTTP server shared by runtime workers (stdlib only, so it runs in any env).

Every worker exposes:
  GET  /health    -> {"ok": true, "runtime", "loaded_model", "busy"}
  GET  /progress  -> {"step", "total", "message", "preview"?}
  POST /load      {"model_id", "path", "offload"}
  POST /unload
  POST /cancel    (interrupts the running generation)
plus runtime-specific POST routes registered by the worker.
Errors are returned as {"detail": "..."} with a 4xx/5xx status.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import threading
import traceback
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

Handler = Callable[[dict[str, Any]], dict[str, Any]]


class Cancelled(Exception):
    pass


class BadRequest(Exception):
    pass


class Progress:
    def __init__(self) -> None:
        self.step = 0
        self.total = 0
        self.message = ""
        self.cancel = threading.Event()
        # Optional live preview of the running generation: {"step": int, "image": data URL}
        self.preview: dict[str, Any] | None = None

    def reset(self, total: int = 0, message: str = "") -> None:
        self.step, self.total, self.message, self.preview = 0, total, message, None
        self.cancel.clear()

    def check(self) -> None:
        if self.cancel.is_set():
            raise Cancelled()

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"step": self.step, "total": self.total, "message": self.message}
        if self.preview is not None:
            data["preview"] = self.preview
        return data


class Worker:
    """Base class: subclasses implement ``_load``/``_unload`` and register routes in ``routes``."""

    def __init__(self, runtime: str) -> None:
        self.runtime = runtime
        self.loaded_model: str | None = None
        self.progress = Progress()
        self.busy = threading.Lock()  # one load/generation at a time
        self.routes: dict[str, Handler] = {
            "/load": self.load,
            "/unload": self.unload,
            "/cancel": self.cancel,
        }

    # -- lifecycle -------------------------------------------------------

    def load(self, req: dict[str, Any]) -> dict[str, Any]:
        with self.busy:
            if self.loaded_model == req["model_id"]:
                return {"ok": True, "loaded_model": self.loaded_model}
            self._release()
            log(f"Loading {req['model_id']} from {req['path']} (offload={req.get('offload', 'none')})")
            self._load(req)
            self.loaded_model = req["model_id"]
            log(f"Loaded {self.loaded_model}")
            return {"ok": True, "loaded_model": self.loaded_model}

    def unload(self, _req: dict[str, Any]) -> dict[str, Any]:
        with self.busy:
            self._release()
        return {"ok": True}

    def cancel(self, _req: dict[str, Any]) -> dict[str, Any]:
        self.progress.cancel.set()
        return {"ok": True}

    def _release(self) -> None:
        if self.loaded_model is None:
            return
        log(f"Unloading {self.loaded_model}")
        self._unload()
        self.loaded_model = None
        gc.collect()
        free_cuda()

    def _load(self, req: dict[str, Any]) -> None:
        raise NotImplementedError

    def _unload(self) -> None:
        raise NotImplementedError

    def require_loaded(self) -> None:
        if self.loaded_model is None:
            raise BadRequest("No model loaded; POST /load first")

    def health(self) -> dict[str, Any]:
        return {"ok": True, "runtime": self.runtime, "loaded_model": self.loaded_model,
                "busy": self.busy.locked()}


def free_cuda() -> None:
    try:
        import torch
    except ImportError:
        return
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()


def log(message: str) -> None:
    print(message, flush=True)


def _make_handler(worker: Worker) -> type[BaseHTTPRequestHandler]:
    class RequestHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:  # silence per-request access logs
            return

        def _send(self, status: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send(200, worker.health())
            elif self.path == "/progress":
                self._send(200, worker.progress.as_dict())
            else:
                self._send(404, {"detail": f"No route GET {self.path}"})

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError as exc:
                self._send(400, {"detail": f"Invalid JSON: {exc}"})
                return
            route = worker.routes.get(self.path)
            if route is None:
                self._send(404, {"detail": f"No route POST {self.path}"})
                return
            try:
                self._send(200, route(payload))
            except Cancelled:
                self._send(409, {"detail": "Cancelled"})
            except BadRequest as exc:
                self._send(400, {"detail": str(exc)})
            except Exception as exc:
                traceback.print_exc()
                self._send(500, {"detail": f"{type(exc).__name__}: {exc}"})

    return RequestHandler


def _exit_with_parent(pid: int) -> None:
    """Exit as soon as the Studio server process dies, so a crashed server never leaves a
    worker holding VRAM."""
    if sys.platform == "win32":
        import ctypes

        synchronize = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
        if handle:
            ctypes.windll.kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
    else:
        import time

        while os.getppid() == pid:
            time.sleep(2)
    # No logging here: stdout is a pipe to the dead server and writing to it would raise.
    os._exit(0)


def serve(factory: Callable[[str], Worker]) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args()
    if args.parent_pid:
        threading.Thread(target=_exit_with_parent, args=(args.parent_pid,), daemon=True).start()
    worker = factory(args.runtime)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), _make_handler(worker))
    server.daemon_threads = True
    log(f"{args.runtime} worker listening on 127.0.0.1:{args.port} (python {sys.version.split()[0]})")
    server.serve_forever()
