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

## Tencent HY-Image 3.5
Cloud only (no open weights), runtime `tencent-cloud`, installed from the catalog entry `hy-image-3.5` (nothing
is downloaded). Uses Tencent Cloud **TokenHub**: `POST /v1/wand/hunyuan-image/v35-generation` with
`Authorization: Bearer <tencent_api_key>` (a single TokenHub API key — no TC3 SecretId/SecretKey signing),
`model: "hy-image-v3.5-preview"`, `messages` (text + reference `image_url` parts), `size`, `seed`,
`generate_max_pixels`. The call is synchronous; the returned COS URL (valid 12 h) is downloaded into outputs.
International keys use `tokenhub-intl.tencentcloudmaas.com`, mainland keys `tokenhub.tencentmaas.com` — the
client tries both and remembers which one accepted the key. ≈ $0.024 per image (international).
