"""Isolated Python environments for heavy runtimes, created with uv under ``data/envs/<name>``."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .. import osenv
from ..osenv import NO_WINDOW
from .. import config
from ..jobs import JobContext, JobError, jobs
from ..proc import kill_tree
from ..schemas import Job
from ..textutil import clean_line

MARKER = ".studio-env.json"


@dataclass(frozen=True)
class EnvSpec:
    name: str
    torch: list[str]
    packages: list[str]
    verify: str  # python snippet that must run without error once installed
    extra_args: list[str] = field(default_factory=list)

    @property
    def digest(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:16]


DIFFUSERS = ("diffusers @ https://github.com/huggingface/diffusers/archive/"
             "578c9b2c6636ab2424a0e56186268b83623656b2.zip")  # 0.41.0.dev0, 2026-10-01

ENV_SPECS: dict[str, EnvSpec] = {
    "image": EnvSpec(
        name="image",
        torch=["torch", "torchvision"],
        # diffusers: FLUX.2 / Z-Image / Qwen-Image / Wan / LTX-2 pipelines. Pinned to a commit after 0.40.0, the
        # first with Qwen-Image 2.1 (QwenImage21Pipeline, and its transformer loadable from a GGUF); it comes as a
        # source archive, so no git is needed. Go back to a release once one has it. transformers 5.17: Qwen3-VL,
        # that model's text encoder. gguf + bitsandbytes load quantized variants (and hold text encoders in 8 or 4
        # bits); av: LTX-2's image-to-video re-compresses the start frame the way the model was trained
        packages=[DIFFUSERS, "transformers>=5.17", "accelerate>=1.6", "safetensors", "sentencepiece",
                  "protobuf", "pillow", "einops", "tiktoken", "gguf>=0.10", "bitsandbytes>=0.45", "av>=14"],
        verify=("import torch, diffusers, transformers, accelerate, gguf, bitsandbytes, av; "
                "assert torch.cuda.is_available(), 'CUDA not available'"),
    ),
    # The agent's run_python: data analysis, charts and documents (Word, Excel, PowerPoint, PDF). No torch.
    "python": EnvSpec(
        name="python",
        torch=[],
        packages=["numpy", "pandas", "matplotlib", "scipy", "sympy", "openpyxl", "python-docx", "python-pptx",
                  "reportlab", "pypdf", "pdfplumber", "pillow", "requests", "beautifulsoup4", "tabulate"],
        verify=("import numpy, pandas, matplotlib, scipy, sympy, openpyxl, docx, pptx, reportlab, pypdf, pdfplumber, "
                "PIL, requests, bs4, tabulate"),
    ),
    "voice": EnvSpec(
        name="voice",
        torch=["torch", "torchaudio"],
        packages=[
            "kokoro>=0.9.4", "misaki[en]>=0.9.4", "chatterbox-tts", "faster-whisper>=1.1", "soundfile", "librosa",
            # misaki would otherwise try to pip-install the spaCy model at first use.
            "en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/"
            "en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl",
        ],
        verify=("import torch, kokoro, faster_whisper, soundfile; from chatterbox.tts import ChatterboxTTS; "
                "assert torch.cuda.is_available(), 'CUDA not available'"),
    ),
    "music": EnvSpec(
        name="music",
        # ACE-Step saves through torchaudio's soundfile backend, which torchaudio 2.9 removed.
        torch=["torch==2.8.0", "torchaudio==2.8.0", "torchvision==0.23.0"],
        packages=["ace-step @ git+https://github.com/ace-step/ACE-Step.git", "soundfile"],
        verify="import torch, acestep; assert torch.cuda.is_available(), 'CUDA not available'",
    ),
    "dub": EnvSpec(
        name="dub",
        # Dubbing / audio tools: Demucs separation, faster-whisper word timestamps, pyannote 3.1 diarization,
        # NLLB machine translation, yt-dlp ingest. torchaudio 2.8 still ships the audio backends pyannote 3.x
        # and demucs import; CTranslate2 (faster-whisper) runs on the cuDNN 9 that torch cu128 bundles.
        torch=["torch==2.8.0", "torchaudio==2.8.0"],
        packages=["demucs>=4.0.1", "faster-whisper>=1.1", "pyannote.audio>=3.3,<4", "transformers>=4.46,<5",
                  "sentencepiece", "soundfile", "scikit-learn", "yt-dlp", "huggingface_hub"],
        verify=("import torch, faster_whisper, soundfile, yt_dlp, transformers; import demucs.pretrained, "
                "demucs.apply; from pyannote.audio import Pipeline; "
                "assert torch.cuda.is_available(), 'CUDA not available'"),
    ),
    "omnivoice": EnvSpec(
        name="omnivoice",
        # OmniVoice needs transformers >= 5.10 (HiggsAudioV2 tokenizer), which the Chatterbox pins in `voice`
        # (transformers 5.2) rule out. The inference package itself is vendored in server/workers/omnivoice.
        torch=["torch", "torchaudio"],
        packages=["transformers>=5.10", "accelerate", "safetensors", "huggingface_hub", "pydub", "soundfile",
                  "numpy"],
        verify=("import torch, torchaudio, transformers, accelerate, pydub, soundfile; "
                "from transformers import HiggsAudioV2TokenizerModel; "
                "assert torch.cuda.is_available(), 'CUDA not available'"),
    ),
}


def env_dir(name: str) -> Path:
    return config.ENVS_DIR / name


def env_python(name: str) -> Path:
    return osenv.venv_python(env_dir(name))


def is_ready(name: str) -> bool:
    spec = ENV_SPECS[name]
    marker = env_dir(name) / MARKER
    try:
        return env_python(name).exists() and json.loads(marker.read_text()).get("digest") == spec.digest
    except (OSError, ValueError):
        return False


_create_lock = threading.Lock()


def is_outdated(name: str) -> bool:
    """Installed, but for an earlier version of the app: what the env needs has changed since. (An env that is
    being installed right now has no marker and is not "outdated".)"""
    try:
        marker = json.loads((env_dir(name) / MARKER).read_text())
    except (OSError, ValueError):
        return False
    return env_python(name).exists() and marker.get("digest") != ENV_SPECS[name].digest


def knows_diffusers_class(env: str, class_name: str) -> bool | None:
    """Whether the diffusers installed in ``env`` has ``class_name`` (a pipeline or model class). None when that
    can't be told: the env isn't installed, or is about to be updated."""
    if not is_ready(env):
        return None
    found = sorted(env_dir(env).glob("**/site-packages/diffusers/__init__.py"))
    if not found:
        return None
    try:
        return f'"{class_name}"' in found[0].read_text(encoding="utf-8")
    except OSError:
        return None


def ensure_env_job(name: str, runtime_id: str, force: bool = False) -> Job | None:
    """Start (or return the in-flight) env creation job; ``None`` when the env is already ready.
    ``force`` re-runs the install (uv makes it incremental) even if the env looks ready."""
    if is_ready(name) and not force:
        return None
    with _create_lock:
        active = jobs.find_active(lambda j: j.kind == "env" and j.title == _title(name))
        if active:
            return active.job
        return jobs.submit("env", _title(name), lambda ctx: _create(ctx, ENV_SPECS[name]), ref=runtime_id)


def _title(name: str) -> str:
    return f"Python env: {name}"


def _uv(ctx: JobContext, args: list[str], progress_from: float, progress_to: float, cwd: Path | None = None) -> None:
    """Run ``python -m uv <args>`` streaming its output into the job; nudges progress per line."""
    cmd = [str(config.SERVER_PYTHON), "-m", "uv", *args]
    ctx.log("$ uv " + " ".join(args))
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=config.uv_env(),
                            text=True, encoding="utf-8", errors="replace",
                            creationflags=NO_WINDOW)
    ctx.on_cancel(lambda: kill_tree(proc))
    tail: list[str] = []
    progress = progress_from
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = clean_line(raw)
        if not line:
            continue
        tail = (tail + [line])[-15:]
        progress = min(progress_to - 0.01, progress + (progress_to - progress) * 0.03)
        ctx.update(progress=round(progress, 3))
        ctx.log(line, "debug")
    code = proc.wait()
    ctx.check_cancelled()
    if code != 0:
        raise JobError(f"uv {args[0]} {args[1] if len(args) > 1 else ''} failed (exit {code}):\n" + "\n".join(tail))
    ctx.update(progress=progress_to)


def _create(ctx: JobContext, spec: EnvSpec) -> None:
    target = env_dir(spec.name)
    py = env_python(spec.name)
    (target / MARKER).unlink(missing_ok=True)
    ctx.update(progress=0.01)
    if not py.exists():
        if target.exists():
            shutil.rmtree(target)  # half-created env without an interpreter: start over
        # --seed installs pip so libraries that shell out to pip (spaCy model download) still work.
        _uv(ctx, ["venv", "--python", config.WORKER_PYTHON_VERSION, "--seed", str(target)], 0.01, 0.08)

    torch_pins: dict[str, str] = {}
    if spec.torch:  # envs without ML models (the Python tools env) skip the CUDA wheels
        _uv(ctx, ["pip", "install", "--python", str(py), *spec.torch, "--index-url", config.TORCH_INDEX_URL],
            0.08, 0.5)
        torch_pins = _installed_versions(py, [re.split(r"[\[=<>~!]", p)[0] for p in spec.torch])

    # Pin the CUDA torch build we just installed so no dependency can swap it for a CPU wheel or an
    # older pinned version (e.g. chatterbox-tts pins torch==2.6.0).
    overrides = target / "overrides.txt"
    overrides.write_text("\n".join(f"{n}=={v}" for n, v in torch_pins.items()) + "\n")
    # Relative --override path: uv mis-parses override paths containing spaces ("G:\AI Studio\...").
    _uv(ctx, ["pip", "install", "--python", str(py), "--override", overrides.name,
              "--extra-index-url", config.TORCH_INDEX_URL, "--index-strategy", "unsafe-best-match",
              *spec.extra_args, *spec.packages], 0.5, 0.93, cwd=target)

    ctx.log("Verifying environment…")
    check = subprocess.run([str(py), "-c", spec.verify], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", creationflags=NO_WINDOW)
    if check.returncode != 0:
        raise JobError(f"Environment verification failed:\n{(check.stderr or check.stdout)[-2000:]}")
    (target / MARKER).write_text(json.dumps({"digest": spec.digest, "torch": torch_pins}))
    ctx.log(f"Environment '{spec.name}' ready" + (f" (torch {torch_pins['torch']})" if "torch" in torch_pins else ""))
    from .manager import runtimes  # late import: manager depends on this module

    runtimes.publish_env(spec.name)


def _installed_versions(py: Path, names: list[str]) -> dict[str, str]:
    code = ("import importlib.metadata as m, json, sys; "
            "print(json.dumps({n: m.version(n) for n in sys.argv[1:]}))")
    out = subprocess.run([str(py), "-c", code, *names], capture_output=True, text=True, check=False,
                         creationflags=NO_WINDOW)
    if out.returncode != 0:
        raise JobError(f"Could not read installed torch version: {out.stderr[-500:]}")
    return json.loads(out.stdout)
