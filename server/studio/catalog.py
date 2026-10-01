"""Curated model catalog. Sizes are download sizes (checked against the HF API / Ollama library
in Sept 2026); ``vram_gb`` is what the model needs to run fully on GPU at the precision we load it."""

from __future__ import annotations

from dataclasses import dataclass, field

from . import db, system
from .schemas import CatalogEntry, Fit, ModelKind, ModelSource, RuntimeId

# Diffusers repos: take only the per-component subfolders, never the duplicate single-file
# checkpoints at the repo root, and skip non-PyTorch formats.
DIFFUSERS_PATTERNS = ["model_index.json", "*/*.json", "*/*.safetensors", "*/*.txt", "*/*.model", "*/*.jinja"]
TRANSFORMERS_PATTERNS = ["*.json", "*.safetensors", "*.txt", "*.model", "*.py", "*.jinja", "*.tiktoken"]

GIB = 2**30


@dataclass(frozen=True)
class Spec:
    id: str
    name: str
    vendor: str
    kind: ModelKind
    runtime: RuntimeId
    source: ModelSource
    description: str
    size_gb: float
    vram_gb: float
    license: str
    tags: list[str] = field(default_factory=list)
    params: str | None = None
    notes: str | None = None
    featured: bool = False
    # Name of the Ollama model created from an HF download (hf -> `ollama create`).
    ollama_name: str | None = None
    # More files from other repos, downloaded into the same folder (repo paths kept), e.g. a quantized transformer
    extras: tuple[ModelSource, ...] = ()

    @property
    def ollama_tag(self) -> str | None:
        if self.runtime != "ollama":
            return None
        return self.ollama_name or self.source.repo


def _ollama(id: str, name: str, vendor: str, tag: str, desc: str, size: float, vram: float, lic: str,
            tags: list[str], params: str, notes: str | None = None, featured: bool = False) -> Spec:
    return Spec(id=id, name=name, vendor=vendor, kind="text", runtime="ollama",
                source=ModelSource(type="ollama", repo=tag), description=desc, size_gb=size, vram_gb=vram,
                license=lic, tags=tags, params=params, notes=notes, featured=featured)


def _hf(repo: str, patterns: list[str] | None = None) -> ModelSource:
    return ModelSource(type="hf", repo=repo, allow_patterns=patterns)


SPECS: list[Spec] = [
    # ------------------------------- text -------------------------------
    _ollama("qwen3-0.6b", "Qwen3 0.6B", "Alibaba Qwen", "qwen3:0.6b",
            "Tiny Qwen3 with thinking and tool calling. Handy for smoke tests and very fast replies.",
            0.52, 1.5, "Apache-2.0", ["chat", "tools", "thinking", "tiny"], "0.6B",
            notes="Very small: fine for quick tests, unreliable for multi-step agent work."),
    _ollama("qwen3-8b", "Qwen3 8B", "Alibaba Qwen", "qwen3:8b",
            "Strong general-purpose 8B model with hybrid thinking and reliable tool calling.",
            5.2, 7, "Apache-2.0", ["chat", "tools", "thinking"], "8B"),
    _ollama("qwen3-30b-a3b", "Qwen3 30B-A3B", "Alibaba Qwen", "qwen3:30b-a3b",
            "Mixture-of-experts with 3B active parameters: 30B-class quality at small-model speed.",
            18.6, 21, "Apache-2.0", ["chat", "tools", "thinking", "moe"], "30B MoE (3B active)", featured=True,
            notes="Q4_K_M. Fits a 24 GB GPU with moderate context; long contexts spill to CPU."),
    _ollama("gemma3-27b", "Gemma 3 27B", "Google", "gemma3:27b",
            "Google's multimodal 27B model (text + image input) with 128K context.",
            17, 20, "Gemma Terms of Use", ["chat", "vision"], "27B",
            notes="Ollama reports no native tool-calling template for Gemma 3; best used in chat mode."),
    _ollama("gpt-oss-20b", "gpt-oss 20B", "OpenAI", "gpt-oss:20b",
            "OpenAI's open-weight reasoning model (MXFP4 MoE) with native tool use.",
            14, 16, "Apache-2.0", ["chat", "tools", "thinking", "moe"], "21B MoE (3.6B active)"),
    _ollama("llama3.1-8b", "Llama 3.1 8B", "Meta", "llama3.1:8b",
            "Meta's widely used 8B instruct model with tool calling.",
            4.9, 6.5, "Llama 3.1 Community License", ["chat", "tools"], "8B"),
    # Pulled as the official llama.cpp GGUF: Ollama 0.32's safetensors importer mis-converts the qwen3_5
    # architecture (the resulting model fails with "missing tensor blk.32.attn_norm.weight").
    _ollama("mimo-v2.6-distill-qwen-9b", "MiMo V2.6 Distill (Qwen 9B)", "Xiaomi MiMo",
            "hf.co/ggml-org/MiMo-V2.6-Distill-Qwen-9B-GGUF:Q8_0",
            "MiMo V2.6 reasoning distilled into a 9B Qwen-based model. Runs great on a 24 GB GPU.",
            10.1, 12, "MIT", ["chat", "reasoning", "thinking"], "9B", featured=True,
            notes="Q8_0 GGUF from ggml-org (the llama.cpp team), pulled directly by Ollama."),
    Spec(id="mimo-v2.6-flash-rl", name="MiMo V2.6 Flash RL", vendor="Xiaomi MiMo", kind="text", runtime="remote",
         source=ModelSource(type="remote", repo="XiaomiMiMo/MiMo-V2.6-Flash-RL"),
         description="Xiaomi's fast MoE flagship (256 experts, 8 active per token, 1M context).",
         size_gb=177.8, vram_gb=190, license="MIT", tags=["chat", "reasoning", "moe", "remote"],
         params="MoE, 256 experts (8 active)",
         notes=("178 GB of FP8 weights in a custom mimo_v2 architecture: it does not fit 24 GB VRAM + 64 GB RAM "
                "and Ollama cannot run it. Use it through an OpenAI-compatible endpoint (Xiaomi's API or a "
                "rented multi-GPU vLLM/SGLang server) set in Settings → OpenAI base URL. Local install is disabled.")),
    Spec(id="mimo-v2.6-pro-rl", name="MiMo V2.6 Pro RL", vendor="Xiaomi MiMo", kind="text", runtime="remote",
         source=ModelSource(type="remote", repo="XiaomiMiMo/MiMo-V2.6-Pro-RL"),
         description="Xiaomi's frontier 1.02T-parameter MoE reasoning model.",
         size_gb=573.5, vram_gb=600, license="MIT", tags=["chat", "reasoning", "moe", "remote"],
         params="1.02T MoE (42B active)",
         notes=("~574 GB of FP8/MXFP4 weights; needs a multi-GPU datacenter node (vLLM on 8×H200 class). "
                "Not installable locally. Use it via an OpenAI-compatible endpoint (Xiaomi's API or a rented vLLM "
                "box) configured in Settings, then pick it under the openai: provider.")),
    # ------------------------------- image -------------------------------
    Spec(id="hunyuan-image-3-instruct-distil", name="HunyuanImage 3.0 Instruct (Distil)", vendor="Tencent",
         kind="image", runtime="hunyuan-image3",
         source=_hf("tencent/HunyuanImage-3.0-Instruct-Distil", TRANSFORMERS_PATTERNS),
         description="Native multimodal autoregressive image model with instruction following and reasoning.",
         size_gb=168.7, vram_gb=170, license="Tencent Hunyuan Community License",
         tags=["text-to-image", "moe", "autoregressive"], params="80B MoE (13B active)",
         notes=("~169 GB of bf16 weights; Tencent recommends ≥3×80 GB GPUs. On 24 GB VRAM + 64 GB RAM it exceeds "
                "even CPU offload and would need disk offload (minutes to hours per image) — effectively "
                "unusable here. The community INT8 build EricRollei/Hunyuan_Image_3_Int8 (~87 GB) halves the "
                "footprint but is still larger than this machine's VRAM+RAM budget.")),
    Spec(id="hunyuan-image-2.1", name="HunyuanImage 2.1", vendor="Tencent", kind="image", runtime="diffusers",
         source=_hf("hunyuanvideo-community/HunyuanImage-2.1-Diffusers", DIFFUSERS_PATTERNS),
         description="17B diffusion transformer generating native 2K images with strong prompt adherence.",
         size_gb=53.1, vram_gb=36, license="Tencent Hunyuan Community License",
         tags=["text-to-image", "2k"], params="17B DiT",
         notes=("Transformer alone is ~35 GB bf16, so on 24 GB it runs with model CPU offload (noticeably slower). "
                "Loaded through diffusers' HunyuanImagePipeline.")),
    Spec(id="flux1-schnell", name="FLUX.1 [schnell]", vendor="Black Forest Labs", kind="image", runtime="diffusers",
         source=_hf("black-forest-labs/FLUX.1-schnell", DIFFUSERS_PATTERNS),
         description="12B rectified-flow transformer distilled for 1–4 step generation.",
         size_gb=33.7, vram_gb=33, license="Apache-2.0", tags=["text-to-image", "fast"], params="12B",
         featured=True,
         notes=("Use 4 steps and guidance 0. The HF repo asks you to accept its terms: accept them on "
                "huggingface.co and set an HF token in Settings. Runs with model CPU offload on 24 GB.")),
    Spec(id="qwen-image", name="Qwen-Image", vendor="Alibaba Qwen", kind="image", runtime="diffusers",
         source=_hf("Qwen/Qwen-Image", DIFFUSERS_PATTERNS),
         description="20B MMDiT image model, excellent at rendering text (English and Chinese) in images.",
         size_gb=57.7, vram_gb=58, license="Apache-2.0", tags=["text-to-image", "text-rendering"],
         params="20B MMDiT + 7B text encoder",
         notes="~58 GB bf16: needs CPU offload on 24 GB (slow, ~1–3 min per 1024² image)."),
    Spec(id="sdxl-base-1.0", name="Stable Diffusion XL 1.0", vendor="Stability AI", kind="image",
         runtime="diffusers",
         source=_hf("stabilityai/stable-diffusion-xl-base-1.0", [
             "model_index.json", "scheduler/*", "tokenizer/*", "tokenizer_2/*",
             "text_encoder/config.json", "text_encoder/model.fp16.safetensors",
             "text_encoder_2/config.json", "text_encoder_2/model.fp16.safetensors",
             "unet/config.json", "unet/diffusion_pytorch_model.fp16.safetensors",
             "vae/config.json", "vae/diffusion_pytorch_model.fp16.safetensors",
         ]),
         description="The classic 1024² latent diffusion model with a huge ecosystem.",
         size_gb=6.9, vram_gb=8, license="CreativeML Open RAIL++-M", tags=["text-to-image", "classic"],
         params="3.5B", featured=True, notes="fp16 weights only (~7 GB instead of the 77 GB full repo)."),
    Spec(id="flux2-klein-4b", name="FLUX.2 [klein] 4B", vendor="Black Forest Labs", kind="image",
         runtime="diffusers", source=_hf("black-forest-labs/FLUX.2-klein-4B", DIFFUSERS_PATTERNS),
         description="Step-distilled 4B FLUX.2: 4-step text-to-image plus multi-reference editing.",
         size_gb=16.0, vram_gb=18.5, license="Apache-2.0", tags=["text-to-image", "image-editing", "fast"],
         params="4B + Qwen3 4B text encoder", featured=True,
         notes=("Runs fully on a 24 GB GPU at 4 steps. Smaller GGUF quants of the transformer: "
                "unsloth/FLUX.2-klein-4B-GGUF.")),
    Spec(id="z-image-turbo", name="Z-Image-Turbo", vendor="Tongyi-MAI (Alibaba)", kind="image", runtime="diffusers",
         source=_hf("Tongyi-MAI/Z-Image-Turbo", DIFFUSERS_PATTERNS),
         description="6B single-stream DiT distilled to 8 steps; photorealism and bilingual text rendering.",
         size_gb=32.9, vram_gb=23, license="Apache-2.0", tags=["text-to-image", "fast", "text-rendering"],
         params="6B + Qwen3 4B text encoder", featured=True,
         notes=("The repo stores the transformer in fp32 (33 GB download); it loads as bf16 (~21 GB) and may use "
                "model CPU offload when other models hold VRAM. Smaller: unsloth/Z-Image-Turbo-GGUF.")),
    Spec(id="flux1-dev-nf4", name="FLUX.1 [dev] NF4", vendor="Black Forest Labs / diffusers", kind="image",
         runtime="diffusers", source=_hf("diffusers/FLUX.1-dev-bnb-4bit", DIFFUSERS_PATTERNS),
         description="FLUX.1 [dev] with a bitsandbytes NF4 transformer and 8-bit T5: full quality at ~half the VRAM.",
         size_gb=13.5, vram_gb=16, license="FLUX.1 [dev] Non-Commercial License",
         tags=["text-to-image", "quantized"], params="12B (NF4)", featured=True,
         notes=("Non-commercial license. Pre-quantized by the diffusers team (not gated, unlike the original repo). "
                "Also serves as the base components for FLUX.1-dev GGUF quants (city96/FLUX.1-dev-gguf).")),
    Spec(id="flux1-krea-dev", name="FLUX.1 Krea [dev]", vendor="Black Forest Labs / Krea", kind="image",
         runtime="diffusers", source=_hf("black-forest-labs/FLUX.1-Krea-dev", DIFFUSERS_PATTERNS),
         description="FLUX.1 [dev] fine-tuned with Krea for natural, less 'AI-looking' photography.",
         size_gb=33.7, vram_gb=33, license="FLUX.1 [dev] Non-Commercial License", tags=["text-to-image"],
         params="12B",
         notes=("Gated: accept the terms on huggingface.co and set an HF token in Settings. Non-commercial license. "
                "bf16 needs model CPU offload on 24 GB.")),
    Spec(id="hy-image-3.5", name="HY-Image 3.5 (Tencent Cloud)", vendor="Tencent", kind="image",
         runtime="tencent-cloud", source=ModelSource(type="remote", repo="hy-image-v3.5-preview"),
         description="Tencent's newest image model: up to 4K, reference-image editing. Cloud API only.",
         size_gb=0, vram_gb=0, license="Tencent Cloud service terms", tags=["text-to-image", "image-editing", "cloud"],
         featured=True,
         notes=("No open weights: runs on Tencent Cloud TokenHub with your API key (Settings → Tencent key). "
                "≈ $0.024 per image (international) — prompts and reference images are sent to Tencent.")),
    # ------------------------------- video -------------------------------
    Spec(id="ltx-2.5", name="LTX-2.5 (Q5 GGUF)", vendor="Lightricks", kind="video", runtime="diffusers-video",
         source=_hf("Lightricks/LTX-2.5-Diffusers", [
             "model_index.json", "modular_model_index.json", "scheduler/*", "tokenizer/*", "processor/*",
             "text_encoder/*", "connectors/*.json", "connectors/diffusion_pytorch_model-*.safetensors", "vae/*",
             "audio_vae/*", "vocoder/*", "transformer/config.json", "prompt_enhancer/*", "duration_head/*",
             "diffusion_decoder/*", "latent_upsampler/*", "temporal_latent_upsampler/*"]),
         extras=(_hf("vantagewithai/LTX-2.5-GGUF", ["distilled/ltx-2.5-22b-distilled-transformer-Q5_K_S.gguf"]),),
         description="Video with its own soundtrack (dialogue, effects, ambience) in one pass, from a prompt or a "
                     "start image. Distilled: 8 steps, about 3 minutes per 5 s clip on a 24 GB GPU.",
         size_gb=64.0, vram_gb=22, license="LTX-2 Community License (free under $10M annual revenue)",
         tags=["text-to-video", "image-to-video", "audio"], params="22B", featured=True,
         notes=("Gated: accept the terms on huggingface.co/Lightricks/LTX-2.5-Diffusers and set an HF token in "
                "Settings. The 22B transformer is a Q5_K_S GGUF (bf16 needs 44 GB); the Gemma text encoder loads in "
                "4-bit.")),
    Spec(id="wan2.2-ti2v-5b", name="Wan 2.2 TI2V 5B", vendor="Alibaba Wan", kind="video", runtime="diffusers-video",
         source=_hf("Wan-AI/Wan2.2-TI2V-5B-Diffusers", DIFFUSERS_PATTERNS),
         description="Open (Apache 2.0) 720p/24 fps video from a prompt or a start image, one model for both. "
                     "Silent; slower than LTX, strong detail.",
         size_gb=34.2, vram_gb=20, license="Apache-2.0", tags=["text-to-video", "image-to-video"], params="5B",
         notes="Runs with model CPU offload on 24 GB; several minutes per 5 s 720p clip."),
    # ------------------------------- voice -------------------------------
    Spec(id="kokoro-82m", name="Kokoro 82M", vendor="hexgrad", kind="voice", runtime="kokoro",
         source=_hf("hexgrad/Kokoro-82M", ["config.json", "kokoro-v1_0.pth", "voices/*.pt"]),
         description="Tiny, fast, high-quality TTS with ~50 preset voices.",
         size_gb=0.36, vram_gb=1, license="Apache-2.0", tags=["tts", "presets", "fast"], params="82M",
         featured=True, notes="Preset voices only (no cloning). English voices are exposed by default."),
    Spec(id="chatterbox", name="Chatterbox", vendor="Resemble AI", kind="voice", runtime="chatterbox",
         source=_hf("ResembleAI/chatterbox",
                    ["ve.safetensors", "t3_cfg.safetensors", "s3gen.safetensors", "tokenizer.json", "conds.pt"]),
         description="Zero-shot voice cloning TTS with emotion exaggeration control.",
         size_gb=3.2, vram_gb=5, license="MIT", tags=["tts", "cloning", "emotion"], params="0.5B",
         featured=True, notes="Clone any voice from a ≥3 s reference clip (10–20 s works best). English only."),
    Spec(id="omnivoice", name="OmniVoice", vendor="k2-fsa (Xiaomi)", kind="voice", runtime="omnivoice",
         source=ModelSource(type="hf", repo="k2-fsa/OmniVoice", revision="c5fdb5ccb189668d56333f77ba2629f4cd7535f4",
                            allow_patterns=["*.json", "*.safetensors", "*.jinja"]),
         description=("Zero-shot TTS in 646 languages: clone a voice from a 3–20 s clip, or design one from tags "
                      "(gender, age, pitch, accent, whisper). 24 kHz, non-verbal tags like [laughter]."),
         size_gb=3.27, vram_gb=6, license="Code Apache-2.0 · weights CC-BY-NC-4.0 (non-commercial)",
         tags=["tts", "cloning", "voice-design", "multilingual"], params="0.6B + audio codec", featured=True,
         notes=("Weights are CC-BY-NC (training data): personal / non-commercial use only. Includes the "
                "HiggsAudio v2 audio tokenizer. Pinned to the revision VoiceStudio ships.")),
    # -------------------------------- stt --------------------------------
    Spec(id="faster-whisper-large-v3", name="Whisper large-v3 (faster-whisper)", vendor="OpenAI / Systran",
         kind="stt", runtime="faster-whisper", source=_hf("Systran/faster-whisper-large-v3"),
         description="Most accurate Whisper, CTranslate2 build for fast GPU transcription.",
         size_gb=3.1, vram_gb=4.5, license="MIT", tags=["stt", "multilingual"], params="1.55B", featured=True),
    Spec(id="faster-whisper-small", name="Whisper small (faster-whisper)", vendor="OpenAI / Systran",
         kind="stt", runtime="faster-whisper", source=_hf("Systran/faster-whisper-small"),
         description="Small, fast multilingual Whisper for quick dictation.",
         size_gb=0.49, vram_gb=1.2, license="MIT", tags=["stt", "multilingual", "fast"], params="244M"),
    # -------------------------------- music -------------------------------
    Spec(id="ace-step-v1-3.5b", name="ACE-Step v1 3.5B", vendor="ACE Studio / StepFun", kind="music",
         runtime="ace-step", source=_hf("ACE-Step/ACE-Step-v1-3.5B", ["*.json", "*/*.json", "*/*.safetensors"]),
         description="Text-to-music foundation model: full songs with vocals from tags + lyrics.",
         size_gb=8.3, vram_gb=10, license="Apache-2.0", tags=["music", "vocals", "lyrics"], params="3.5B",
         featured=True, notes="Up to 4 minutes per generation; ~20 s for a 1-minute song on an RTX 4090."),
]

_BY_ID = {s.id: s for s in SPECS}


def get(catalog_id: str) -> Spec | None:
    return _BY_ID.get(catalog_id)


def by_ollama_tag(tag: str) -> Spec | None:
    return next((s for s in SPECS if s.ollama_tag == tag), None)


def compute_fit(vram_gb: float, runtime: RuntimeId) -> Fit:
    if runtime == "remote":
        return "no"
    vram = system.vram_total_bytes() / GIB
    ram = system.ram_total_bytes() / GIB
    if vram_gb <= vram * 0.95:
        return "yes"
    if vram_gb <= vram + 0.7 * ram:
        return "offload"
    return "no"


def entries() -> list[CatalogEntry]:
    installed_ids = {m.catalog_id for m in db.list_installed()}
    return [to_entry(s, s.id in installed_ids) for s in SPECS]


def to_entry(s: Spec, installed: bool) -> CatalogEntry:
    return CatalogEntry(
        id=s.id, name=s.name, vendor=s.vendor, kind=s.kind, runtime=s.runtime, source=s.source,
        description=s.description, params=s.params, size_gb=s.size_gb, vram_gb=s.vram_gb, license=s.license,
        tags=s.tags, fit=compute_fit(s.vram_gb, s.runtime), notes=s.notes, featured=s.featured or None,
        installed=installed,
    )
