"""A persistent Python session for the agent's ``run_python`` tool (one process per chat, started by
``studio/agent/pykernel.py`` in the ``python`` env).

Protocol: one JSON request per stdin line ``{"code", "chart_dir"}``; the reply is one line on stdout starting with
``\\x1e`` (so a crash's traceback on the same stream can't be mistaken for it). Variables persist between requests
like a notebook. The value of a final expression is returned (a pandas DataFrame also as a table), open matplotlib
figures are saved as PNGs, and files created or changed under the working directory are listed.
"""

from __future__ import annotations

import ast
import builtins
import contextlib
import io
import json
import os
import sys
import traceback
import uuid

os.environ.setdefault("MPLBACKEND", "Agg")
PROTOCOL = sys.stdout
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".ruff_cache", "_charts"}
MAX_FILES = 3000
MAX_OUTPUT = 20_000
TABLE_ROWS = 50


def _no_input(*_args: object) -> str:
    raise RuntimeError("input() is not available here: pass values in the code instead")


builtins.input = _no_input
namespace: dict[str, object] = {"__name__": "__main__"}


def snapshot(root: str) -> dict[str, tuple[int, float]]:
    seen: dict[str, tuple[int, float]] = {}
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in files:
            path = os.path.join(base, f)
            try:
                st = os.stat(path)
            except OSError:
                continue
            seen[os.path.abspath(path)] = (st.st_size, st.st_mtime)
            if len(seen) >= MAX_FILES:
                return seen
    return seen


def table(value: object) -> dict[str, object] | None:
    """A DataFrame (or Series) as a small table for the chat."""
    pd = sys.modules.get("pandas")
    if pd is None:
        return None
    if isinstance(value, pd.Series):
        value = value.to_frame()
    if not isinstance(value, pd.DataFrame):
        return None
    head = value.head(TABLE_ROWS)
    index = not isinstance(head.index, pd.RangeIndex)
    columns = ([str(head.index.name or "")] if index else []) + [str(c) for c in head.columns]
    rows = [([str(i)] if index else []) + ["" if v is None else str(v) for v in row]
            for i, row in zip(head.index, head.itertuples(index=False))]
    return {"columns": columns, "rows": rows, "total_rows": int(len(value))}


def charts(chart_dir: str) -> list[str]:
    plt = sys.modules.get("matplotlib.pyplot")
    if plt is None:
        return []
    saved = []
    for num in plt.get_fignums():
        os.makedirs(chart_dir, exist_ok=True)
        path = os.path.join(chart_dir, f"{uuid.uuid4().hex[:10]}.png")
        plt.figure(num).savefig(path, dpi=110, bbox_inches="tight", facecolor="white")
        saved.append(path)
    plt.close("all")
    return saved


def run(code: str, chart_dir: str) -> dict[str, object]:
    before = snapshot(".")
    buf = io.StringIO()
    result: str | None = None
    tab: dict[str, object] | None = None
    error: str | None = None
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            tree = ast.parse(code, mode="exec")
            last = tree.body.pop() if tree.body and isinstance(tree.body[-1], ast.Expr) else None
            exec(compile(tree, "<python>", "exec"), namespace)
            if last is not None:
                value = eval(compile(ast.Expression(last.value), "<python>", "eval"), namespace)
                if type(value).__module__.startswith("matplotlib"):
                    value = None  # ax.set_title(...) and friends: the chart itself is what's shown
                if value is not None:
                    tab = table(value)
                    result = repr(value) if tab is None else str(value)
        except BaseException:  # noqa: BLE001 - user code: report everything, including SystemExit
            lines = traceback.format_exc().splitlines()
            # drop the kernel's own frames: the user's code starts at File "<python>"
            start = next((i for i, line in enumerate(lines) if '"<python>"' in line), 1)
            error = "\n".join(lines[:1] + lines[start:])
    output = buf.getvalue()
    if result is not None:
        output = (output + ("\n" if output and not output.endswith("\n") else "") + result) if output else result
    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT // 2] + f"\n... [{len(output) - MAX_OUTPUT} characters cut] ...\n" + output[-MAX_OUTPUT // 2:]
    images = charts(chart_dir)
    after = snapshot(".")
    changed = sorted(p for p, sig in after.items() if before.get(p) != sig)
    return {"output": output, "error": error, "images": images, "table": tab, "files": changed[:50]}


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        req = json.loads(line)
        try:
            reply = run(req["code"], req["chart_dir"])
        except BaseException as exc:  # noqa: BLE001 - never let the session die on one request
            reply = {"output": "", "error": f"Kernel error: {exc!r}", "images": [], "table": None, "files": []}
        PROTOCOL.write("\x1e" + json.dumps(reply) + "\n")
        PROTOCOL.flush()


if __name__ == "__main__":
    main()
