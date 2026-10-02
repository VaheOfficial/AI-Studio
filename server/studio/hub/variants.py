"""Group a repository's files into installable variants.

- GGUF: one variant per quant file, split ``-00001-of-0000N`` sets grouped, ``mmproj`` projectors attached.
- diffusers repos (``model_index.json``): the full pipeline per available precision (default, fp16, bf16…).
- Alternative transformer/UNet weights (GGUF or single-file ``.safetensors``) for image models: paired with the
  base pipeline's other components ("companions") so the image runtime can assemble a full pipeline.
- Transformers ``safetensors`` checkpoints, CTranslate2 (faster-whisper) and ONNX exports.

Everything here is pure: it works on ``{path: size}`` maps so it can be reasoned about without network access.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..schemas import ModelKind, RuntimeId, TextEncoderMode, WeightFormat

GIB = 2**30

# Text encoders of image pipelines can be held quantized (bitsandbytes, at load time). What is left of an
# encoder's size: its linear layers shrink to 8 or 4 bits, embeddings and norms stay as they are.
ENCODER_SCALE: dict[TextEncoderMode, float] = {"full": 1.0, "8bit": 0.56, "4bit": 0.34}
ENCODER_MIN_BYTES = 2 * GIB  # smaller encoders (CLIP) are left alone: nothing to gain

TASK_KINDS: dict[str, ModelKind] = {
    "text-generation": "text", "image-text-to-text": "text", "text2text-generation": "text",
    "text-to-image": "image", "image-to-image": "image",
    "text-to-speech": "voice", "audio-to-audio": "voice",
    "automatic-speech-recognition": "stt",
    "text-to-audio": "music",
}

GGUF_QUANT = re.compile(
    r"(?<![A-Za-z0-9])((?:UD-)?(?:IQ[1-4]_(?:XXS|XS|NL|S|M)|Q[2-8]_K(?:_(?:XXL|XL|L|M|S))?|Q[2-8]_[01]"
    r"|TQ[12]_0|MXFP4(?:_MOE)?|NVFP4|BF16|F16|F32))(?![A-Za-z0-9])", re.I)
_SHARD = re.compile(r"-(\d{5})-of-(\d{5})\.gguf$", re.I)
_PRECISION = re.compile(r"(?<![a-z0-9])(fp8(?:[_-]e4m3fn|[_-]e5m2)?|fp16|bf16|fp32|nf4|int8|int4)(?![a-z0-9])", re.I)
# diffusers component weights: name[.variant][-0000x-of-0000y].safetensors|bin, and their shard indexes
_WEIGHT = re.compile(r"^(?P<name>[^/.]+)(?:\.(?P<v>fp16|bf16|fp32|fp8|int8))?(?:-\d{5}-of-\d{5})?\.(?P<ext>safetensors|bin)$")
_INDEX = re.compile(r"^(?P<name>[^/.]+)\.(?P<ext>safetensors|bin)\.index(?:\.(?P<v>fp16|bf16|fp32|fp8|int8))?\.json$")
_AUX_EXT = (".json", ".txt", ".model", ".jinja", ".tiktoken", ".py")
_SINGLE_FILE_MIN = 500 * 2**20  # root checkpoints smaller than this are VAEs/LoRAs, not models
# Single-file image weights the diffusers runtime can't read: Apple MLX, and quantizations ComfyUI nodes define
_FOREIGN = re.compile(r"(?<![a-z0-9])(mlx|nvfp4|svdq|int8|int4|nf4)(?![a-z0-9])", re.I)
LLM_RUNTIMES: list[RuntimeId] = ["llamacpp", "lmstudio", "ollama"]


@dataclass
class Draft:
    """A variant before machine fit / install state are known."""

    id: str
    label: str
    format: WeightFormat
    kind: ModelKind
    files: list[str]
    size: int
    runtimes: list[RuntimeId]
    quant: str | None = None
    note: str | None = None
    # Alternative denoiser weights: the base diffusers pipeline's other components must come with it.
    needs_base: bool = False
    notes: list[str] = field(default_factory=list)


def slug(text: str) -> str:
    """Model-id-safe form of a repo or file name: "Qwen3-8B-Q4_K_M" -> "qwen3-8b-q4-k-m"."""
    return re.sub(r"[^a-z0-9.]+", "-", text.lower()).strip("-.")


def kind_of(task: str | None, tags: list[str]) -> ModelKind | None:
    if task in TASK_KINDS:
        return TASK_KINDS[task]
    if any(t in tags for t in ("text-to-image", "image-generation", "diffusers")):
        return "image"
    return None


def formats_from_tags(tags: list[str]) -> list[WeightFormat]:
    table: list[tuple[str, WeightFormat]] = [("gguf", "gguf"), ("diffusers", "diffusers"), ("ctranslate2", "ct2"),
                                              ("onnx", "onnx"), ("safetensors", "safetensors"), ("mlx", "other")]
    return [fmt for tag, fmt in table if tag in tags]


def gguf_quant(name: str) -> str | None:
    found = GGUF_QUANT.findall(name.rsplit("/", 1)[-1])
    if not found:
        return None
    q = found[-1]
    return "UD-" + q[3:].upper() if q.upper().startswith("UD-") else q.upper()


def _vram_estimate(d: Draft, companions: int) -> float:
    gb = (d.size + companions) / GIB
    if d.kind == "text" and d.format in ("gguf", "ollama"):
        return gb * 1.08 + 1.5  # weights + KV cache for a 16K context
    if d.format == "ct2":
        return gb * 1.45
    return gb * 1.1 + (0.0 if d.kind == "image" else 0.5)


def vram_gb(d: Draft, companions: int = 0) -> float:
    return round(_vram_estimate(d, companions), 1)


# ------------------------------------------------------------------ GGUF


def _gguf(files: dict[str, int], kind: ModelKind | None) -> list[Draft]:
    ggufs = {p: s for p, s in files.items() if p.lower().endswith(".gguf")}
    projectors = sorted((p for p in ggufs if "mmproj" in p.lower().rsplit("/", 1)[-1]),
                        key=lambda p: ("f16" not in p.lower(), "bf16" not in p.lower(), ggufs[p]))
    groups: dict[str, list[str]] = {}
    for p in sorted(ggufs):
        if p in projectors:
            continue
        groups.setdefault(_SHARD.sub("", p).removesuffix(".gguf").removesuffix(".GGUF"), []).append(p)
    image = kind == "image"
    labels = [gguf_quant(stem) or stem.rsplit("/", 1)[-1] for stem in groups]
    drafts: list[Draft] = []
    for (stem, parts), label in zip(groups.items(), labels):
        if labels.count(label) > 1:
            label = stem.rsplit("/", 1)[-1]
        split = len(parts) > 1
        d = Draft(id=f"gguf:{stem}", label=label, format="gguf", kind=kind or "text", files=list(parts),
                  size=sum(ggufs[p] for p in parts), runtimes=[], quant=gguf_quant(stem))
        if image:
            d.runtimes, d.needs_base = ["diffusers"], True
        elif kind in (None, "text"):
            d.runtimes = [r for r in LLM_RUNTIMES if not (split and r == "ollama")]
            if split:
                d.notes.append(f"Split into {len(parts)} files; Ollama can't import split GGUFs.")
            if projectors:
                d.files.append(projectors[0])
                d.size += ggufs[projectors[0]]
                d.notes.append("Includes the vision projector (image input).")
        else:
            d.notes.append("GGUF builds of speech/audio models need runtimes the studio doesn't ship.")
        drafts.append(d)
    return sorted(drafts, key=lambda d: d.size)


# --------------------------------------------------------------- diffusers


def _components(files: dict[str, int]) -> dict[str, list[str]]:
    comps: dict[str, list[str]] = {}
    for p in files:
        if "/" in p:
            comps.setdefault(p.split("/", 1)[0], []).append(p)
    return comps


def _weight_variant(name: str) -> tuple[bool, str | None, str | None]:
    """(is weight or shard index, precision variant, extension)."""
    for rx in (_WEIGHT, _INDEX):
        m = rx.match(name)
        if m:
            return True, m.group("v"), m.group("ext")
    return False, None, None


def pipeline_files(files: dict[str, int], precision: str | None = None, skip: str | None = None,
                   configs_only: bool = False) -> list[str]:
    """Files of a diffusers pipeline at ``precision`` (falling back to default weights per component);
    ``skip`` leaves out one component's weights (replaced by other weights), ``configs_only`` all of them."""
    out = ["model_index.json"] if "model_index.json" in files else []
    for comp, paths in sorted(_components(files).items()):
        weights: list[tuple[str, str | None, str | None]] = []
        for p in paths:
            rel = p.split("/", 1)[1]
            is_weight, v, ext = _weight_variant(rel) if "/" not in rel else (False, None, None)
            if is_weight:
                weights.append((p, v, ext))
            elif p.lower().endswith(_AUX_EXT):
                out.append(p)
        if configs_only or comp == skip or not weights:
            continue
        has_safetensors = any(ext == "safetensors" for _, _, ext in weights)
        usable = [(p, v) for p, v, ext in weights if ext == "safetensors" or not has_safetensors]
        chosen = [p for p, v in usable if v == precision] or [p for p, v in usable if v is None]
        out += chosen
    return sorted(set(out))


def _precisions(files: dict[str, int]) -> list[str | None]:
    found: set[str | None] = set()
    for comp_paths in _components(files).values():
        for p in comp_paths:
            is_weight, v, _ = _weight_variant(p.split("/", 1)[1])
            if is_weight:
                found.add(v)
    return sorted(found, key=lambda v: (v is not None, v or ""))


def _diffusers(files: dict[str, int], kind: ModelKind | None) -> list[Draft]:
    runtimes: list[RuntimeId] = ["diffusers"] if kind in ("image", None) else []
    drafts = []
    for precision in _precisions(files):
        paths = pipeline_files(files, precision)
        d = Draft(id=f"diffusers:{precision or 'default'}", label=f"Full pipeline{f' · {precision}' if precision else ''}",
                  format="diffusers", kind=kind or "image", files=paths, size=sum(files[p] for p in paths),
                  runtimes=runtimes, quant=precision)
        if not runtimes:
            d.notes.append("The studio's diffusers runtime only runs image pipelines.")
        drafts.append(d)
    return drafts


def _single_files(files: dict[str, int], kind: ModelKind | None) -> list[Draft]:
    if kind != "image":
        return []
    drafts = []
    for p, size in files.items():
        if "/" in p or not p.lower().endswith(".safetensors") or size < _SINGLE_FILE_MIN:
            continue
        m = _PRECISION.search(p)
        quant = m.group(1).lower().replace("-", "_") if m else None
        d = Draft(id=f"file:{p}", label=p.removesuffix(".safetensors"), format="safetensors", kind="image",
                  files=[p], size=size, runtimes=["diffusers"], quant=quant, needs_base=True)
        foreign = _FOREIGN.search(p)
        if foreign:  # a safetensors file is only a container: these hold weights packed for another runtime
            d.runtimes, d.needs_base = [], False
            d.notes.append("MLX weights run on Apple Silicon only." if foreign.group(1).lower() == "mlx" else
                           f"{foreign.group(1).upper()} files are packed for ComfyUI; the image runtime loads GGUF, "
                           "fp8 and full-precision weights. Pick a GGUF build instead.")
        drafts.append(d)
    return sorted(drafts, key=lambda d: d.size)


# ------------------------------------------------------------ other formats


_QUANT_TAGS = {"awq": "AWQ", "gptq": "GPTQ", "bitsandbytes": "bnb", "fp8": "FP8", "exl2": "EXL2", "mlx": "MLX",
               "compressed-tensors": "compressed"}


def _transformers(files: dict[str, int], kind: ModelKind | None, tags: list[str]) -> list[Draft]:
    if "omnivoice" in tags:  # k2-fsa OmniVoice layout: the model plus its audio_tokenizer/ subfolder
        paths = sorted(p for p in files if p.endswith((".json", ".safetensors", ".jinja")))
        return [Draft(id="omnivoice", label="OmniVoice weights", format="safetensors", kind="voice", files=paths,
                      size=sum(files[p] for p in paths), runtimes=["omnivoice"],
                      notes=["OmniVoice weights are usually CC-BY-NC (non-commercial) — check the model card."])]
    root = {p: s for p, s in files.items() if "/" not in p}
    weights = [p for p in root if p.endswith(".safetensors")]
    if "config.json" not in root or not weights or "model_index.json" in files:
        return []
    paths = sorted(weights + [p for p in root if p.lower().endswith(_AUX_EXT)])
    quant = next((label for tag, label in _QUANT_TAGS.items() if tag in tags), None)
    d = Draft(id="safetensors", label=f"Transformers weights{f' · {quant}' if quant else ''}", format="safetensors",
              kind=kind or "text", files=paths, size=sum(root[p] for p in paths), runtimes=[], quant=quant)
    if (kind or "text") == "text" and quant is None:
        d.runtimes = ["ollama"]
        d.notes.append("Imported into Ollama (converted and quantized to Q8_0); architectures Ollama can't convert "
                       "fail — a GGUF build is the reliable choice.")
    elif quant == "MLX":
        d.notes.append("MLX weights run on Apple Silicon only.")
    elif quant:
        d.notes.append(f"{quant} checkpoints need vLLM/SGLang-style servers that don't run on Windows here; "
                       "pick a GGUF build instead.")
    else:
        d.notes.append("No studio runtime loads raw transformers weights for this task.")
    return [d]


def _ct2(files: dict[str, int], kind: ModelKind | None, tags: list[str]) -> list[Draft]:
    if "model.bin" not in files or not ("ctranslate2" in tags or any(p.startswith("vocabulary") for p in files)):
        return []
    paths = sorted(p for p in files if "/" not in p and not p.lower().endswith((".md", ".gitattributes")))
    whisper = kind == "stt" or "whisper" in " ".join(tags)
    d = Draft(id="ct2", label="CTranslate2", format="ct2", kind=kind or "stt", files=paths,
              size=sum(files[p] for p in paths), runtimes=["faster-whisper"] if whisper else [])
    if not whisper:
        d.notes.append("Only Whisper CTranslate2 models run here (faster-whisper).")
    return [d]


def _onnx(files: dict[str, int], kind: ModelKind | None) -> list[Draft]:
    paths = sorted(p for p in files if p.lower().endswith((".onnx", ".onnx_data", ".onnx.data")))
    if not paths:
        return []
    paths += sorted(p for p in files if p.lower().endswith((".json", ".txt", ".model")))
    return [Draft(id="onnx", label="ONNX export", format="onnx", kind=kind or "text", files=paths,
                  size=sum(files[p] for p in paths), runtimes=[],
                  notes=["The studio has no ONNX runtime; use the PyTorch or GGUF build."])]


def group(files: dict[str, int], kind: ModelKind | None, tags: list[str]) -> list[Draft]:
    """All variants found in a repo's files (without companions, fit or install state)."""
    drafts: list[Draft] = []
    if "model_index.json" in files:
        drafts += _diffusers(files, kind)
    drafts += _gguf(files, kind)
    drafts += _single_files(files, kind)
    drafts += _transformers(files, kind, tags)
    drafts += _ct2(files, kind, tags)
    if not drafts:
        drafts += _onnx(files, kind)
    for d in drafts:
        d.note = " ".join(d.notes) or None
    return drafts


def encoder_bytes(files: dict[str, int], chosen: list[str]) -> int:
    """Bytes of the large text encoders among ``chosen`` files of a diffusers pipeline (``files``: path → size)."""
    per_component: dict[str, int] = {}
    for p in chosen:
        comp, _, rel = p.partition("/")
        if comp.startswith("text_encoder") and rel and _weight_variant(rel)[0] and not rel.endswith(".json"):
            per_component[comp] = per_component.get(comp, 0) + files.get(p, 0)
    return sum(size for size in per_component.values() if size >= ENCODER_MIN_BYTES)


def companion_files(base: dict[str, int], d: Draft) -> tuple[list[str], str | None]:
    """Base-pipeline files that must accompany denoiser weights ``d``, plus a note. DiT pipelines (a
    ``transformer`` component) take everything except the transformer weights; UNet pipelines' single-file
    checkpoints already hold every component, so only configs and tokenizers are needed."""
    comps = _components(base)
    if "transformer" in comps:
        return pipeline_files(base, skip="transformer"), None
    if "unet" in comps and d.format == "safetensors":
        return pipeline_files(base, configs_only=True), "Single-file checkpoint (UNet, text encoders and VAE in one file)."
    if "unet" in comps:
        return pipeline_files(base, skip="unet"), None
    return [], "The base pipeline has no transformer or UNet to replace."


def detect(files: list[str]) -> tuple[WeightFormat, str | None]:
    """Format and precision/quant label of an already-downloaded file set."""
    lowered = [f.lower() for f in files]
    ggufs = [f for f in files if f.lower().endswith(".gguf") and "mmproj" not in f.lower()]
    if ggufs:
        return "gguf", gguf_quant(ggufs[0])
    if "model_index.json" in lowered:
        precisions = {v for f in files if "/" in f for is_w, v, _ in [_weight_variant(f.split("/", 1)[1])] if is_w}
        return "diffusers", next(iter(precisions)) if len(precisions) == 1 else None
    if "model.bin" in lowered and any(f.startswith("vocabulary") for f in lowered):
        return "ct2", None
    if any(f.endswith(".safetensors") for f in lowered):
        return "safetensors", None
    if any(f.endswith(".onnx") for f in lowered):
        return "onnx", None
    return "other", None
