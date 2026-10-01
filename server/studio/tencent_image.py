"""Tencent HY-Image 3.5 (cloud only — no open weights) through Tencent Cloud TokenHub.

TokenHub authenticates with a single API key (``Authorization: Bearer <key>``; stored in the
``tencent_api_key`` setting) — no TC3-HMAC SecretId/SecretKey signing. The image endpoint is synchronous: one
POST returns the finished image as a temporary COS URL (valid 12 h), which we download into outputs.
Docs: https://intl.cloud.tencent.com/document/product/1300/83708
"""

from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from . import settings
from .schemas import InstalledModel
from .schemas_image import ImageDefaults, ImageModelProfile, ImageSizeRange

MODEL = "hy-image-v3.5-preview"
PATH = "/v1/wand/hunyuan-image/v35-generation"
# International console keys work on the -intl host, mainland China keys on the other; try both.
HOSTS = ("https://tokenhub-intl.tencentcloudmaas.com", "https://tokenhub.tencentmaas.com")
# `generate_max_pixels` tiers (1K, 1.5K, 2K) — billed the same per image.
PIXEL_TIERS = (1_048_576, 2_359_296, 4_194_304)
MAX_REFERENCES = 5
_TIMEOUT = httpx.Timeout(300.0, connect=15.0)


class TencentError(Exception):
    """User-facing failure of a TokenHub call."""


def profile(m: InstalledModel) -> ImageModelProfile:
    return ImageModelProfile(
        model_id=m.id, family="HY-Image 3.5", engine="Tencent TokenHub", location="cloud",
        modes=["txt2img", "edit"], guidance="none", negative_prompt=False,
        defaults=ImageDefaults(steps=1, guidance=0.0, width=2048, height=2048, strength=0.7),
        size=ImageSizeRange(min=256, max=4096, step=16, max_pixels=PIXEL_TIERS[-1]),
        max_count=4, max_images=MAX_REFERENCES,
        cost="≈ $0.024 per image (international) / ¥0.15 (mainland), billed by Tencent",
        notes=["Runs on Tencent Cloud: your prompt and reference images are sent to Tencent.",
               "Needs a TokenHub API key with postpaid billing enabled for HY-Image (Settings → Tencent key).",
               "The model rewrites prompts itself; there are no step or guidance controls."],
    )


@dataclass(frozen=True)
class TencentImage:
    path: Path
    width: int
    height: int


def _pixel_tier(width: int, height: int) -> int:
    area = width * height
    return next((t for t in PIXEL_TIERS if area <= t), PIXEL_TIERS[-1])


def data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def build_request(prompt: str, width: int, height: int, seed: int, references: list[Path]) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    content += [{"type": "image_url", "image_url": {"url": data_url(p)}} for p in references]
    return {"model": MODEL, "messages": [{"role": "user", "content": content}], "size": f"{width}x{height}",
            "seed": seed, "generate_max_pixels": _pixel_tier(width, height)}


def parse_response(body: dict[str, Any]) -> tuple[str, int | None, int | None]:
    """(image URL, width, height) from a v35-generation response."""
    choices = body.get("choices") or []
    if not choices:
        raise TencentError(f"TokenHub returned no image (request {body.get('request_id', '?')})")
    choice = choices[0]
    if choice.get("finish_reason"):
        raise TencentError(f"HY-Image failed: {choice['finish_reason']} (request {body.get('request_id', '?')})")
    image = (choice.get("delta") or {}).get("image") or {}
    if not image.get("url"):
        raise TencentError(f"TokenHub response has no image URL (request {body.get('request_id', '?')})")
    return image["url"], image.get("width"), image.get("height")


def _error_message(r: httpx.Response) -> str:
    try:
        err = r.json()
        err = err.get("error", err)
        detail = err.get("message") or err.get("code") or r.text
    except ValueError:
        detail = r.text
    hints = {401: "the API key was rejected", 403: "HY-Image is not enabled (enable postpaid billing in the console)",
             422: "the prompt or an input image was blocked by moderation", 429: "too many concurrent requests"}
    return f"Tencent TokenHub: {hints.get(r.status_code, f'HTTP {r.status_code}')} — {str(detail)[:300]}"


class TencentClient:
    def __init__(self) -> None:
        self._host: dict[str, str] = {}  # api key → host that accepted it

    def _key(self) -> str:
        key = settings.load().tencent_api_key
        if not key:
            raise TencentError("Set your Tencent Cloud TokenHub API key in Settings to use HY-Image 3.5.")
        return key

    def _post(self, client: httpx.Client, payload: dict[str, Any]) -> dict[str, Any]:
        key = self._key()
        hosts = [self._host[key]] if key in self._host else list(HOSTS)
        last: httpx.Response | None = None
        for host in hosts:
            r = client.post(host + PATH, json=payload, headers={"Authorization": f"Bearer {key}"})
            if r.status_code == 401 and host != hosts[-1]:
                last = r
                continue  # key belongs to the other region's console
            if r.status_code >= 400:
                raise TencentError(_error_message(r))
            self._host[key] = host
            body: dict[str, Any] = r.json()
            return body
        assert last is not None
        raise TencentError(_error_message(last))

    def generate(self, prompt: str, width: int, height: int, seed: int, references: list[Path],
                 out_stem: Path) -> TencentImage:
        """One image; saved next to ``out_stem`` with the extension of what Tencent returns."""
        with httpx.Client(timeout=_TIMEOUT) as client:
            try:
                body = self._post(client, build_request(prompt, width, height, seed, references))
                url, w, h = parse_response(body)
                img = client.get(url)
                img.raise_for_status()
            except httpx.HTTPError as exc:
                raise TencentError(f"Could not reach Tencent TokenHub: {exc}") from exc
        ext = mimetypes.guess_extension(img.headers.get("content-type", "").split(";")[0]) or ".png"
        path = out_stem.with_suffix(".jpg" if ext in (".jpe", ".jpeg") else ext)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(img.content)
        return TencentImage(path=path, width=int(w or width), height=int(h or height))


client = TencentClient()
