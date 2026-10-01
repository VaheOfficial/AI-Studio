"""Web research without API keys: search (DuckDuckGo), readable page text (trafilatura, or the
agent's browser for pages that need JavaScript), and passage ranking so the model reads the few paragraphs that
answer the question instead of whole pages - the retrieve-then-cite pipeline answer engines use."""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import httpx
import lxml.html
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
class Result:
    title: str
    url: str
    snippet: str


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


def _cls(name: str) -> str:
    return f"contains(concat(' ', normalize-space(@class), ' '), ' {name} ')"


def _text(el: lxml.html.HtmlElement | None) -> str:
    return " ".join(el.text_content().split()) if el is not None else ""


def _ddg(html: str) -> list[Result]:
    doc = lxml.html.fromstring(html)
    out = []
    for res in doc.xpath(f"//div[{_cls('result')}][not({_cls('result--ad')})]"):
        link = next(iter(res.xpath(f".//a[{_cls('result__a')}]")), None)
        if link is None:
            continue
        href = link.get("href") or ""
        if "uddg=" in href:  # redirect links carry the real URL
            href = parse_qs(urlparse(href).query).get("uddg", [href])[0]
        snippet = next(iter(res.xpath(f".//*[{_cls('result__snippet')}]")), None)
        out.append(Result(_text(link), href, _text(snippet)))
    return out


def _ddg_lite(html: str) -> list[Result]:
    doc = lxml.html.fromstring(html)
    links = doc.xpath(f"//a[{_cls('result-link')}]")
    snippets = doc.xpath(f"//td[{_cls('result-snippet')}]")
    return [Result(_text(a), a.get("href") or "", _text(snippets[i]) if i < len(snippets) else "")
            for i, a in enumerate(links)]


# DuckDuckGo is the only engine: others serve captchas or junk to programs. It answers bursts with HTTP 202 (rate
# limited), so its requests go one at a time, a second apart; a rate-limited search waits with growing pauses
# (the turn can still be stopped) and alternates between the html and lite endpoints. Results are cached an hour.
_DDG_GAP_S = 1.0
RETRY_WAITS_S = (15, 30, 60, 120)
_ENDPOINTS = (("https://html.duckduckgo.com/html/", _ddg), ("https://lite.duckduckgo.com/lite/", _ddg_lite))
_ddg_lock = asyncio.Lock()
_ddg_last = 0.0
_results: dict[str, tuple[float, list[Result]]] = {}


async def _ddg_request(client: httpx.AsyncClient, url: str, query: str) -> httpx.Response:
    global _ddg_last
    async with _ddg_lock:
        wait = _ddg_last + _DDG_GAP_S - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            return await client.post(url, data={"q": query})
        finally:
            _ddg_last = time.monotonic()


async def search(query: str, count: int = 8, on_wait: Callable[[int], None] | None = None) -> list[Result]:
    """DuckDuckGo results for ``query``. ``on_wait(seconds)`` is called before each pause while rate limited."""
    key = " ".join(query.lower().split())
    cached = _results.get(key)
    if cached and time.monotonic() - cached[0] < _CACHE_TTL_S:
        return cached[1][:count]
    status = 0
    async with httpx.AsyncClient(headers=_HEADERS, timeout=15, follow_redirects=True) as client:
        for attempt in range(len(RETRY_WAITS_S) + 1):
            url, parse = _ENDPOINTS[attempt % len(_ENDPOINTS)]
            try:
                r = await _ddg_request(client, url, query)
                status = r.status_code
                results = parse(r.text) if status == 200 else []
            except (httpx.HTTPError, ValueError) as exc:
                raise ToolFailure(f"Web search failed: {exc}") from exc
            results = [x for x in results if x.url.startswith("http")]
            if status == 200:  # a real answer, even if empty
                seen: set[str] = set()
                unique = [x for x in results if not (x.url in seen or seen.add(x.url))]
                _results[key] = (time.monotonic(), unique)
                return unique[:count]
            if attempt < len(RETRY_WAITS_S):
                if on_wait:
                    on_wait(RETRY_WAITS_S[attempt])
                await asyncio.sleep(RETRY_WAITS_S[attempt])
    raise ToolFailure(f"DuckDuckGo is still rate limiting (HTTP {status}) after waiting "
                      f"{sum(RETRY_WAITS_S)} s. Try again in a few minutes, or search in the browser "
                      "(browser_navigate to a search page) where the user can take over.")


def _cache_path(url: str):
    return PAGE_CACHE / f"{hashlib.sha1(url.encode()).hexdigest()[:20]}.txt"


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
