"""Reading web pages: a page's readable text (trafilatura, or the agent's browser for pages that need
JavaScript), and passage ranking so the model reads the few paragraphs that answer a question instead of the
whole page. Searching is done in the agent's browser (the browser_* tools): search engines turn plain HTTP
clients away."""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
import time
from collections import Counter
from dataclasses import dataclass

import httpx
import trafilatura

from .. import config
from .types import ToolFailure

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36")
_HEADERS = {"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"}
MAX_PAGE_BYTES = 6 * 2**20
PAGE_CACHE = config.CACHE_DIR / "web"
_CACHE_TTL_S = 3600
_WORD = re.compile(r"\w+", re.UNICODE)
_STOP = set("a an and are as at be by for from has have how i in is it its of on or that the this to was were what "
            "when where which who why will with you your do does did can could should would".split())


@dataclass
class Page:
    url: str
    title: str
    text: str


@dataclass
class Passage:
    url: str
    title: str
    text: str
    score: float


def _cache_path(url: str):
    return PAGE_CACHE / f"{hashlib.sha1(url.encode()).hexdigest()[:20]}.txt"


def main_text(html: str, url: str) -> str:
    """The main content of an HTML page (the article, the documentation, the post) without the navigation, side
    bars and footers around it; empty when the page has no such body (a list of links, an app)."""
    return _extract(html, url)[1]


def _extract(html: str, url: str) -> tuple[str, str]:
    """(title, main text as markdown-ish plain text) of an HTML page."""
    text = trafilatura.extract(html, url=url, output_format="markdown", include_links=False, include_tables=True,
                               favor_recall=True) or ""
    meta = trafilatura.extract_metadata(html, default_url=url)
    title = (meta.title if meta and meta.title else "") or ""
    return title, text.strip()


async def fetch(url: str, *, browser_session: str | None = None) -> Page:
    """Readable text of a page (cached for an hour). Pages that need JavaScript are rendered in the agent's
    browser when ``browser_session`` is given."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    cached = _cache_path(url)
    if cached.is_file() and time.time() - cached.stat().st_mtime < _CACHE_TTL_S:
        title, _, text = cached.read_text(encoding="utf-8").partition("\n")
        return Page(url, title, text)
    title, text, error = "", "", ""
    try:
        async with httpx.AsyncClient(headers=_HEADERS, timeout=httpx.Timeout(20, read=30), follow_redirects=True) as c:
            async with c.stream("GET", url) as r:
                body = bytearray()
                async for chunk in r.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_PAGE_BYTES:
                        break
                kind = r.headers.get("content-type", "")
                status = r.status_code
                final = str(r.url)
        if status >= 400:
            error = f"HTTP {status}"
        elif "pdf" in kind or final.lower().endswith(".pdf"):
            text = await asyncio.to_thread(_pdf_text, bytes(body))
            title = final.rsplit("/", 1)[-1]
        elif "html" in kind or "xml" in kind or not kind:
            title, text = await asyncio.to_thread(_extract, body.decode(r.encoding or "utf-8", errors="replace"), final)
        elif kind.startswith("text/") or "json" in kind:
            text = body.decode(r.encoding or "utf-8", errors="replace")
        else:
            error = f"not a text page ({kind.split(';')[0]})"
        url = final
    except httpx.HTTPError as exc:
        error = f"{type(exc).__name__}: {exc}"
    if len(text) < 200 and browser_session and not error.startswith("not a text"):
        rendered = await _render(url, browser_session)  # probably built by JavaScript
        if rendered and len(rendered.text) > len(text):
            title, text, error = rendered.title or title, rendered.text, ""
    if not text:
        raise ToolFailure(f"Could not read {url}: {error or 'no readable text on the page'}")
    PAGE_CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_text(f"{title}\n{text}", encoding="utf-8")
    return Page(url, title or url, text)


async def _render(url: str, session_id: str) -> Page | None:
    from ..workspace.browser import browser
    from ..workspace.state import WorkspaceError

    try:
        await browser.navigate(session_id, url, agent=True)
        final, title, content, _ = await browser.read(session_id, "text")
    except WorkspaceError:
        return None
    return Page(final, title, content)


def _pdf_text(data: bytes) -> str:
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages[:60]).strip()


# ------------------------------- ranking -------------------------------


def chunks(text: str, size: int = 900, overlap: int = 150) -> list[str]:
    """Paragraph-aligned pieces of about ``size`` chars."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out: list[str] = []
    cur = ""
    for p in paras:
        while len(p) > size:  # a giant paragraph: hard-split it
            head, p = p[:size], p[size - overlap:]
            if cur:
                out.append(cur)
                cur = ""
            out.append(head)
        if len(cur) + len(p) + 2 > size and cur:
            out.append(cur)
            cur = cur[-overlap:] + "\n\n" + p if overlap else p
        else:
            cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        out.append(cur)
    return out


def _terms(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 1]


def rank(query: str, pages: list[Page], top: int, per_page: int = 3) -> list[Passage]:
    """BM25 over the pages' chunks; at most ``per_page`` passages from one page so several sources are heard."""
    pieces = [(p, c) for p in pages for c in chunks(p.text)]
    if not pieces:
        return []
    docs = [_terms(c) for _, c in pieces]
    avg = sum(len(d) for d in docs) / len(docs) or 1
    df: Counter[str] = Counter(t for d in docs for t in set(d))
    q = _terms(query)
    distinct = set(q)
    floor = 0.3 if len(distinct) >= 3 else 0.0  # share of the question's terms a passage must contain
    n = len(docs)
    scored = []
    for (page, text), terms in zip(pieces, docs, strict=True):
        tf = Counter(terms)
        if floor and len(distinct & tf.keys()) < floor * len(distinct):
            continue  # off-topic: shares a word or two with the question, not the subject
        score = 0.0
        for t in q:
            if t in tf:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                score += idf * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * len(terms) / avg))
        scored.append(Passage(page.url, page.title, text, score))
    scored.sort(key=lambda p: p.score, reverse=True)
    picked: list[Passage] = []
    used: Counter[str] = Counter()
    for p in scored:
        if p.score <= 0 or used[p.url] >= per_page:
            continue
        picked.append(p)
        used[p.url] += 1
        if len(picked) >= top:
            break
    return picked
