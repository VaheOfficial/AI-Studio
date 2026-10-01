"""Images the model looks at: pictures the user attaches, browser screenshots and generated images. They are
downscaled before they go to a model (a 4K screenshot costs thousands of tokens and says no more than 1280 px) and
cached per file, so re-sending the same image on every step stays cheap."""

from __future__ import annotations

import base64
import io
import uuid
from functools import lru_cache
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .. import config
from .types import ToolFailure

MAX_SIDE = 1280
MAX_UPLOAD_BYTES = 20 * 2**20
EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
CHAT_DIR = config.OUTPUTS_DIR / "chat"
_PUBLIC = "/files/"


def to_path(ref: str, workspace_root: Path | None = None) -> Path:
    """A local image file from a studio URL (``/files/...`` or ``http://127.0.0.1:8765/files/...``), an absolute
    path, or a path relative to the chat's workspace folder."""
    ref = ref.strip().strip('"')
    for prefix in (f"http://{config.HOST}:{config.PORT}", f"http://localhost:{config.PORT}"):
        ref = ref.removeprefix(prefix)
    if ref.startswith(_PUBLIC):
        path = (config.DATA_DIR / ref.removeprefix(_PUBLIC).split("?", 1)[0]).resolve()
        if public_url(path) is None:
            raise ToolFailure(f"Not a studio file: {ref}")
    else:
        path = Path(ref)
        if not path.is_absolute():
            if workspace_root is None:
                raise ToolFailure(f"'{ref}' is a relative path but this chat has no workspace folder")
            path = workspace_root / path
        path = path.resolve()
    if not path.is_file():
        raise ToolFailure(f"Image not found: {ref}")
    if path.suffix.lower() not in EXTENSIONS:
        raise ToolFailure(f"Not an image file: {path.name}")
    return path


def public_url(path: Path) -> str | None:
    """The ``/files/...`` URL of a file in a public data folder, if it is in one."""
    try:
        rel = path.resolve().relative_to(config.DATA_DIR)
    except ValueError:
        return None
    return _PUBLIC + rel.as_posix() if rel.parts and rel.parts[0] in config.PUBLIC_SUBDIRS else None


def encode(path: Path) -> tuple[str, str]:
    """(mime type, base64) of the image scaled to fit ``MAX_SIDE``."""
    stat = path.stat()
    return _encode(str(path), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=64)
def _encode(path: str, _mtime: int, _size: int) -> tuple[str, str]:
    try:
        with Image.open(path) as im:
            im.load()
            frame = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
    except (OSError, UnidentifiedImageError) as exc:
        raise ToolFailure(f"Could not read the image {Path(path).name}: {exc}") from exc
    frame.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    if frame.mode == "RGBA" and frame.getextrema()[3][0] < 255:  # real transparency: keep PNG
        frame.save(buf, "PNG", optimize=True)
        mime = "image/png"
    else:
        frame.convert("RGB").save(buf, "JPEG", quality=85)
        mime = "image/jpeg"
    return mime, base64.b64encode(buf.getvalue()).decode()


TOOL_OUTPUT_HEAD = "[Tool output - not from the user]"


def tool_followup(results: list[tuple[str, list[Path]]]) -> str:
    """Text of the message that carries tool-returned pictures to models whose APIs take images only in user
    messages (Ollama, OpenAI-compatible). Worded so the model doesn't mistake it for the user attaching something."""
    listing = "; ".join(f"{name}: {public_url(p) or p.name}" for name, paths in results for p in paths)
    return f"{TOOL_OUTPUT_HEAD} The images returned by your tool calls above ({listing})."


def data_url(path: Path) -> str:
    mime, b64 = encode(path)
    return f"data:{mime};base64,{b64}"


def save_upload(name: str, data: bytes) -> str:
    """Store an image attached to a chat message; returns its public URL."""
    ext = Path(name).suffix.lower()
    if ext not in EXTENSIONS:
        raise ToolFailure(f"{name}: only {', '.join(sorted(EXTENSIONS))} images can be attached")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ToolFailure(f"{name} is larger than {MAX_UPLOAD_BYTES // 2**20} MB")
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
    except (OSError, UnidentifiedImageError) as exc:
        raise ToolFailure(f"{name} is not a readable image") from exc
    CHAT_DIR.mkdir(parents=True, exist_ok=True)
    out = CHAT_DIR / f"{uuid.uuid4().hex[:16]}{'.jpg' if ext == '.jpeg' else ext}"
    out.write_bytes(data)
    return f"{_PUBLIC}outputs/chat/{out.name}"
