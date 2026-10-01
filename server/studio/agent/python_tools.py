"""The agent's Python: ``run_python`` (a persistent session per chat - analysis, charts, tables, documents),
``reset_python``, and ``read_skill`` (how-to guides for Word, Excel, PowerPoint, PDF and charts in ``skills/``)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from ..jobs import jobs
from ..runtimes import envs
from ..schemas_workspace import FileArtifact, PythonDisplay, TableData
from . import pykernel
from .types import ToolContext, ToolFailure, ToolOutcome, ToolSpec

SKILLS_DIR = Path(__file__).parent / "skills"
SKILLS = {p.stem: p for p in sorted(SKILLS_DIR.glob("*.md"))}
MAX_TIMEOUT_S = 600
_INSTALL_WAIT_S = 20 * 60

SPECS: list[ToolSpec] = [
    ToolSpec(
        "run_python",
        "Run Python code in a persistent session for this chat (variables stay between calls, like a notebook). Use "
        "it for calculations, data analysis (pandas, numpy, scipy, sympy), charts (matplotlib: open figures are "
        "shown to the user automatically - don't call plt.show or savefig for display) and for making files: Word "
        "(python-docx), Excel (openpyxl), PowerPoint (python-pptx), PDF (reportlab, pypdf, pdfplumber). The working "
        "directory is the chat's workspace folder (or a scratch folder); files you create there are offered to the "
        "user as downloads. The value of the last line is returned (a DataFrame is shown as a table). No input(); "
        "internet access works (requests). Read the matching skill with read_skill before making a document.",
        {"type": "object", "properties": {
            "code": {"type": "string"},
            "timeout_s": {"type": "integer", "description": f"Default 120, at most {MAX_TIMEOUT_S}"},
        }, "required": ["code"]},
        needs_approval=True,
    ),
    ToolSpec("reset_python", "Restart this chat's Python session (clears all variables).",
             {"type": "object", "properties": {}}),
    ToolSpec(
        "read_skill",
        "Read a how-to guide before a task it covers: " + ", ".join(SKILLS) + ". Each explains the library to use, "
        "conventions and quality checks.",
        {"type": "object", "properties": {"name": {"type": "string", "enum": list(SKILLS)}}, "required": ["name"]},
    ),
]


async def _ensure_env(ctx: ToolContext, code: str) -> None:
    """First use: install the Python tools environment (a background job), showing progress on the call."""
    if envs.is_ready(pykernel.ENV):
        return
    job = envs.ensure_env_job(pykernel.ENV, "python")
    if job is None:
        return
    waited = 0.0
    while waited < _INSTALL_WAIT_S:
        current = jobs.get(job.id)
        if current is None or current.status in ("done", "error", "cancelled"):
            break
        pct = f" {current.progress * 100:.0f}%" if current.progress and current.progress > 0 else ""
        ctx.progress(PythonDisplay(code=code, output=f"Installing the Python tools environment (one time, a few "
                                                     f"hundred MB){pct}…"))
        await asyncio.sleep(2)
        waited += 2
    if not envs.is_ready(pykernel.ENV):
        current = jobs.get(job.id)
        raise ToolFailure("The Python tools environment could not be installed"
                          + (f": {current.error}" if current and current.error else "; see Models → Runtimes"))


async def _run_python(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    code = a["code"]
    timeout = max(5, min(int(a.get("timeout_s") or 120), MAX_TIMEOUT_S))
    await _ensure_env(ctx, code)
    ctx.progress(PythonDisplay(code=code, output="Running…"))
    try:
        r = await pykernel.run(ctx.session_id, code, timeout)
    except pykernel.KernelError as exc:
        return ToolOutcome(False, f"Error: {exc}", display=PythonDisplay(code=code, error=str(exc)))
    images = [p for p in (Path(x) for x in r.images) if p.exists()]
    image_urls = [u for u in (pykernel.file_url(ctx.session_id, p) for p in images) if u]
    files = []
    for f in (Path(x) for x in r.files):
        if f.exists() and "_charts" not in f.parts:
            files.append(FileArtifact(name=f.name, path=str(f), url=pykernel.file_url(ctx.session_id, f),
                                      size=f.stat().st_size))
    table = TableData(**r.table) if r.table else None
    display = PythonDisplay(code=code, output=r.output, error=r.error, images=image_urls, table=table, files=files)
    parts = []
    if r.output:
        parts.append(r.output)
    if r.error:
        parts.append(f"Error:\n{r.error}")
    if images:
        parts.append(f"{len(images)} chart{'s' if len(images) != 1 else ''} shown to the user"
                     + (" (attached below)" if ctx.vision else ""))
    if files:
        parts.append("Files created or changed (offered to the user as downloads): "
                     + ", ".join(f"{f.name} ({f.path})" for f in files))
    if not parts:
        parts.append("(no output)")
    return ToolOutcome(r.error is None, "\n".join(parts), display=display, images=images[:3] if ctx.vision else [])


async def _reset_python(_a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    had = pykernel.reset(ctx.session_id)
    return ToolOutcome(True, "Python session restarted" if had else "No Python session was running")


async def _read_skill(a: dict[str, Any], _ctx: ToolContext) -> ToolOutcome:
    path = SKILLS.get(a["name"])
    if path is None:
        raise ToolFailure(f"No skill '{a['name']}'. Available: {', '.join(SKILLS)}")
    return ToolOutcome(True, path.read_text(encoding="utf-8"))


IMPL: dict[str, Callable[[dict[str, Any], ToolContext], Awaitable[ToolOutcome]]] = {
    "run_python": _run_python, "reset_python": _reset_python, "read_skill": _read_skill,
}
