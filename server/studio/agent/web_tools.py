"""Agent tools for the web: ``web_search`` (results with snippets), ``fetch_url`` (a page's readable text, or just the
passages that answer a question) and ``research`` (several searches, the top pages read in parallel, the best
passages ranked and numbered for citation). The browser tools stay for pages that need clicking or logging in."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from ..schemas_workspace import SourceItem, SourcesDisplay
from . import web
from .types import ToolContext, ToolFailure, ToolOutcome, ToolSpec

PAGE_CHARS = 8_000  # fetch_url without a question: this much per call, then continue with offset
PASSAGES = 6  # fetch_url with a question
RESEARCH_PAGES = 8
RESEARCH_PASSAGES = 10
_S = {"type": "string"}


def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


SPECS: list[ToolSpec] = [
    ToolSpec("web_search", "Search the web. Returns titles, URLs and snippets; read pages with fetch_url.",
             _obj({"query": _S, "count": {"type": "integer", "minimum": 1, "maximum": 15}}, ["query"])),
    ToolSpec("fetch_url", "Read a web page (or PDF) as clean text. With question, returns only the passages that "
             "answer it; without, the text from offset on.",
             _obj({"url": _S, "question": _S, "offset": {"type": "integer", "minimum": 0}}, ["url"])),
    ToolSpec("research", "Answer a question from the web: runs your 1-4 search queries, reads the top pages in "
             "parallel and returns the most relevant passages numbered [1], [2]... with their sources. Cite them in "
             "your answer as [n](url).",
             _obj({"question": _S, "queries": {"type": "array", "items": _S, "minItems": 1, "maxItems": 4,
                                               "description": "Different phrasings / sub-questions"}},
                  ["question", "queries"])),
]


def _items(rows: list[tuple[str, str, str | None]]) -> list[SourceItem]:
    return [SourceItem(n=i, title=t or u, url=u, snippet=(s or None) and s[:240]) for i, (t, u, s) in
            enumerate(rows, 1)]


def _waiting(ctx: ToolContext, query: str) -> Callable[[int], None]:
    """Show on the call's card that the search is waiting out DuckDuckGo's rate limit."""
    return lambda s: ctx.progress(SourcesDisplay(query=f"{query} - DuckDuckGo is rate limiting, retrying in {s} s",
                                                 items=[]))


async def _web_search(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    results = await web.search(a["query"], int(a.get("count") or 8), _waiting(ctx, a["query"]))
    if not results:
        return ToolOutcome(True, f"No results for {a['query']!r}; try other words.",
                           display=SourcesDisplay(query=a["query"], items=[]))
    lines = [f"[{i}] {r.title}\n    {r.url}\n    {r.snippet}" for i, r in enumerate(results, 1)]
    return ToolOutcome(True, f"{len(results)} results for {a['query']!r}:\n" + "\n".join(lines),
                       display=SourcesDisplay(query=a["query"], items=_items([(r.title, r.url, r.snippet)
                                                                              for r in results])))


async def _fetch_url(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    page = await web.fetch(a["url"], browser_session=ctx.session_id)
    display = SourcesDisplay(query=a.get("question") or page.url, items=_items([(page.title, page.url, None)]))
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


async def _research(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    queries = [q for q in (a["queries"] if isinstance(a["queries"], list) else [a["queries"]]) if str(q).strip()][:4]
    if not queries:
        raise ToolFailure("research needs at least one search query")
    unique = list(dict.fromkeys(" ".join(str(q).lower().split()) for q in queries))
    searched = await asyncio.gather(*(web.search(q, 6, _waiting(ctx, a["question"])) for q in unique),
                                    return_exceptions=True)
    urls: dict[str, web.Result] = {}
    for rank in range(6):  # interleave the queries' results so each query contributes its best pages
        for res in searched:
            if not isinstance(res, BaseException) and rank < len(res):
                urls.setdefault(res[rank].url, res[rank])
    if not urls:
        errors = "; ".join(str(r) for r in searched if isinstance(r, BaseException))
        raise ToolFailure(f"The searches found nothing{': ' + errors if errors else ''}")
    picked = list(urls.values())[:RESEARCH_PAGES]
    fetched = await asyncio.gather(*(asyncio.wait_for(web.fetch(r.url), 25) for r in picked), return_exceptions=True)
    pages = [p for p in fetched if isinstance(p, web.Page)]
    failed = len(picked) - len(pages)
    passages = web.rank(" ".join([a["question"], *map(str, queries)]), pages, RESEARCH_PASSAGES, per_page=3)
    if not passages:  # pages unreadable or off-topic: fall back to the search snippets
        rows = [(r.title, r.url, r.snippet) for r in picked]
        return ToolOutcome(True, "No page text could be used; search snippets:\n" + "\n".join(
            f"[{i}] {t} ({u}): {s}" for i, (t, u, s) in enumerate(rows, 1)),
                           display=SourcesDisplay(query=a["question"], items=_items(rows)))
    numbers: dict[str, int] = {}
    for p in passages:
        numbers.setdefault(p.url, len(numbers) + 1)
    by_source = sorted(passages, key=lambda p: numbers[p.url])
    body = "\n\n".join(f"[{numbers[p.url]}] {p.title}\n{p.url}\n{p.text}" for p in by_source)
    titles = {p.url: p.title for p in passages}
    note = f" ({failed} page{'s' if failed != 1 else ''} could not be read)" if failed else ""
    return ToolOutcome(True, f"Read {len(pages)} pages for {a['question']!r}{note}. The most relevant passages, "
                             f"numbered by source - cite as [n](url), and say when they don't answer something:\n\n"
                             f"{body}",
                       display=SourcesDisplay(query=a["question"], items=_items(
                           [(titles[u], u, None) for u in numbers])))


IMPL: dict[str, Callable[[dict[str, Any], ToolContext], Awaitable[ToolOutcome]]] = {
    "web_search": _web_search, "fetch_url": _fetch_url, "research": _research,
}
