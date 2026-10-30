"""Built-in llama.cpp runtime: the pinned official ``llama-server`` build for this machine (Windows or Linux with
CUDA on NVIDIA GPUs, Metal on Apple Silicon, CPU otherwise), serving one GGUF at a time on a local port with an
OpenAI-compatible API. ``--jinja`` applies the model's own chat template, so tool calls work."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import shutil
import socket
import subprocess
import tarfile
import threading
import time
import zipfile
from pathlib import Path

import httpx

from . import config, events, osenv, settings
from .osenv import detached
from .gguf_meta import DRAFT_ARCHITECTURES, architecture, mtp_layers, read_values
from .jobs import JobContext, JobError, RateMeter, jobs
from .localhttp import client
from .proc import bind_to_server_lifetime, kill_tree
from .runtimes import RuntimeNotReady, WorkerError, runtimes
from .runtimes.manager import ExternalStatus
from .schemas import InstalledModel, Job

RELEASE = "b11259"
_DOWNLOAD_URL = f"https://github.com/ggml-org/llama.cpp/releases/download/{RELEASE}"
Asset = tuple[str, int, str]  # (file name, bytes, sha256) as published in the GitHub release for this tag
# Builds per machine: (label, archives). CUDA 13.4 needs driver >= 580.
_BUILDS: dict[str, tuple[str, tuple[Asset, ...]]] = {
    "windows-cuda": ("CUDA 13.4", (
        ("llama-b11259-bin-win-cuda-13.4-x64.zip", 153546058,
         "7e93d79ed0dfacb67a7a5448eab38b60511ec3ad623022259b08490d5cf01404"),
        ("cudart-llama-bin-win-cuda-13.4-x64.zip", 423535356,
         "738f8c251ac22b70c3ae6f83a10cf222725df0395246a2cf58f32bdb85fbe668"),
    )),
    "windows-x64": ("CPU", (
        ("llama-b11259-bin-win-cpu-x64.zip", 19164803,
         "977c5ddcd24caaaaaf87a9cdcfa46972a1c8ccf2007a013a45c84e8bc31865d9"),
    )),
    "windows-arm64": ("CPU", (
        ("llama-b11259-bin-win-cpu-arm64.zip", 12051898,
         "fbe90f5549bfe662ca151fd0a4e123e85041e6b363bd9b76ac233f435fe8f1c7"),
    )),
    "macos-arm64": ("Metal", (
        ("llama-b11259-bin-macos-arm64.tar.gz", 11767669,
         "abd2b16d698861ac332a1eff1ea0edb0732aa6f7bb729a920dbe8b6502e353d4"),
    )),
    "macos-x64": ("CPU", (
        ("llama-b11259-bin-macos-x64.tar.gz", 11320042,
         "1a718a5bc1fd5e44807172fd7fc0ffdcd774d72d7ba777b8865e0483d9fdd162"),
    )),
    "linux-cuda": ("CUDA 13.4", (
        ("llama-b11259-bin-ubuntu-cuda-13.4-x64.tar.gz", 152878063,
         "ccd87e3754b7445a45231090e509b9142e171240f9dbc20eb9358e9f7ca9dfa6"),
        ("cudart-llama-b11259-bin-ubuntu-cuda-13.4-x64.tar.gz", 440236546,
         "8beb2d945a6087810029182fd9b214d2d89b3bcc360483599625209cc136b951"),
    )),
    "linux-x64": ("CPU", (
        ("llama-b11259-bin-ubuntu-x64.tar.gz", 17407983,
         "17ef03988f78292afa0d16c0b19405572e0d992973584ed8b2b230751d76e252"),
    )),
    "linux-arm64": ("CPU", (
        ("llama-b11259-bin-ubuntu-arm64.tar.gz", 13505697,
         "508e7ce80a16cd8f3e7ae325cfc1897e237978dfae4076589ae47f2d8715a4de"),
    )),
}


def build_key() -> str | None:
    """Which pinned build fits this machine: CUDA with an NVIDIA GPU, Metal on Apple silicon, CPU otherwise."""
    from . import system  # late: system imports the engines' status modules

    nvidia = system.has_nvidia()
    arm = platform.machine().lower() in ("arm64", "aarch64")
    if osenv.IS_WINDOWS:
        if arm:
            return "windows-arm64"
        return "windows-cuda" if nvidia else "windows-x64"
    if osenv.IS_MAC:
        return "macos-arm64" if arm else "macos-x64"
    if arm:
        return "linux-arm64"
    return "linux-cuda" if nvidia else "linux-x64"


def supported() -> bool:
    return build_key() is not None


def _assets() -> tuple[Asset, ...]:
    key = build_key()
    return _BUILDS[key][1] if key else ()


def build_label() -> str:
    key = build_key()
    return f"{RELEASE} · {_BUILDS[key][0]}" if key else RELEASE


ROOT_DIR = config.ENVS_DIR / "llamacpp"
INSTALL_DIR = ROOT_DIR / RELEASE
_MARKER = INSTALL_DIR / ".studio-llamacpp.json"
_STARTUP_TIMEOUT_S = 900  # large GGUFs are read at USB-disk speed
_CHUNK = 1 << 20


def server_exe() -> Path:
    return INSTALL_DIR / osenv.exe("llama-server")


def installed() -> bool:
    try:
        return server_exe().exists() and json.loads(_MARKER.read_text()).get("release") == RELEASE
    except (OSError, ValueError):
        return False


# ------------------------------ install ------------------------------

_install_lock = threading.Lock()


def ensure_installed_job(force: bool = False) -> Job | None:
    """Start (or return the running) binary download job; ``None`` when already installed."""
    if installed() and not force:
        return None
    with _install_lock:
        active = jobs.find_active(lambda j: j.kind == "env" and j.ref == "llamacpp")
        if active:
            return active.job
        return jobs.submit("env", f"llama.cpp {build_label()}", _install, ref="llamacpp")


def _install(ctx: JobContext) -> None:
    assets = _assets()
    if not assets:
        raise JobError("There is no llama.cpp build for this machine. Use Ollama or LM Studio, or a cloud model.")
    server.stop()  # Windows can't replace the DLLs of a running llama-server
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    _MARKER.unlink(missing_ok=True)
    total = sum(size for _, size, _ in assets)
    done_before = 0
    meter = RateMeter()
    reusable = _previous_assets()
    record: dict[str, dict[str, object]] = {}
    for name, size, digest in assets:
        files = _reuse(reusable.get((name, digest)))
        if files is None:
            archive = INSTALL_DIR / name
            _download(ctx, f"{_DOWNLOAD_URL}/{name}", archive, digest, done_before, total, meter)
            ctx.update(message=f"Extracting {name}", speed_bps=None)
            files = _extract(archive)
            archive.unlink()
        else:
            ctx.update(message=f"Reusing {name} (unchanged since the previous build)", speed_bps=None)
        record[name] = {"sha256": digest, "files": files}
        done_before += size
    if not server_exe().exists():
        raise JobError(f"{server_exe().name} missing from the {RELEASE} release archive")
    _MARKER.write_text(json.dumps({"release": RELEASE, "assets": record}))
    for old in ROOT_DIR.iterdir():  # builds pinned by earlier studio versions
        if old.is_dir() and old != INSTALL_DIR:
            shutil.rmtree(old, ignore_errors=True)
    ctx.update(message=f"llama.cpp {build_label()} ready", progress=1.0)
    runtimes.publish("llamacpp")


def _extract(archive: Path) -> list[str]:
    """Unpack a release archive into INSTALL_DIR; returns the files it placed (relative). Windows zips are flat;
    the macOS/Linux tarballs have one top-level folder, which is dropped."""
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(INSTALL_DIR)
            return [n for n in zf.namelist() if not n.endswith("/")]
    files: list[str] = []
    with tarfile.open(archive) as tf:
        for member in tf.getmembers():
            rel = "/".join(member.name.split("/")[1:])
            if not rel:
                continue
            member.name = rel
            tf.extract(member, INSTALL_DIR, filter="data")  # keeps exec bits and in-folder symlinks, nothing else
            if not member.isdir():
                files.append(rel)
    return files


def _previous_assets() -> dict[tuple[str, str], tuple[Path, list[str]]]:
    """Archives other installed builds extracted, by (name, sha256): an update copies an unchanged one (the 400+ MB
    CUDA runtime usually is) instead of downloading it again."""
    found: dict[tuple[str, str], tuple[Path, list[str]]] = {}
    for old in ROOT_DIR.iterdir() if ROOT_DIR.is_dir() else ():
        if not old.is_dir() or old == INSTALL_DIR:
            continue
        try:
            assets = json.loads((old / _MARKER.name).read_text()).get("assets") or {}
        except (OSError, ValueError):
            continue
        for name, info in assets.items():
            found[(name, str(info.get("sha256")))] = (old, list(info.get("files") or []))
    return found


def _reuse(previous: tuple[Path, list[str]] | None) -> list[str] | None:
    """Copy a previous build's files of an unchanged archive; ``None`` if they aren't all there."""
    if previous is None:
        return None
    src, files = previous
    if not files or not all((src / f).is_file() for f in files):
        return None
    for f in files:
        (INSTALL_DIR / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / f, INSTALL_DIR / f)
    return files


def _download(ctx: JobContext, url: str, dest: Path, digest: str, done_before: int, total: int,
              meter: RateMeter) -> None:
    part = dest.with_suffix(".part")
    sha = hashlib.sha256()
    done = 0
    ctx.update(message=f"Downloading {dest.name}", bytes_total=total)
    with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(30, read=120)) as r:
        if r.status_code != 200:
            raise JobError(f"Download of {url} failed: HTTP {r.status_code}")
        with part.open("wb") as f:
            for chunk in r.iter_bytes(_CHUNK):
                ctx.check_cancelled()
                f.write(chunk)
                sha.update(chunk)
                done += len(chunk)
                overall = done_before + done
                speed = meter.sample(overall)
                ctx.update(progress=round(overall / total, 4), bytes_done=overall,
                           speed_bps=round(speed) if speed else None)
    if sha.hexdigest() != digest:
        part.unlink(missing_ok=True)
        raise JobError(f"Checksum mismatch for {dest.name}: expected {digest}, got {sha.hexdigest()}")
    part.replace(dest)


# ------------------------------ server ------------------------------


def model_files(m: InstalledModel) -> tuple[Path, Path | None]:
    """(main GGUF — the first shard of a split set, vision projector if any) of an installed model."""
    base = Path(m.path)
    if base.is_file():
        return base, None
    ggufs = sorted(f for f in (m.files or []) if f.lower().endswith(".gguf"))
    main = next((f for f in ggufs if "mmproj" not in f.lower()), None)
    if main is None:
        raise WorkerError(f"{m.name} has no GGUF weights to load")
    mmproj = next((f for f in ggufs if "mmproj" in f.lower()), None)
    return base / main, (base / mmproj if mmproj else None)


def is_draft_model(m: InstalledModel) -> bool:
    """A speculative-decoding drafter (DFlash, EAGLE-3): it can't answer on its own, so it isn't a chat model."""
    if m.runtime != "llamacpp" or m.format != "gguf":
        return False
    try:
        main, _ = model_files(m)
    except WorkerError:
        return False
    return architecture(main) in DRAFT_ARCHITECTURES


def supports_tool_chat(model: Path) -> bool:
    """Reject known pretrained Gemma variants rather than claiming agent support."""
    if architecture(model) != "gemma4":
        return True
    meta = read_values(model, {"general.source.url", "general.finetune", "tokenizer.chat_template"})
    source = str(meta.get("general.source.url") or "").lower().rstrip("/")
    # The exact Google base model has no instruction tuning or tool-call contract.
    if source.startswith("https://huggingface.co/google/gemma-4-") and not source.endswith("-it"):
        return False
    return bool(meta.get("tokenizer.chat_template") or source.endswith("-it") or meta.get("general.finetune"))


def chat_template_override(model: Path) -> Path | None:
    """Gemma 4 GGUFs without their native template must not fall back to ChatML.

    Source: google/gemma-4-26B-A4B-it chat_template.jinja.
    The family format is shared by the 26B-A4B and 31B instruction models.
    """
    if architecture(model) != "gemma4" or not supports_tool_chat(model):
        return None
    embedded = read_values(model, {"tokenizer.chat_template"}).get("tokenizer.chat_template")
    if not embedded or "<|turn>" not in embedded:
        return Path(__file__).parent / "templates" / "gemma4.jinja"
    return None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind((config.HOST, 0))
        return int(s.getsockname()[1])


class LlamaServer:
    """One ``llama-server`` process at a time; loading another model restarts it."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._proc: subprocess.Popen[str] | None = None
        self._port: int | None = None
        self._model_id: str | None = None
        self._parallel = 1
        self._context_per_slot: int | None = None
        self._load_owner: str | None = None
        self._loading = False
        self._gpu_offload_complete: bool | None = None

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def status(self) -> ExternalStatus:
        alive = self._alive()
        return ExternalStatus(installed=installed(), running=alive, port=self._port if alive else None,
                              loaded_model=self._model_id if alive else None)

    def base_url(self, model_id: str) -> str | None:
        """OpenAI-compatible base URL while ``model_id`` is the served model."""
        if self._alive() and self._model_id == model_id:
            return f"http://{config.HOST}:{self._port}/v1"
        return None

    def capacity(self) -> dict[str, int | bool] | None:
        """Verify slots/context and whether any request is in flight before a reconfiguration."""
        if not self._alive() or self._loading:
            return None
        props = client.get(f"http://{config.HOST}:{self._port}/props", timeout=5)
        props.raise_for_status()
        slots = client.get(f"http://{config.HOST}:{self._port}/slots", timeout=5)
        slots.raise_for_status()
        data = props.json()
        result={'slots': int(data['total_slots']),
                'context_per_slot': int(data['default_generation_settings']['n_ctx']),
                'busy': any(v.get('is_processing', False) for v in slots.json())}
        if self._gpu_offload_complete is not None:
            result['gpu_offload_complete']=self._gpu_offload_complete
        return result

    def cancel_load(self, owner: str) -> None:
        """Cancel only the loader owned by this arena, without stopping an unrelated server."""
        with self._lock:
            if self._loading and self._load_owner == owner:
                self._stop_locked()

    def release_arena(self, owners: set[str]) -> bool:
        """Release an idle temporary arena load; ordinary loads have no arena owner."""
        with self._lock:
            if self._load_owner not in owners or self._loading or not self._alive():
                return False
            current=self.capacity()
            if not current or current['busy']:
                return False
            model_id=self._stop_locked()
        _mark_unloaded(model_id)
        return True

    def load(self, m: InstalledModel, *, parallel: int = 1, context_per_slot: int | None = None,
             owner: str | None = None) -> None:
        if parallel not in (1, 2):
            raise ValueError('Supported llama.cpp generation slots are one or two')
        if not installed():
            raise RuntimeNotReady("llama.cpp is not installed yet: set it up under Models → Runtimes "
                                  "(installing a GGUF model with llama.cpp does this too).")
        model, mmproj = model_files(m)
        if not model.exists():
            raise WorkerError(f"{model} is missing; reinstall {m.name}")
        if is_draft_model(m):
            raise WorkerError(f"{m.name} is a speculative-decoding draft model: it only runs next to the model it "
                              "was made for, not on its own")
        s = settings.load()
        context = context_per_slot or s.llamacpp_ctx_size
        if not 2048 <= context <= 262144:
            raise ValueError('Context per slot must be between 2048 and 262144 tokens')
        with self._lock:
            self._stop_locked()
            port = _free_port()
            cmd = [str(server_exe()), "-m", str(model), "--host", config.HOST, "--port", str(port),
                   "--jinja", "-ngl", "auto", "--fit", "on", "-c", str(context * parallel),
                   "--alias", m.id, "--no-webui", "-np", str(parallel), "--cont-batching"]
            if template := chat_template_override(model):
                cmd += ["--chat-template-file", str(template)]
                events.log("info", "llamacpp", "Using bundled native Gemma 4 template; GGUF template is missing or incompatible")
            if s.llamacpp_kv_cache != "f16":
                cmd += ["-ctk", s.llamacpp_kv_cache, "-ctv", s.llamacpp_kv_cache]
            if mmproj:
                cmd += ["--mmproj", str(mmproj)]
                if context * parallel > 65536:
                    # The vision projector (~1 GB) runs on the CPU so a long context still fits on the GPU; only
                    # pictures pay for it (a few seconds each). Measured, 27B Q4 on a 4090: 96K stays at ~82 tok/s.
                    cmd += ["--no-mmproj-offload"]
            mtp = mtp_layers(model)
            if mtp and parallel == 1:
                # The model's own multi-token-prediction head drafts 3 tokens per step, verified in one pass. One
                # slot: with llama-server's default 4 (or even 2) parallel slots the verification of hybrid models
                # (recurrent + attention layers, e.g. Qwen3.8) cost ~1 token-time per drafted token and drafting was
                # slower than none. Measured, Qwen3.8 27B Q4 on a 4090: 37 tok/s plain → 70-103 tok/s. Requests
                # that arrive together (a title while a reply streams) take turns.
                cmd += ["--spec-type", "draft-mtp", "--spec-draft-n-max", "3"]
            events.log("info", "llamacpp", f"Starting llama-server {RELEASE} for {m.name} on port {port}"
                                           + f" with {parallel} generation slot(s), {context} requested tokens per slot"
                                           + (" and MTP speculative decoding" if mtp and parallel == 1 else ""))
            proc = subprocess.Popen(cmd, cwd=INSTALL_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace",
                                    **detached())
            bind_to_server_lifetime(proc)
            self._proc, self._port, self._model_id = proc, port, m.id
            self._parallel, self._context_per_slot = parallel, context
            self._load_owner, self._loading = owner, True
            self._gpu_offload_complete = None
            tail: list[str] = []
            threading.Thread(target=self._pump, args=(proc, tail), daemon=True, name="log-llamacpp").start()
        runtimes.publish("llamacpp")
        try:
            self._wait_healthy(proc, port, tail)  # outside the lock so stop() can abort a slow load
        except Exception:
            with self._lock:
                if self._proc is proc:
                    self._stop_locked()
            runtimes.publish("llamacpp")
            raise
        finally:
            with self._lock:
                if self._proc is proc:
                    self._loading = False
        events.log("info", "llamacpp", f"{m.name} is being served on port {port}")

    @staticmethod
    def _wait_healthy(proc: subprocess.Popen[str], port: int, tail: list[str]) -> None:
        deadline = time.monotonic() + _STARTUP_TIMEOUT_S
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                time.sleep(0.2)  # let the log pump drain the error
                raise WorkerError(f"llama-server exited while loading (code {proc.returncode}):\n"
                                  + "\n".join(tail[-15:]))
            try:
                if client.get(f"http://{config.HOST}:{port}/health", timeout=2).status_code == 200:
                    return
            except httpx.TransportError:
                pass
            time.sleep(0.5)
        raise WorkerError(f"llama-server did not finish loading within {_STARTUP_TIMEOUT_S}s")

    def _pump(self, proc: subprocess.Popen[str], tail: list[str]) -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip()
            if not line:
                continue
            tail.append(line)
            del tail[:-40]
            lowered = line.lower()
            if offload := re.search(r'offloaded\s+(\d+)/(\d+)\s+layers\s+to\s+gpu',lowered):
                with self._lock:
                    if self._proc is proc:
                        self._gpu_offload_complete=int(offload[1])==int(offload[2])
            level: events.LogLevel = "error" if ("error" in lowered or "failed" in lowered) else "debug"
            events.log(level, "llamacpp", line)
        code = proc.wait()
        with self._lock:
            if self._proc is not proc:
                return  # replaced or stopped on purpose
            model_id = self._model_id
            self._proc, self._port, self._model_id = None, None, None
        events.log("warn" if code else "info", "llamacpp", f"llama-server exited (code {code})")
        _mark_unloaded(model_id)

    def _stop_locked(self) -> str | None:
        """Kill the process; returns the id of the model it was serving."""
        proc, model_id = self._proc, self._model_id
        self._proc, self._port, self._model_id = None, None, None
        self._parallel, self._context_per_slot = 1, None
        self._load_owner, self._loading = None, False
        self._gpu_offload_complete = None
        if proc is not None and proc.poll() is None:
            kill_tree(proc)
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                events.log("warn", "llamacpp", f"llama-server pid {proc.pid} did not exit after kill")
        return model_id

    def stop(self) -> None:
        """Stop serving and free the VRAM."""
        with self._lock:
            model_id = self._stop_locked()
        _mark_unloaded(model_id)


def _mark_unloaded(model_id: str | None) -> None:
    if model_id:
        from .models import models  # late import: models depends on this module

        models.set_status(model_id, "ready")
    runtimes.publish("llamacpp")


server = LlamaServer()
runtimes.register_external("llamacpp", server.status)
