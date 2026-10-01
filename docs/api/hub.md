# Model hub & local text runtimes

Types: [`apps/studio/src/api/contracts/hub.ts`](../../apps/studio/src/api/contracts/hub.ts) (mirrored by
`server/studio/schemas_hub.py`). Core additions in `types.ts`: `Settings.default_local_backend`,
`Settings.llamacpp_ctx_size`, `LocalBackendId`, and `ChatModelOption.provider` gained `lmstudio` / `llamacpp`.

## Hub
| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | `/api/hub/search` | `catalog=hf\|ollama\|lmstudio`, `q`, `task` (HF pipeline tag), `sort=trending\|downloads\|likes\|updated`, `gguf=true` | `HubSearchResult[]` (cached 5 min) |
| GET | `/api/hub/repo` | `source=hf\|ollama`, `id` | `HubRepo` with `variants` and `related` quantized repos |
| POST | `/api/hub/install` | `HubInstallRequest` | `Job` (kind=download, `ref` = the variant's `ref`) |
| GET | `/api/hub/backends` | | `LocalBackend[]` — LM Studio, llama.cpp, Ollama |

- `catalog=lmstudio` searches LM Studio's own GGUF uploads (`lmstudio-community` on Hugging Face — the files
  LM Studio's in-app catalog downloads). `catalog=ollama` parses ollama.com's public search / tags pages.
- Variants (see `server/studio/hub/variants.py`): one per GGUF quant (split sets grouped, `mmproj` projectors
  attached); a diffusers pipeline per precision (default / fp16 / bf16 …); single-file `.safetensors` checkpoints;
  transformers weights; CTranslate2; ONNX; plus a `catalog:<id>` "Studio preset" when the repo is in the curated
  catalog (installing it is the same as `POST /api/models/{catalog_id}/install`). Each has size, estimated VRAM,
  `fit`, the `runtimes` that can load it, and a `note` with honest caveats (no runtime for AWQ/MLX/ONNX, etc.).
- Gated repos (the repo or its companions' base repo): the install job checks access first and fails with a
  message + link; set `hf_token` in Settings.

## What an install records (`InstalledModel`)
| Variant | `runtime` | `path` | `format` / `quant` | `files` (relative to `path`) |
|---|---|---|---|---|
| GGUF LLM → llama.cpp | `llamacpp` | `data/models/<id>` | `gguf` / `Q4_K_M` | the GGUF (all shards) + `mmproj` |
| GGUF LLM → LM Studio | `lmstudio` | `<LM Studio models>/<org>/<repo>` | `gguf` / quant | same |
| GGUF LLM → Ollama | `ollama` | `ollama://hf.co/<repo>:<quant>` | `gguf` / quant | — (Ollama's store) |
| Ollama library tag | `ollama` | `ollama://<model>:<tag>` | `ollama` / quant if in the tag | — |
| diffusers pipeline | `diffusers` | `data/models/<id>` | `diffusers` / `fp16`… or none | pipeline files of that precision |
| image transformer GGUF / single file | `diffusers` | `data/models/<id>` | `gguf` or `safetensors` / quant | the weights file(s) at the root **plus** the base pipeline's companions (`model_index.json`, `text_encoder*/`, `tokenizer*/`, `vae/`, `scheduler/`, `transformer/config.json`) |

For the Image area: a quantized FLUX transformer install is a normal diffusers folder whose
`transformer/` has only `config.json`, with the GGUF/safetensors transformer weights at the root (the root file
listed first in `files`). For UNet (SD/SDXL) single-file checkpoints the companions are configs/tokenizers only.
`source_repo` is where the weights came from; companions come from the repo's `base_model`.

When an installed diffusers pipeline shares that base model (`image_models.installed_base`, the same rule the
loader uses), the variant has no `companions`: only the weights are downloaded and the loader pairs them with that
pipeline's text encoders, VAE and configs; the variant `note` names it. This also lets gated bases install without
an HF token — e.g. `city96/FLUX.1-dev-gguf` quants run on the ungated `diffusers/FLUX.1-dev-bnb-4bit` pipeline.

## Local text runtimes
- **llama.cpp** (`llamacpp`): `POST /api/runtimes/llamacpp/install` downloads the pinned official build
  (`b11259`, Windows CUDA 13.4 + cudart, SHA-256 verified) into `data/envs/llamacpp/<release>`; an update copies
  archives whose checksum didn't change (usually the 400+ MB cudart) from the previous build instead of downloading them.
  Loading a model starts `llama-server -m <gguf> --jinja -ngl auto --fit on -c <llamacpp_ctx_size>` (default 96K;
  `-ctk/-ctv q8_0` unless `llamacpp_kv_cache` is `f16`; with a vision projector above 64K, `--no-mmproj-offload` keeps
  it on the CPU so the context fits on the GPU — measured with Qwen3.8 27B Q4 on a 4090: 96K at ~82 tok/s, 128K at
  ~46, 256K at ~18 as layers move to the CPU) on a free
  local port (one model at a time; the process is bound to the studio server's lifetime). A GGUF that keeps its
  multi-token-prediction layers (`<arch>.nextn_predict_layers` > 0, read by `studio/gguf_meta.py`; most conversions
  drop them — look for "MTP" in the repo name) also gets `--spec-type draft-mtp --spec-draft-n-max 3 -np 1`: the
  model drafts 3 tokens per step and checks them in one pass. Measured with Qwen3.8 27B Q4 on a 4090 (b11259):
  37 tok/s plain → 70–103 tok/s. The single slot matters: with llama-server's default 4 slots (or 2) verifying a
  hybrid model's drafts cost about one decode per drafted token and drafting was slower than none. External
  drafters (DFlash 2, 1.1 GB) reached 48–81 tok/s with a fine-tuned target and aren't wired in; GGUFs whose
  architecture is a drafter (`dflash`, `eagle3`) are hidden from the chat model list and can't be loaded alone.
  NVFP4 GGUFs load too, but a 4090 has no FP4 tensor cores, so Q4_K/Q5_K are the better pick there.
  `POST /api/runtimes/llamacpp/stop` stops it. Chat provider id: `llamacpp:<installed model id>`.
- **LM Studio** (`lmstudio`): detected from the app / `~/.lmstudio/bin/lms.exe`. `POST /api/runtimes/lmstudio/install`
  runs `lms server start`; loading uses `lms load <library path> --identifier <model id>`; stop = `lms unload --all`.
  LLMs downloaded inside LM Studio are mirrored into `/api/models` (`lms ls --json`), and deleting removes only
  that model's files from LM Studio's library. Chat provider id: `lmstudio:<installed model id>`.
- `Settings.default_local_backend` (default `llamacpp`) is preselected for GGUF installs and orders local chat
  models first. `models.load()` / `_make_room` evict LLMs of all three runtimes before other models.
