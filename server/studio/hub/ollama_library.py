"""Ollama library side of the hub: search ollama.com and list a model's tags (grouped by weights digest) with
their download sizes. ollama.com has no public JSON API for this, so the public HTML pages are parsed."""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx

from .. import catalog, db
from ..schemas import InstalledModel
from ..schemas_hub import HubRepo, HubSearchResult, HubVariant
from . import variants
from .cache import cached
from .huggingface import HubError

BASE = "https://ollama.com"
_TTL_S = 600
_HEADERS = {"User-Agent": "AI-Studio (local model hub)"}
_CAPABILITIES = ("tools", "thinking", "vision", "embedding", "audio", "cloud")
_ITEM = re.compile(r'<li\s[^>]*>\s*<a href="/(?:library/)?(?P<name>[\w.-]+(?:/[\w.-]+)?)"(?P<body>.*?)</li>', re.S)
_SPAN = re.compile(r"<span[^>]*>\s*([^<]+?)\s*</span>")
_SIZE_TAG = re.compile(r"^\d+(?:\.\d+)?[bmk]$|^e\d+b$|^\d+x\d+b$")  # lowercase: "8b", "e4b"; pulls are "2.7M"
_TAG_QUANT = re.compile(r"(?:^|-)(q\d_k_[sml]|q\d_k|q\d_[01]|iq\d_\w+|fp16|bf16|mxfp4)(?:$|-)", re.I)
_UNITS = {"KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12}


def _get(path: str) -> str:
    try:
        r = httpx.get(f"{BASE}{path}", timeout=15, headers=_HEADERS, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise HubError(f"Could not reach ollama.com: {exc}") from exc
    if r.status_code == 404:
        raise HubError(f"{path} not found on ollama.com", 404)
    if r.status_code != 200:
        raise HubError(f"ollama.com answered {r.status_code} for {path}")
    return r.text


def _count(text: str) -> int | None:
    m = re.fullmatch(r"([\d.,]+)\s*([KMB]?)", text.strip())
    if not m:
        return None
    return int(float(m.group(1).replace(",", "")) * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[m.group(2)])


def _parse_item(name: str, body: str) -> HubSearchResult:
    desc = re.search(r"<p[^>]*>\s*([^<]+?)\s*</p>", body)
    spans = [html.unescape(s) for s in _SPAN.findall(body)]
    caps = [s for s in spans if s in _CAPABILITIES]
    sizes = [s for s in spans if _SIZE_TAG.match(s)]
    pulls = re.search(r">\s*([\d.,]+[KMB]?)\s*</span>\s*<span[^>]*>\s*(?:&nbsp;)?\s*Pulls", body)
    updated = re.search(r'title="([A-Z][a-z]{2} \d{1,2}, \d{4} \d{1,2}:\d{2} [AP]M) UTC"', body)
    author, _, short = name.rpartition("/")
    return HubSearchResult(
        id=name, source="ollama", name=short, author=author or "ollama", kind="text", task="text-generation",
        downloads=_count(pulls.group(1)) if pulls else None,
        updated_at=datetime.strptime(updated.group(1), "%b %d, %Y %I:%M %p").replace(tzinfo=timezone.utc).isoformat()
        if updated else None,
        gated=False, formats=["ollama"], tags=caps + sizes,
        description=html.unescape(desc.group(1)) if desc else None,
    )


def search(query: str) -> list[HubSearchResult]:
    def fetch() -> list[HubSearchResult]:
        page = _get(f"/search?{urlencode({'q': query})}" if query else "/search")
        return [_parse_item(m.group("name"), m.group("body")) for m in _ITEM.finditer(page)]
    return cached(("ollama-search", query), _TTL_S, fetch)


def _path(name: str) -> str:
    return f"/{name}" if "/" in name else f"/library/{name}"


def _tag_rows(name: str) -> list[dict[str, str]]:
    page = _get(f"{_path(name)}/tags")
    rows = []
    for chunk in page.split('<div class="group px-4 py-3">')[1:]:
        tag = re.search(r'href="/(?:library/)?[\w./-]+:([\w.-]+)"', chunk)
        digest = re.search(r'font-mono[^>]*>\s*([0-9a-f]{12})', chunk)
        cols = re.findall(r'col-span-2 text-neutral-500 text-\[13px\][^>]*>\s*([^<]+?)\s*<', chunk)
        if tag and digest and cols:
            rows.append({"tag": tag.group(1), "digest": digest.group(1), "size": cols[0],
                         "context": cols[1] if len(cols) > 1 else "", "input": cols[2] if len(cols) > 2 else ""})
    return rows


def _bytes(size: str) -> int:
    m = re.fullmatch(r"([\d.]+)\s*([KMGT]B)", size.strip())
    return int(float(m.group(1)) * _UNITS[m.group(2)]) if m else 0


def _installed_tag(full: str, installed: list[InstalledModel]) -> str | None:
    return next((m.id for m in installed if m.runtime == "ollama" and m.path == f"ollama://{full}"), None)


def repo(name: str) -> HubRepo:
    def fetch() -> tuple[HubSearchResult, list[dict[str, str]]]:
        page = _get(_path(name))
        desc = re.search(r'<meta name="description" content="([^"]*)"', page)
        caps = sorted({c for c in re.findall(r"<span[^>]*>\s*(\w+)\s*</span>", page) if c in _CAPABILITIES})
        summary = HubSearchResult(id=name, source="ollama", name=name.rpartition("/")[2],
                                  author=name.rpartition("/")[0] or "ollama", kind="text", task="text-generation",
                                  gated=False, formats=["ollama"], tags=caps,
                                  description=html.unescape(desc.group(1)) if desc else None)
        return summary, _tag_rows(name)
    head, rows = cached(("ollama-repo", name), _TTL_S, fetch)

    by_digest: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_digest.setdefault(row["digest"], []).append(row)
    installed = db.list_installed()
    embedding = "embedding" in head.tags
    out: list[HubVariant] = []
    latest: HubVariant | None = None
    for group in by_digest.values():
        tags = sorted((r["tag"] for r in group), key=lambda t: (t == "latest", len(t)))
        primary = tags[0]
        quant = next((m.group(1).upper() for t in tags if (m := _TAG_QUANT.search(t))), None)
        size = _bytes(group[0]["size"])
        full = f"{name}:{primary}"
        draft = variants.Draft(id=primary, label=primary, format="ollama", kind="text", files=[], size=size,
                               runtimes=["ollama"], quant=quant)
        vram = variants.vram_gb(draft)
        notes = [f"Same weights as {', '.join(tags[1:])}."] if len(tags) > 1 else []
        if group[0]["context"]:
            notes.append(f"{group[0]['context']} context · {group[0]['input']} input.")
        if embedding:
            notes.append("Embedding model: it can't chat.")
        variant = HubVariant(
            id=primary, ref=f"ollama:{full}", label=primary, format="ollama", quant=quant, kind="text", files=[],
            size_bytes=size, vram_gb=vram, fit=catalog.compute_fit(vram, "ollama"), runtimes=["ollama"],
            note=" ".join(notes) or None,
            installed_id=next(filter(None, (_installed_tag(f"{name}:{t}", installed) for t in tags)), None),
        )
        out.append(variant)
        if "latest" in tags:
            latest = variant
    out.sort(key=lambda v: v.size_bytes)
    if latest and latest.fit == "yes":
        latest.recommended = True  # Ollama's own default pick for this model
    return HubRepo(
        id=name, source="ollama", name=head.name, author=head.author, kind="text", task="text-generation",
        gated=False, base_models=[], tags=head.tags, summary=head.description, url=f"{BASE}{_path(name)}",
        files=[], variants=out, related=[],
    )
