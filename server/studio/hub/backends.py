"""Status of the three engines that run GGUF language models: LM Studio, the built-in llama.cpp and Ollama."""

from __future__ import annotations

from .. import config, llamacpp, lmstudio, ollama, settings
from ..schemas_hub import LocalBackend


def local_backends() -> list[LocalBackend]:
    lm_installed, lm_running = lmstudio.installed(), lmstudio.refresh_status()
    lms = lmstudio.lms_exe()
    lm_detail = ("Not installed on this machine." if not lm_installed else
                 "Installed but never opened: open LM Studio once to finish its setup." if not lmstudio.set_up() else
                 f"`lms` CLI at {lms}" if lms else "LM Studio's `lms` CLI wasn't found; reinstall LM Studio.")
    cpp = llamacpp.server.status()
    ctx = settings.load().llamacpp_ctx_size
    ol_installed, ol_running, ol_version = ollama.refresh_status()
    return [
        LocalBackend(id="lmstudio", name="LM Studio", installed=lm_installed, running=lm_running,
                     version=lmstudio.version() if lm_installed else None,
                     endpoint=f"{lmstudio.API}/v1" if lm_running else None,
                     models_dir=str(lmstudio.models_dir()) if lm_installed else None, detail=lm_detail,
                     install_url=None if lm_installed else lmstudio.INSTALL_URL),
        LocalBackend(id="llamacpp", name="llama.cpp", installed=cpp.installed, running=cpp.running,
                     version=llamacpp.build_label(), endpoint=f"http://{config.HOST}:{cpp.port}/v1" if cpp.port else None,
                     models_dir=str(config.MODELS_DIR),
                     detail=f"Built-in llama-server: one GGUF at a time, layers fitted to free VRAM, {ctx:,}-token "
                            "context, tool calling through the model's chat template."),
        LocalBackend(id="ollama", name="Ollama", installed=ol_installed, running=ol_running, version=ol_version,
                     endpoint=config.OLLAMA_URL if ol_running else None,
                     detail="Its own model store; pulls Ollama library tags and Hugging Face GGUFs.",
                     install_url=None if ol_installed else "https://ollama.com/download"),
    ]
