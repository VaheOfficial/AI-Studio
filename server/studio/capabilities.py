"""What this machine can do. The same studio runs on a Windows PC with an NVIDIA GPU, a Mac, or a laptop with no
GPU at all; the UI shows only the areas that can work here and the agent only gets the tools that can run.

A generation feature is available when it can run locally (the model runtimes are CUDA builds, so that means an
NVIDIA GPU) or through a configured cloud provider. Chat, the agent's workspace (terminal, files, browser, Python),
automations, connectors and memory work everywhere."""

from __future__ import annotations

import platform

from . import llamacpp, osenv, settings, system
from .schemas import Capabilities, Feature, FeatureId

_NEEDS_GPU = "Needs an NVIDIA GPU"
# Agent tools that only make sense with a feature (the rest work everywhere)
TOOL_FEATURE: dict[str, FeatureId] = {
    "generate_image": "image", "edit_image": "image",
    "text_to_speech": "voice", "list_voices": "voice", "clone_voice": "voice", "transcribe": "voice",
    "generate_music": "music",
    "generate_video": "video",
    "separate_audio": "dub", "start_dub": "dub",
}


def _gpu() -> str:
    if system.has_nvidia():
        return "nvidia"
    if osenv.IS_MAC and platform.machine().lower() in ("arm64", "aarch64"):
        return "apple"
    return "none"


def _generation(local: bool, cloud: bool, cloud_hint: str) -> Feature:
    if local or cloud:
        return Feature(available=True, local=local, cloud=cloud)
    return Feature(available=False, reason=f"{_NEEDS_GPU}, or {cloud_hint}")


def get() -> Capabilities:
    s = settings.load()
    nvidia = system.has_nvidia()
    openrouter = bool(s.openrouter_api_key)
    features: dict[FeatureId, Feature] = {
        "image": _generation(nvidia, openrouter or bool(s.tencent_api_key), "an OpenRouter key for cloud image models"),
        "voice": _generation(nvidia, openrouter, "an OpenRouter key for cloud speech models"),
        "music": Feature(available=nvidia, local=nvidia, reason=None if nvidia else _NEEDS_GPU),
        "video": Feature(available=nvidia, local=nvidia, reason=None if nvidia else _NEEDS_GPU),
        "dub": Feature(available=nvidia, local=nvidia, reason=None if nvidia else _NEEDS_GPU),
        "game": Feature(available=True, local=True),
        "llamacpp": Feature(available=llamacpp.supported(), local=True,
                            reason=None if llamacpp.supported() else "No llama.cpp build for this machine"),
    }
    return Capabilities(platform=osenv.PLATFORM, machine=osenv.MACHINE, arch=platform.machine().lower(), gpu=_gpu(),
                        shell=osenv.shell_name(), features=features)


def available(feature: FeatureId) -> bool:
    f = get().features.get(feature)
    return bool(f and f.available)


def tool_available(name: str) -> bool:
    feature = TOOL_FEATURE.get(name)
    return feature is None or available(feature)
