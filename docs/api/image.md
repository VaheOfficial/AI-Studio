# Image API

Types: [`apps/studio/src/api/contracts/image.ts`](../../apps/studio/src/api/contracts/image.ts) (mirrored by
`server/studio/schemas_image.py`). All image generation — local diffusers / HunyuanImage 3 workers, Tencent
HY-Image 3.5 and pinned OpenRouter image models — goes through one route and returns a `Job`.

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/image/models` | | `ImageModelProfile[]` — one per installed image model (local and cloud) |
| POST | `/api/image/generate` | `ImageGenerateRequest` | `Job` (kind=generate; outputs in `job.result.outputs`) |
| GET | `/api/image/stars` | | `string[]` — starred output ids, newest first |
| PUT | `/api/image/stars/{output_id}` | `{ starred: boolean }` | `204` |

The gallery reads `GET /api/outputs?kind=image&limit=1000` and deletes with `DELETE /api/outputs/{id}` (core API).

## Profiles
`ImageModelProfile` says what the selected model can do so the UI only shows controls that apply:
`modes` (`txt2img` / `img2img` / `inpaint` / `edit`), guidance kind (`cfg`, `true-cfg`, `distilled`, `none`),
negative-prompt support, step/guidance ranges, samplers (SD 1.x / SDXL only), native size + step multiple,
provider enum `options` (OpenRouter: `aspect_ratio`, `resolution`, `quality`, `output_format`), `max_images`
for reference edits, estimated `vram_gb` of the weights actually installed, cloud `cost`, and `notes` (license,
offload, gating, missing companions).

Local profiles come from the installed files: the pipeline class in `model_index.json` (or the base pipeline for
a single GGUF / safetensors denoiser, or the tensor names of a full single-file checkpoint), with
step-distilled checkpoints (FLUX schnell, Z-Image-Turbo, distilled FLUX.2 klein) detected from configs/names.
Qwen-Image 2.1 (`QwenImage21Pipeline`) is one pipeline for text-to-image and editing (up to three reference
images) and is sampled without guidance: its guidance default is 1 (off), 40 steps, sizes in multiples of 32.

## Runtime
The `image` environment (image and video workers) pins diffusers to a commit rather than a release
(`DIFFUSERS` in `server/studio/runtimes/envs.py`): the first one with Qwen-Image 2.1, installed from a source
archive. An environment installed for an earlier version of the app is brought up to date the first time one of
its runtimes is needed: its workers are stopped, the install changes only what differs, and the load continues
(`RuntimeManager._update_env`). The hub does not offer a pipeline whose class the installed diffusers lacks
(`envs.knows_diffusers_class`): the variant says so instead of downloading weights that can't be loaded.

## Generate / edit
`ImageGenerateRequest` = core `ImageRequest` + `mode`, `scheduler`, `images` (data URLs or
`/files/outputs/...` URLs; the first is the init image for img2img/inpaint, all are references for `edit`),
`mask` (PNG data URL, white = repaint), `strength`, `options`. Uploaded images and masks are saved under
`/files/outputs/inputs/` and recorded in the output's `params` (with the seed) so "reuse settings" can
reproduce a result.

While a local job denoises, the server pushes `{ type: "image.preview", job_id, step, total, image }` frames
(a ≤256 px JPEG data URL projected straight from the latent, no VAE decode) over `/api/ws`.

## Local weights (image worker)
`POST /load` to the diffusers worker carries, besides `model_id`, `path`, `offload`:
`pipeline_dir` (folder with `model_index.json`), `weights` + `weights_format` (`gguf` | `safetensors`) for a
single denoiser file loaded with `from_single_file` (GGUF via `GGUFQuantizationConfig`; fp8 safetensors kept in
fp8 with layerwise casting) and plugged into the base pipeline, `full_checkpoint` + `pipeline_class` for
SD 1.x / SDXL / SD3 single-file checkpoints, and `quant`. Pre-quantized diffusers repos (bitsandbytes NF4 /
int8) load through `from_pretrained`. The base pipeline for a denoiser file is found in the model folder (hub
companions) or in another installed diffusers model sharing the Hugging Face card's `base_model`.

`text_encoder` (`full` | `8bit` | `4bit`, from `InstalledModel.text_encoder`) says how the pipeline's large text
encoders (`text_encoder*` components of 2 GB or more) are held: `8bit` and `4bit` load them through bitsandbytes
(LLM.int8, NF4) instead of bf16 and hand them to the pipeline in place of the folder's. The first such load reads
the full weights and saves the quantized encoder in `<pipeline_dir>/.quantized/<component>-<mode>`; later loads
read that copy (a copy that fails to load is dropped and made again). Small encoders (CLIP) stay as they are.
The server's VRAM estimate (`image_models.vram_need_gb`) and the offload decision use the same mode.
`PATCH /api/models/{id}` with `{ "text_encoder": … }` changes it on an installed model: a loaded model is
unloaded and the change applies at its next load.

## Tencent HY-Image 3.5
Cloud only (no open weights), runtime `tencent-cloud`, installed from the catalog entry `hy-image-3.5` (nothing
is downloaded). Uses Tencent Cloud **TokenHub**: `POST /v1/wand/hunyuan-image/v35-generation` with
`Authorization: Bearer <tencent_api_key>` (a single TokenHub API key — no TC3 SecretId/SecretKey signing),
`model: "hy-image-v3.5-preview"`, `messages` (text + reference `image_url` parts), `size`, `seed`,
`generate_max_pixels`. The call is synchronous; the returned COS URL (valid 12 h) is downloaded into outputs.
International keys use `tokenhub-intl.tencentcloudmaas.com`, mainland keys `tokenhub.tencentmaas.com` — the
client tries both and remembers which one accepted the key. ≈ $0.024 per image (international).
