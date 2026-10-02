"""Typed OpenRouter client (https://openrouter.ai/docs) shared by every feature.

One key buys access to any OpenRouter model. This module only speaks HTTP: it never touches the
database or the job system, so it can be imported from anywhere (agent provider, cloud catalog,
image/voice generation). Billed calls return a :class:`Usage`; hand it to
``openrouter_usage.record(...)`` so the cost shows up in the studio's spend tracking.

- Catalog (public, no key): :func:`list_models`, :func:`list_image_models`, :func:`image_model_endpoints`
- Account: :func:`key_info` (inference key), :func:`credits` (management key), :func:`generation`
- Chat: :func:`stream_chat` (SSE chunks), :func:`chat` (one-shot)
- Media (blocking, for job threads): :func:`generate_image`, :func:`speech`, :func:`transcribe`

Errors are raised as :class:`OpenRouterError` with a user-facing message ("OpenRouter: out of credits…").
Keys are never logged or included in error messages.
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from . import config, settings
from .localhttp import tls

BASE_URL = os.environ.get("STUDIO_OPENROUTER_URL", "https://openrouter.ai/api/v1").rstrip("/")
CREDITS_URL = "https://openrouter.ai/settings/credits"
KEYS_URL = "https://openrouter.ai/settings/keys"
# App attribution headers (https://openrouter.ai/docs/app-attribution)
_APP_HEADERS = {"HTTP-Referer": f"http://{config.HOST}:{config.PORT}", "X-OpenRouter-Title": "Grom AI Studio"}
_TIMEOUT = httpx.Timeout(30, read=600)


class OpenRouterError(RuntimeError):
    """A failed OpenRouter call; ``str(exc)`` is safe to show to the user."""

    def __init__(self, message: str, status: int = 502, error_type: str | None = None,
                 retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.error_type = error_type
        self.retry_after = retry_after


@dataclass(frozen=True)
class Usage:
    """What one request cost. ``cost`` is USD as billed by OpenRouter (None when not reported)."""

    cost: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    generation_id: str | None = None
    cached_tokens: int | None = None  # prompt tokens read from the provider's prompt cache (billed at a discount)

    @staticmethod
    def from_json(usage: dict[str, Any] | None, generation_id: str | None) -> Usage:
        u = usage or {}
        cost = u.get("cost")
        details = u.get("prompt_tokens_details") or {}
        cached = details.get("cached_tokens") if isinstance(details, dict) else None
        return Usage(cost=float(cost) if isinstance(cost, (int, float)) else None,
                     prompt_tokens=u.get("prompt_tokens", u.get("input_tokens")),
                     completion_tokens=u.get("completion_tokens", u.get("output_tokens")),
                     generation_id=generation_id, cached_tokens=cached if isinstance(cached, int) else None)


# ------------------------------ plumbing ------------------------------


def inference_key() -> str:
    key = settings.load().openrouter_api_key
    if not key:
        raise OpenRouterError("No OpenRouter API key configured — add one in Settings → Providers", 401,
                              "authentication")
    return key


def headers(api_key: str | None) -> dict[str, str]:
    h = dict(_APP_HEADERS)
    if api_key:
        h["Authorization"] = f"Bearer {api_key}"
    return h


def _retry_after(value: str | None) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None


def error_from(status: int, body: Any, retry_after: float | None = None) -> OpenRouterError:
    """Map an OpenRouter error body (HTTP or mid-stream ``error`` chunk) to a clear message."""
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        detail = str(err.get("message") or "").strip()
        meta = err.get("metadata") if isinstance(err.get("metadata"), dict) else {}
    else:
        detail = (body if isinstance(body, str) else json.dumps(body))[:300].strip() if body else ""
        meta = {}
    etype = meta.get("error_type")
    source = meta.get("limit_source")
    wait = f" Retry in {retry_after:.0f}s." if retry_after else ""
    if status == 401 or etype == "authentication":
        msg = f"OpenRouter: the API key was rejected — check it in Settings → Providers ({detail or 'unauthorized'})"
    elif status == 402 or etype == "payment_required":
        if source == "openrouter_in_flight_budget":
            msg = f"OpenRouter: too much spend is in flight right now.{wait or ' Retry shortly.'}"
        elif source == "openrouter_key_limit":
            msg = f"OpenRouter: this API key's credit limit is used up — raise it at {KEYS_URL}"
        else:
            msg = f"OpenRouter: out of credits — add credits at {CREDITS_URL}"
    elif status == 403:
        msg = f"OpenRouter: request blocked ({detail or etype or 'forbidden'})"
    elif status == 404:
        msg = f"OpenRouter: not found ({detail or 'unknown model'})"
    elif status == 408:
        msg = "OpenRouter: the request timed out"
    elif status == 429:
        msg = f"OpenRouter: rate limited ({detail or 'too many requests'}).{wait or ' Try again shortly or pick another model.'}"
    elif status in (502, 503):
        msg = f"OpenRouter: no provider could serve this request right now ({detail or etype or status})"
    else:
        msg = f"OpenRouter error {status}: {detail or etype or 'request failed'}"
    return OpenRouterError(msg, status, etype, retry_after)


def _raise_for(r: httpx.Response) -> None:
    if r.status_code < 400:
        return
    try:
        body: Any = r.json()
    except ValueError:
        body = r.text
    raise error_from(r.status_code, body, _retry_after(r.headers.get("retry-after")))


def _unreachable(exc: httpx.HTTPError) -> OpenRouterError:
    return OpenRouterError(f"OpenRouter is unreachable: {type(exc).__name__}", 503, "network")


def _data(r: httpx.Response, unwrap: bool = True) -> Any:
    _raise_for(r)
    try:
        body = r.json()
        return body["data"] if unwrap else body
    except (ValueError, KeyError, TypeError) as exc:
        raise OpenRouterError(f"OpenRouter returned an unexpected response ({r.status_code})") from exc


async def _get(path: str, api_key: str | None = None, params: dict[str, str] | None = None,
               unwrap: bool = True) -> Any:
    """GET a JSON endpoint; most wrap their payload in ``data`` (``unwrap`` returns it)."""
    try:
        async with httpx.AsyncClient(verify=tls, timeout=30) as client:
            r = await client.get(f"{BASE_URL}{path}", params=params, headers=headers(api_key))
    except httpx.HTTPError as exc:
        raise _unreachable(exc) from exc
    return _data(r, unwrap)


def _post_sync(path: str, api_key: str, payload: dict[str, Any], timeout: float) -> httpx.Response:
    try:
        r = httpx.post(f"{BASE_URL}{path}", json=payload, headers=headers(api_key), timeout=timeout)
    except httpx.HTTPError as exc:
        raise _unreachable(exc) from exc
    _raise_for(r)
    return r


# ------------------------------ catalog ------------------------------


async def list_models(output_modalities: str = "all") -> list[dict[str, Any]]:
    """``GET /models`` — every model with the given output modality ("all", "text", "image", …)."""
    data = await _get("/models", params={"output_modalities": output_modalities})
    return list(data)


async def list_image_models() -> list[dict[str, Any]]:
    """``GET /images/models`` — image models with their typed ``supported_parameters``."""
    return list(await _get("/images/models"))


async def image_model_endpoints(model_id: str) -> list[dict[str, Any]]:
    """Per-provider records (parameters, per-image ``pricing`` lines) for one image model."""
    body = await _get(f"/images/models/{model_id}/endpoints", unwrap=False)  # not wrapped in ``data``
    return list(body.get("endpoints") or []) if isinstance(body, dict) else []


# ------------------------------ account ------------------------------


async def key_info(api_key: str) -> dict[str, Any]:
    """``GET /key`` — usage (total/daily/weekly/monthly) and ``limit_remaining`` of an inference key."""
    return dict(await _get("/key", api_key))


async def credits(management_key: str) -> dict[str, Any]:
    """``GET /credits`` — ``total_credits`` and ``total_usage``; needs a management key."""
    return dict(await _get("/credits", management_key))


def generation(generation_id: str, api_key: str | None = None) -> dict[str, Any] | None:
    """``GET /generation`` — billed stats of one request (``total_cost``…); None while not yet recorded."""
    key = api_key or inference_key()
    try:
        r = httpx.get(f"{BASE_URL}/generation", params={"id": generation_id}, headers=headers(key), timeout=30)
    except httpx.HTTPError as exc:
        raise _unreachable(exc) from exc
    if r.status_code == 404:
        return None
    return dict(_data(r))


# -------------------------------- chat --------------------------------


async def stream_chat(body: dict[str, Any], api_key: str) -> AsyncIterator[dict[str, Any]]:
    """``POST /chat/completions`` with ``stream: true``; yields parsed SSE chunks.

    Keep-alive comments are skipped and mid-stream ``error`` chunks raise :class:`OpenRouterError`.
    The last chunk carries ``usage`` (including ``cost``); each chunk's ``id`` is the generation id.
    """
    try:
        async with httpx.AsyncClient(verify=tls, timeout=_TIMEOUT) as client:
            async with client.stream("POST", f"{BASE_URL}/chat/completions", json={**body, "stream": True},
                                     headers=headers(api_key)) as r:
                if r.status_code >= 400:
                    raw = await r.aread()
                    try:
                        parsed: Any = json.loads(raw)
                    except ValueError:
                        parsed = raw.decode(errors="replace")
                    raise error_from(r.status_code, parsed, _retry_after(r.headers.get("retry-after")))
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue  # blank separators and ": OPENROUTER PROCESSING" keep-alives
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        chunk = json.loads(data)
                    except ValueError:
                        continue
                    if isinstance(chunk.get("error"), dict):
                        code = chunk["error"].get("code")
                        raise error_from(code if isinstance(code, int) else 502, chunk)
                    yield chunk
    except httpx.HTTPError as exc:
        raise _unreachable(exc) from exc


async def chat(body: dict[str, Any], api_key: str) -> tuple[dict[str, Any], Usage]:
    """Non-streaming ``POST /chat/completions``; returns the first choice's message and its usage."""
    try:
        async with httpx.AsyncClient(verify=tls, timeout=_TIMEOUT) as client:
            r = await client.post(f"{BASE_URL}/chat/completions", json={**body, "stream": False},
                                  headers=headers(api_key))
    except httpx.HTTPError as exc:
        raise _unreachable(exc) from exc
    _raise_for(r)
    payload = r.json()
    if isinstance(payload.get("error"), dict):
        raise error_from(int(payload["error"].get("code") or 502), payload)
    choices = payload.get("choices") or [{}]
    return dict(choices[0].get("message") or {}), Usage.from_json(payload.get("usage"), payload.get("id"))


# -------------------------------- media --------------------------------


@dataclass(frozen=True)
class GeneratedImage:
    data: bytes
    media_type: str  # "image/png", "image/jpeg", "image/webp", "image/svg+xml"


@dataclass(frozen=True)
class ImageResult:
    images: list[GeneratedImage]
    usage: Usage


def generate_image(model: str, prompt: str, *, n: int | None = None, size: str | None = None,
                   resolution: str | None = None, aspect_ratio: str | None = None, seed: int | None = None,
                   quality: str | None = None, output_format: str | None = None,
                   input_references: list[str] | None = None, provider: dict[str, Any] | None = None,
                   api_key: str | None = None, timeout: float = 600) -> ImageResult:
    """``POST /images``. ``input_references`` are image URLs or ``data:`` URLs (image-to-image);
    ``provider`` is the routing / ``options`` passthrough object. Check each model's accepted values
    with :func:`list_image_models` / :func:`image_model_endpoints`."""
    payload: dict[str, Any] = {"model": model, "prompt": prompt}
    optional = {"n": n, "size": size, "resolution": resolution, "aspect_ratio": aspect_ratio, "seed": seed,
                "quality": quality, "output_format": output_format, "provider": provider}
    payload.update({k: v for k, v in optional.items() if v is not None})
    if input_references:
        payload["input_references"] = [{"type": "image_url", "image_url": {"url": u}} for u in input_references]
    r = _post_sync("/images", api_key or inference_key(), payload, timeout)
    body = r.json()
    images = [GeneratedImage(base64.b64decode(item["b64_json"]), item.get("media_type") or "image/png")
              for item in body.get("data") or [] if item.get("b64_json")]
    if not images:
        raise OpenRouterError(f"OpenRouter: {model} returned no image")
    return ImageResult(images, Usage.from_json(body.get("usage"), r.headers.get("x-generation-id")))


@dataclass(frozen=True)
class SpeechResult:
    audio: bytes
    media_type: str  # "audio/mpeg" for mp3, "audio/pcm" for pcm
    usage: Usage  # the TTS endpoint reports no cost inline: look it up with generation(usage.generation_id)


def speech(model: str, text: str, *, voice: str | None = None, response_format: str = "mp3",
           speed: float | None = None, provider: dict[str, Any] | None = None, api_key: str | None = None,
           timeout: float = 600) -> SpeechResult:
    """``POST /audio/speech`` — returns raw audio bytes. Omit ``voice`` only for models whose provider
    has a default voice (models list their voices in ``supported_voices``)."""
    payload: dict[str, Any] = {"model": model, "input": text, "response_format": response_format}
    optional = {"voice": voice, "speed": speed, "provider": provider}
    payload.update({k: v for k, v in optional.items() if v is not None})
    r = _post_sync("/audio/speech", api_key or inference_key(), payload, timeout)
    if not r.content:
        raise OpenRouterError(f"OpenRouter: {model} returned no audio")
    return SpeechResult(r.content, r.headers.get("content-type", "audio/mpeg").split(";")[0],
                        Usage(generation_id=r.headers.get("x-generation-id")))


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str | None
    duration_s: float | None
    segments: list[dict[str, Any]] = field(default_factory=list)  # {start, end, text, speaker?}
    usage: Usage = Usage()


def transcribe(model: str, audio: bytes, audio_format: str, *, language: str | None = None,
               api_key: str | None = None, timeout: float = 600) -> Transcript:
    """``POST /audio/transcriptions`` with base64 audio (``audio_format`` e.g. "wav", "mp3", "webm").

    Asks for ``verbose_json`` (language + timestamped segments); models that reject it (e.g.
    gpt-4o-transcribe) are retried with plain ``json``, which returns text only."""
    key = api_key or inference_key()
    payload: dict[str, Any] = {"model": model, "input_audio": {"data": base64.b64encode(audio).decode(),
                                                               "format": audio_format}}
    if language:
        payload["language"] = language
    try:
        r = _post_sync("/audio/transcriptions", key, {**payload, "response_format": "verbose_json",
                                                      "timestamp_granularities": ["segment"]}, timeout)
    except OpenRouterError as exc:
        if exc.status != 400:
            raise
        r = _post_sync("/audio/transcriptions", key, payload, timeout)
    body = r.json()
    duration = body.get("duration")
    return Transcript(
        text=str(body.get("text") or "").strip(),
        language=body.get("language") or language,
        duration_s=float(duration) if isinstance(duration, (int, float)) else None,
        segments=[s for s in body.get("segments") or [] if isinstance(s, dict)],
        usage=Usage.from_json(body.get("usage"), r.headers.get("x-generation-id")),
    )
