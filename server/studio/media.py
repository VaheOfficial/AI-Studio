"""ffmpeg / ffprobe for every feature: locate a runnable binary, or fetch a pinned static build.

Ported from VoiceStudio ``services/ffmpeg_utils.py`` + ``services/media_tools.py``. Resolution order:
``FFMPEG_PATH`` / ``FFPROBE_PATH`` env → the build acquired into ``data/tools`` → the system ``PATH``.
Each candidate must pass a ``-version`` probe before it is trusted (a WindowsApps alias stub or a
wrong-arch binary exists on disk but explodes at spawn).

The bundled build is downloaded from ``github.com/zackees/ffmpeg_bins`` at an immutable commit and
verified by size + SHA-256 before extraction (VoiceStudio's decision record: the ``static-ffmpeg``
pip package downloads a mutable branch tip without checksums).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

import httpx

from . import config
from .jobs import JobContext, JobError, RateMeter, jobs
from .proc import kill_tree
from .schemas import Job
from .schemas_dub import MediaToolsStatus, MediaToolInfo

TOOLS_DIR = config.DATA_DIR / "tools"

_FFBIN_REPO = "zackees/ffmpeg_bins"
_FFBIN_COMMIT = "df95abcb0ce6efff710dda5ef28a2f6f1dc21493"  # 2026-01-16, ffmpeg 8.0
_FFBIN_TREE = "v8.0"
# git-LFS oids (sha256) + sizes of the platform zips at the pinned commit.
_FFBIN_SHA256 = {"win32": ("92662c2241e93fe71b3f3a01e94a0b0dc8cfad726019f96b83bc109ce44c5d0b", 72065209)}
_ENV_KEYS = {"ffmpeg": "FFMPEG_PATH", "ffprobe": "FFPROBE_PATH"}
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# Windows CreateProcess rejects command lines over 32,767 chars; a many-track mux can exceed it.
_WIN_ARGV_SOFT_LIMIT = 30_000

_ok_cache: dict[str, bool] = {}
_version_cache: dict[str, str | None] = {}
_lock = threading.Lock()


class MediaError(RuntimeError):
    """ffmpeg is missing or a media command failed; message is user-facing."""


def _exe(name: str) -> str:
    return f"{name}.exe" if sys.platform == "win32" else name


def bundled_dir() -> Path:
    # Versioned by the pin so a future bump lands in a fresh directory.
    return TOOLS_DIR / f"ffmpeg-{_FFBIN_COMMIT[:12]}"


def _runs(path: str) -> bool:
    cached = _ok_cache.get(path)
    if cached is not None:
        return cached
    try:
        ok = subprocess.run([path, "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
                            check=False, creationflags=_NO_WINDOW).returncode == 0
    except (OSError, subprocess.SubprocessError):
        ok = False
    _ok_cache[path] = ok
    return ok


def _resolve(tool: str) -> tuple[str | None, str | None]:
    """(path, origin) where origin is env | bundled | system."""
    env_path = os.environ.get(_ENV_KEYS[tool])
    if env_path:
        found = shutil.which(env_path) or (env_path if os.path.isfile(env_path) else None)
        if found and _runs(found):
            return found, "env"
    bundled = bundled_dir() / _exe(tool)
    if bundled.is_file() and _runs(str(bundled)):
        return str(bundled), "bundled"
    system = shutil.which(tool)
    if system and _runs(system):
        return system, "system"
    return None, None


def find(tool: str) -> str | None:
    return _resolve(tool)[0]


def ffmpeg() -> str:
    path = find("ffmpeg")
    if not path:
        raise MediaError("ffmpeg is not installed. Install it from the Dub page (Media tools) or put ffmpeg on PATH.")
    return path


def ffprobe() -> str:
    path = find("ffprobe")
    if not path:
        raise MediaError("ffprobe is not installed. Install it from the Dub page (Media tools) or put it on PATH.")
    return path


def _version(path: str) -> str | None:
    if path not in _version_cache:
        try:
            out = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=10, check=False,
                                 creationflags=_NO_WINDOW).stdout
            first = (out or "").split("\n", 1)[0].split()
            _version_cache[path] = first[2] if len(first) > 2 else None
        except (OSError, subprocess.SubprocessError):
            _version_cache[path] = None
    return _version_cache[path]


def status() -> MediaToolsStatus:
    tools = []
    for tool in ("ffmpeg", "ffprobe"):
        path, origin = _resolve(tool)
        tools.append(MediaToolInfo(tool=tool, ok=bool(path), path=path, origin=origin,
                                   version=_version(path) if path else None))
    return MediaToolsStatus(ready=all(t.ok for t in tools), tools=tools, bundle_available=sys.platform in _FFBIN_SHA256)


def install_job() -> Job:
    """Download + verify + unpack the pinned static ffmpeg/ffprobe into ``data/tools``."""
    if sys.platform not in _FFBIN_SHA256:
        raise MediaError(f"No pinned ffmpeg build for platform {sys.platform}; install ffmpeg with your package manager")
    with _lock:
        active = jobs.find_active(lambda j: j.kind == "download" and j.ref == "media-tools")
        if active:
            return active.job
        return jobs.submit("download", "Install ffmpeg + ffprobe", _acquire, ref="media-tools")


def _acquire(ctx: JobContext) -> None:
    sha, size = _FFBIN_SHA256[sys.platform]
    url = f"https://github.com/{_FFBIN_REPO}/raw/{_FFBIN_COMMIT}/{_FFBIN_TREE}/{sys.platform}.zip"
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    target = bundled_dir()
    with tempfile.TemporaryDirectory(dir=TOOLS_DIR) as tmp:
        zip_path = Path(tmp) / "ffmpeg.zip"
        hasher = hashlib.sha256()
        meter = RateMeter()
        done = 0
        ctx.log(f"Downloading pinned ffmpeg build ({size / 1e6:.0f} MB)")
        with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(30, read=120)) as r:
            if r.status_code >= 400:
                raise JobError(f"ffmpeg download failed: HTTP {r.status_code}")
            with zip_path.open("wb") as f:
                for chunk in r.iter_bytes(1 << 18):
                    ctx.check_cancelled()
                    f.write(chunk)
                    hasher.update(chunk)
                    done += len(chunk)
                    bps = meter.sample(done)
                    ctx.update(progress=round(min(done / size, 0.99), 4), bytes_done=done, bytes_total=size,
                               speed_bps=round(bps) if bps else None)
        if done != size or hasher.hexdigest() != sha:
            raise JobError("ffmpeg download failed verification (size/checksum mismatch) — refusing to install")
        staged = Path(tmp) / "staged"
        staged.mkdir()
        wanted = {_exe("ffmpeg"), _exe("ffprobe")}
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.infolist():
                base = os.path.basename(member.filename)
                if base in wanted and not member.is_dir():
                    with zf.open(member) as src, (staged / base).open("wb") as dst:
                        shutil.copyfileobj(src, dst)
        for base in wanted:
            path = staged / base
            if not path.is_file() or not _runs(str(path)):
                raise JobError(f"The downloaded {base} does not run on this machine")
        if target.exists():
            shutil.rmtree(target)
        staged.replace(target)
    _ok_cache.clear()
    _version_cache.clear()
    ctx.log(f"ffmpeg {_version(str(target / _exe('ffmpeg'))) or ''} installed in {target}")


# ------------------------------------------------------------------ running


def run(cmd: list[str], ctx: JobContext | None = None, *, timeout: float = 3600, what: str = "ffmpeg") -> str:
    """Run an ffmpeg/ffprobe command; returns stderr. Cancelling ``ctx`` kills the process.
    Oversized ``-filter_complex`` graphs are moved into a script file (Windows argv limit)."""
    cmd, script = _externalize_filter(cmd)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=_NO_WINDOW)
        if ctx is not None:
            ctx.on_cancel(lambda: kill_tree(proc))
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_tree(proc)
            proc.wait()
            raise MediaError(f"{what} timed out after {timeout:.0f}s") from None
        if ctx is not None:
            ctx.check_cancelled()
        stderr = err.decode("utf-8", errors="replace")
        if proc.returncode != 0:
            raise MediaError(f"{what} failed (exit {proc.returncode}): {stderr.strip()[-800:]}")
        return stderr + out.decode("utf-8", errors="replace")
    finally:
        if script:
            Path(script).unlink(missing_ok=True)


def _externalize_filter(cmd: list[str]) -> tuple[list[str], str | None]:
    if sum(len(a) + 1 for a in cmd) <= _WIN_ARGV_SOFT_LIMIT or "-filter_complex" not in cmd:
        return cmd, None
    idx = cmd.index("-filter_complex")
    fd, script = tempfile.mkstemp(suffix=".ffgraph", prefix="studio_filter_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(cmd[idx + 1])
    out = list(cmd)
    out[idx:idx + 2] = ["-/filter_complex", script]
    return out, script


def probe(path: str | Path) -> dict:
    """ffprobe JSON (format + streams)."""
    import json

    out = subprocess.run([ffprobe(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
                          str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                         timeout=120, creationflags=_NO_WINDOW)
    if out.returncode != 0:
        raise MediaError(f"Could not read media file: {out.stderr.strip()[-400:] or 'ffprobe failed'}")
    return json.loads(out.stdout or "{}")


def duration(path: str | Path) -> float:
    info = probe(path)
    try:
        return float(info.get("format", {}).get("duration") or 0.0)
    except ValueError:
        return 0.0


def pcm16(path: str | Path, rate: int) -> bytes:
    """Decode to mono signed 16-bit little-endian PCM at ``rate`` Hz."""
    out = subprocess.run([ffmpeg(), "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"],
                         capture_output=True, timeout=600, creationflags=_NO_WINDOW)
    if out.returncode != 0:
        raise MediaError(f"Could not decode audio: {out.stderr.decode('utf-8', 'replace').strip()[-400:]}")
    return out.stdout


def frame_rates(path: str | Path) -> tuple[str, str] | None:
    """(r_frame_rate, avg_frame_rate) of the first video stream."""
    for s in probe(path).get("streams", []):
        if s.get("codec_type") == "video":
            return str(s.get("r_frame_rate") or ""), str(s.get("avg_frame_rate") or "")
    return None


# ------------------------------------------------------------------ filters

BED_MIX_SAMPLE_RATE = 48000
VOICE_GAIN = 1.1


def bed_mix_filter(bed_in: str, voice_in: str, *, out: str = "aout", tail: str = "", uniq: str = "",
                   bed_gain: float = 1.0) -> str:
    """Mix ``voice_in`` over ``bed_in`` at original level (VoiceStudio ``bed_mix_filter``): both legs resampled
    to 48 kHz stereo so the bed keeps its bandwidth and stereo image; ``normalize=0`` makes amix a plain sum
    (its dynamic normalisation would otherwise duck the bed), a limiter catches summed peaks."""
    b, v = f"bmb{uniq}", f"bmv{uniq}"
    stereo = "aformat=channel_layouts=stereo"
    return (f"[{bed_in}]aresample={BED_MIX_SAMPLE_RATE},{stereo},volume={bed_gain:g}[{b}];"
            f"[{voice_in}]aresample={BED_MIX_SAMPLE_RATE},{stereo},volume={VOICE_GAIN:g}[{v}];"
            f"[{b}][{v}]amix=inputs=2:duration=longest:dropout_transition=2:normalize=0,"
            f"alimiter=level=false:limit=0.98:latency=1{tail}[{out}]")


def atempo_chain(ratio: float) -> str:
    """``atempo`` stages for any ratio (each stage is limited to [0.5, 2.0]); pitch is preserved."""
    stages: list[str] = []
    remaining = ratio
    while remaining > 2.0:
        stages.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        stages.append("atempo=0.5")
        remaining /= 0.5
    stages.append(f"atempo={remaining:.6f}")
    return ",".join(stages)


def filter_escape(path: str | Path) -> str:
    """Escape a path for a quoted ffmpeg filter value (``subtitles=``/``ass=``): forward slashes on Windows,
    escaped drive colon and apostrophes."""
    normalized = str(path).replace("\\", "/")
    return normalized.replace(":", "\\:").replace("'", "'\\\\\\''")
