"""The agent's tool for reading the web: ``fetch_url`` (a page's readable text, or just the passages that answer a
question). Looking things up, and pages that need clicking or logging in, are the browser tools' job."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from ..schemas_workspace import SourceItem, SourcesDisplay
from . import web
from .types import ToolContext, ToolFailure, ToolOutcome, ToolSpec

PAGE_CHARS = 8_000  # fetch_url without a question: this much per call, then continue with offset
PASSAGES = 6  # fetch_url with a question
_S = {"type": "string"}


def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


SPECS: list[ToolSpec] = [
    ToolSpec("fetch_url", "Read a web page (or PDF) as clean text. With question, returns only the passages that "
             "answer it; without, the text from offset on.",
             _obj({"url": _S, "question": _S, "offset": {"type": "integer", "minimum": 0}}, ["url"])),
]


async def _fetch_url(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    page = await web.fetch(a["url"], browser_session=ctx.session_id)
    display = SourcesDisplay(query=a.get("question") or page.url,
                             items=[SourceItem(n=1, title=page.title or page.url, url=page.url, snippet=None)])
    if a.get("question"):
        passages = web.rank(a["question"], [page], PASSAGES, per_page=PASSAGES)
        if passages:
            body = "\n\n---\n\n".join(p.text for p in passages)
            return ToolOutcome(True, f"{page.title}\n{page.url}\nThe {len(passages)} passages most relevant to "
                                     f"{a['question']!r} (of {len(page.text):,} chars):\n\n{body}", display=display)
    start = int(a.get("offset") or 0)
    chunk = page.text[start:start + PAGE_CHARS]
    if not chunk:
        raise ToolFailure(f"offset {start} is past the end of the page ({len(page.text):,} chars)")
    end = start + len(chunk)
    more = (f"\n\n[... {len(page.text) - end:,} more chars: call fetch_url with offset={end}, or pass a question to "
            "get just the relevant passages]") if end < len(page.text) else ""
    return ToolOutcome(True, f"{page.title}\n{page.url}\n\n{chunk}{more}", display=display)


IMPL: dict[str, Callable[[dict[str, Any], ToolContext], Awaitable[ToolOutcome]]] = {"fetch_url": _fetch_url}
