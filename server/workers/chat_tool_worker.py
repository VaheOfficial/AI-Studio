"""One JSON-in/JSON-out call to a generated chat tool, in a fresh process."""
from __future__ import annotations

import contextlib
import io
import json
import sys


class BoundedLog(io.StringIO):
    def write(self, text: str) -> int:
        remaining = max(0, 16000 - self.tell())
        super().write(text[:remaining])
        return len(text)


def main() -> None:
    request = json.loads(sys.stdin.read())
    log = BoundedLog()
    try:
        namespace = {"__name__": "chat_tool"}
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            exec(compile(request["code"], "<chat-tool>", "exec"), namespace)
            value = namespace["execute"](request["args"])
        result = {"ok": True, "value": value, "log": log.getvalue()}
        encoded = json.dumps(result, allow_nan=False)
    except Exception as exc:
        encoded = json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}", "log": log.getvalue()})
    sys.stdout.write(encoded)


if __name__ == "__main__":
    main()
