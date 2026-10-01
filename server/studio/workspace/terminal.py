"""PTY terminals: interactive shells the user opens and the agent's commands. ConPTY through ``pywinpty`` on
Windows (PowerShell), a Unix pty through ``ptyprocess`` on macOS and Linux (the user's login shell).

Output is read on a thread per terminal, coalesced on the event loop and pushed as ``terminal.output`` frames
with a running offset (``seq``) so a client that fetched the scrollback over REST can splice live frames onto
it without gaps or duplicates. The agent reads the same stream with ANSI sequences stripped.
"""

from __future__ import annotations

import asyncio
import base64
import re
import threading
import uuid
from pathlib import Path

from .. import db, events, osenv
from ..events import bus
from ..proc import kill_tree
from ..schemas_workspace import (EvTerminalClosed, EvTerminalExit, EvTerminalOutput, EvTerminalUpdate,
                                 TerminalBuffer, TerminalInfo)
from .state import WorkspaceError

SCROLLBACK = 400_000  # chars kept for clients that attach later
TRANSCRIPT = 2_000_000  # chars kept for the agent's reads of a command
FLUSH_S = 0.03
MAX_PER_SESSION = 24
_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_CUP = re.compile(r"\x1b\[\d*(?:;\d*)?[Hf]")
_CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_ESC = re.compile(r"\x1b[@-Z\\-_]|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


if osenv.IS_WINDOWS:
    from winpty import PtyProcess
else:  # same interface: spawn / read / write / setwinsize / wait / exitstatus
    from ptyprocess import PtyProcessUnicode as PtyProcess


def shell_exe() -> str:
    return osenv.shell()


def _shell_argv() -> list[str]:
    """An interactive shell for the user."""
    return [shell_exe(), "-NoLogo"] if osenv.IS_WINDOWS else [shell_exe(), "-l"]


def _command_argv(command: str) -> list[str]:
    """One command for the agent, in the user's environment (PATH, aliases from their login profile)."""
    if osenv.IS_WINDOWS:
        script = f"$ProgressPreference = 'SilentlyContinue'\n{command}"
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        return [shell_exe(), "-NoLogo", "-NoProfile", "-EncodedCommand", encoded]
    return [shell_exe(), "-lc", command]


def strip_ansi(raw: str) -> str:
    """Terminal output as plain text: escape sequences removed, carriage-return overwrites resolved."""
    s = _OSC.sub("", raw)
    s = _CUP.sub("\n", s)
    s = _CSI.sub("", s)
    s = _ESC.sub("", s.replace("\r\n", "\n"))
    lines = []
    for line in s.split("\n"):
        if "\r" in line:
            line = next((seg for seg in reversed(line.split("\r")) if seg.strip()), "")
        lines.append(line.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip("\n")


class Terminal:
    def __init__(self, info: TerminalInfo, argv: list[str], cwd: Path, cols: int, rows: int) -> None:
        self.info = info
        self._loop = asyncio.get_running_loop()
        self._pending: list[tuple[str, bool]] = []
        self._flush_handle: asyncio.TimerHandle | None = None
        self.scrollback = ""
        self.transcript = ""
        self.seq = 0
        self.read_cursor = 0  # transcript offset already returned to the agent
        self.exited: asyncio.Future[int] = self._loop.create_future()
        self.proc = PtyProcess.spawn(argv, cwd=str(cwd), dimensions=(rows, cols))
        threading.Thread(target=self._reader, name=f"pty-{info.id}", daemon=True).start()

    # ---- reader thread ----
    def _reader(self) -> None:
        while True:
            try:
                chunk = self.proc.read(8192)
            except EOFError:
                break
            except Exception as exc:
                events.log("warn", "terminal", f"Terminal {self.info.id} read failed: {exc}")
                break
            if chunk and not self._post(self._on_data, chunk):
                return
        try:
            self.proc.wait()
        except Exception:
            pass
        code = self.proc.exitstatus
        self._post(self._on_exit, code if isinstance(code, int) else -1)

    def _post(self, fn: object, arg: object) -> bool:
        try:
            self._loop.call_soon_threadsafe(fn, arg)  # type: ignore[arg-type]
            return True
        except RuntimeError:  # the event loop is gone (server shutting down)
            return False

    # ---- event loop ----
    def _on_data(self, chunk: str, record: bool = True) -> None:
        """Queue output; ``record=False`` shows text to the user without adding it to the agent's transcript."""
        self._pending.append((chunk, record))
        if self._flush_handle is None:
            self._flush_handle = self._loop.call_later(FLUSH_S, self._flush)

    def _flush(self) -> None:
        self._flush_handle = None
        if not self._pending:
            return
        data = "".join(text for text, _ in self._pending)
        recorded = "".join(text for text, record in self._pending if record)
        self._pending.clear()
        start = self.seq
        self.seq += len(data)
        self.scrollback = (self.scrollback + data)[-SCROLLBACK:]
        if self.info.kind == "command" and len(self.transcript) < TRANSCRIPT:
            self.transcript += recorded
        bus.publish(EvTerminalOutput(id=self.info.id, data=data, seq=start))

    def _on_exit(self, code: int) -> None:
        if self._flush_handle is not None:
            self._flush_handle.cancel()
        self._flush()
        self.info = self.info.model_copy(update={"status": "exited", "exit_code": code})
        bus.publish(EvTerminalExit(id=self.info.id, code=code))
        bus.publish(EvTerminalUpdate(terminal=self.info))
        if not self.exited.done():
            self.exited.set_result(code)

    @property
    def running(self) -> bool:
        return self.info.status == "running"

    def write(self, data: str) -> None:
        if self.running:
            self.proc.write(data)

    def resize(self, cols: int, rows: int) -> None:
        if self.running:
            self.proc.setwinsize(rows, cols)

    def kill(self) -> None:
        if self.running:
            kill_tree(self.proc.pid)

    def buffer(self) -> TerminalBuffer:
        return TerminalBuffer(terminal=self.info, data=self.scrollback, seq=self.seq)

    def clean_output(self, since: int = 0) -> str:
        return strip_ansi(self.transcript[since:])


class TerminalManager:
    def __init__(self) -> None:
        self._terms: dict[str, Terminal] = {}

    def _spawn(self, session_id: str, kind: str, title: str, argv: list[str], cwd: Path, cols: int, rows: int,
               call_id: str | None = None) -> Terminal:
        self._prune(session_id)
        info = TerminalInfo(id=uuid.uuid4().hex[:12], session_id=session_id, title=title, cwd=str(cwd), kind=kind,
                            status="running", call_id=call_id, created_at=db.now_iso())
        try:
            term = Terminal(info, argv, cwd, cols, rows)
        except Exception as exc:
            raise WorkspaceError(f"Could not start a terminal: {exc}") from exc
        self._terms[info.id] = term
        bus.publish(EvTerminalUpdate(terminal=info))
        return term

    def open_shell(self, session_id: str, cwd: Path, cols: int = 120, rows: int = 30) -> Terminal:
        return self._spawn(session_id, "shell", Path(shell_exe()).stem, _shell_argv(), cwd, cols, rows)

    def run_command(self, session_id: str, command: str, cwd: Path, call_id: str | None) -> Terminal:
        argv = _command_argv(command)
        title = command.strip().splitlines()[0][:60] if command.strip() else "command"
        term = self._spawn(session_id, "command", title, argv, cwd, 160, 30, call_id)
        # Echo the command like a prompt line so the terminal reads naturally.
        term._on_data(f"\x1b[2m{cwd}>\x1b[0m \x1b[1m{command.replace(chr(10), chr(13) + chr(10))}\x1b[0m\r\n", record=False)
        return term

    def get(self, terminal_id: str) -> Terminal:
        term = self._terms.get(terminal_id)
        if term is None:
            raise WorkspaceError(f"Unknown terminal or process '{terminal_id}'")
        return term

    def for_session(self, session_id: str) -> list[Terminal]:
        return [t for t in self._terms.values() if t.info.session_id == session_id]

    def close(self, terminal_id: str) -> None:
        term = self._terms.pop(terminal_id, None)
        if term is None:
            return
        term.kill()
        bus.publish(EvTerminalClosed(id=terminal_id))

    def forget_session(self, session_id: str) -> None:
        for t in self.for_session(session_id):
            self.close(t.info.id)

    def _prune(self, session_id: str) -> None:
        mine = self.for_session(session_id)
        finished = [t for t in mine if not t.running]
        for t in finished[: max(0, len(mine) - MAX_PER_SESSION + 1)]:
            self.close(t.info.id)

    def shutdown(self) -> None:
        for t in list(self._terms.values()):
            t.kill()
        self._terms.clear()


terminals = TerminalManager()
