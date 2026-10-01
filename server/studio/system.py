"""Hardware telemetry via psutil and NVML."""

from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path

import psutil

from . import config, events, lmstudio, ollama
from .schemas import GpuInfo, OllamaStatus, SystemInfo

try:
    import pynvml
except ImportError:  # nvidia-ml-py is a declared dependency, but keep the server usable without it
    pynvml = None

_nvml_lock = threading.Lock()
_nvml_ready: bool | None = None


def _nvml() -> bool:
    global _nvml_ready
    with _nvml_lock:
        if _nvml_ready is None:
            if pynvml is None:
                _nvml_ready = False
            else:
                try:
                    pynvml.nvmlInit()
                    _nvml_ready = True
                except pynvml.NVMLError as exc:
                    # normal on a Mac or any PC without an NVIDIA card
                    events.log("info", "system", f"No NVIDIA GPU (NVML: {exc}); GPU features are off")
                    _nvml_ready = False
        return _nvml_ready


def gpus() -> list[GpuInfo]:
    """NVIDIA GPUs (NVML). Empty on machines without one - and when ``STUDIO_NO_GPU=1`` hides them, which runs the
    studio as a no-GPU machine would (cloud and CPU features only)."""
    if os.environ.get("STUDIO_NO_GPU") == "1" or not _nvml():
        return []
    result: list[GpuInfo] = []
    for i in range(pynvml.nvmlDeviceGetCount()):
        h = pynvml.nvmlDeviceGetHandleByIndex(i)
        mem = pynvml.nvmlDeviceGetMemoryInfo(h)
        name = pynvml.nvmlDeviceGetName(h)
        try:
            util = float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)
        except pynvml.NVMLError:
            util = 0.0
        try:
            temp: float | None = float(pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU))
        except pynvml.NVMLError:
            temp = None
        result.append(GpuInfo(
            name=name.decode() if isinstance(name, bytes) else name,
            vram_total=int(mem.total), vram_used=int(mem.used), util=util, temp_c=temp,
        ))
    return result


def has_nvidia() -> bool:
    return bool(gpus())


def vram_total_bytes() -> int:
    """VRAM of the largest GPU (models are placed on a single device)."""
    return max((g.vram_total for g in gpus()), default=0)


def vram_free_bytes() -> int:
    return max((g.vram_total - g.vram_used for g in gpus()), default=0)


def ram_total_bytes() -> int:
    return int(psutil.virtual_memory().total)


def disk_free_bytes(path: Path | None = None) -> int:
    """Free space on the drive holding ``path`` (default: the data folder)."""
    where = path or config.DATA_DIR
    try:
        return int(shutil.disk_usage(where).free)
    except OSError as exc:
        events.log("warn", "system", f"Cannot stat {where}: {exc}")
        return 0


def info() -> SystemInfo:
    """Full ``SystemInfo`` (blocking: NVML + an Ollama version probe; call via ``asyncio.to_thread``)."""
    vm = psutil.virtual_memory()
    installed, running, version = ollama.refresh_status()
    lmstudio.refresh_status()  # pushes runtime.update when the LM Studio app's server starts or stops
    return SystemInfo(
        gpus=gpus(), ram_total=int(vm.total), ram_used=int(vm.total - vm.available),
        cpu_percent=psutil.cpu_percent(interval=None), disk_free=disk_free_bytes(),
        data_dir=str(config.DATA_DIR), ollama=OllamaStatus(installed=installed, running=running, version=version),
    )


def summary_text() -> str:
    """One-paragraph hardware description for the agent system prompt."""
    gpu_list = gpus()
    gpu_txt = ", ".join(f"{g.name} ({g.vram_total / 2**30:.0f} GB VRAM, {g.vram_used / 2**30:.1f} GB used)"
                        for g in gpu_list) or "no NVIDIA GPU detected"
    vm = psutil.virtual_memory()
    return (f"GPU: {gpu_txt}. RAM: {vm.total / 2**30:.0f} GB ({vm.used / 2**30:.0f} GB used). "
            f"CPU: {psutil.cpu_count(logical=False)} cores / {psutil.cpu_count()} threads. "
            f"Free disk in data dir: {disk_free_bytes() / 2**30:.0f} GB.")
