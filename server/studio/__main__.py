"""``python -m studio``: the server as the desktop app runs it.

The same app as ``uvicorn studio.main:app`` on ``STUDIO_PORT``. With ``STUDIO_WATCH_PARENT=1`` it also shuts down
when its standard input closes: the desktop app holds that pipe open for as long as it lives, so the server (and
the workers and model servers it started) never outlives the window - not even when the app crashes."""

from __future__ import annotations

import os
import sys
import threading

import uvicorn

from . import config, proc

_SHUTDOWN_GRACE_S = 20  # a normal shutdown saves running turns and stops the workers within a few seconds


def _exit_with_parent(server: uvicorn.Server) -> None:
    try:
        sys.stdin.buffer.read()  # returns at end of file: the parent closed the pipe, or died
    except (OSError, ValueError):
        pass
    server.should_exit = True

    def force() -> None:  # a shutdown that hangs must not leave a headless server behind
        proc.kill_bound()
        os._exit(0)

    timer = threading.Timer(_SHUTDOWN_GRACE_S, force)
    timer.daemon = True
    timer.start()


def main() -> None:
    # Open WebSockets and streams would hold a graceful shutdown forever; after a few seconds they are cancelled
    # and the app's own shutdown (saving turns, stopping workers) runs
    server = uvicorn.Server(uvicorn.Config("studio.main:app", host=config.HOST, port=config.PORT, log_level="info",
                                           timeout_graceful_shutdown=3))
    if os.environ.get("STUDIO_WATCH_PARENT") == "1":
        threading.Thread(target=_exit_with_parent, args=(server,), name="parent-watch", daemon=True).start()
    server.run()


if __name__ == "__main__":
    main()
