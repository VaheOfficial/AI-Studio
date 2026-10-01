# Video API

Types: [`apps/studio/src/api/contracts/video.ts`](../../apps/studio/src/api/contracts/video.ts), mirrored by
`server/studio/schemas_video.py`. Video models have `kind: "video"` and run on the `diffusers-video` runtime
(`server/workers/video_worker.py`, in the `image` environment — diffusers 0.40 has the Wan 2.2 and LTX-2 pipelines).
Outputs have `kind: "video"`: H.264 MP4 under `/files/outputs/videos/`, encoded by the studio's ffmpeg (its path is
sent with each request, so the environment needs no video libraries).

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/video/models` | | `VideoModelProfile[]` — installed video models: native size, speed, segment length and which LTX extras are installed |
| POST | `/api/video/generate` | `VideoRequest` | `Job` (kind=generate); the clip arrives in `job.result.outputs` |

Nothing is a fixed preset. `VideoRequest`:

- `width` × `height`: any size up to 3840 on a side (default: the native size), rounded to a multiple of 32 (64 when
  two-stage, so the half-size pass also fits).
- `duration_s`: up to 120 s. Clips longer than the model's `segment_seconds` (Wan 5 s, LTX 10 s) are made in
  segments: each continues from the previous segment's last frame (image-to-video, the repeated first frame dropped)
  and the parts are joined without re-encoding.
- `auto_duration` (LTX-2.5): the duration head picks the length, `duration_s` (≤ 20 s) is the upper bound.
- `upscale` (LTX-2.5): two-stage generation — render at half size, upsample the latents 2× with the latent upsampler,
  refine with the stage-2 schedule. `null` = automatic above 1280×720.
- `enhance_prompt` (LTX-2.5): LTX's own Gemma prompt enhancer rewrites the prompt once (T2V or I2V system prompt);
  every segment uses that text, and it is saved as `params.enhanced_prompt`.
- `decoder` (LTX-2.5): `vae` or `diffusion` — the diffusion decoder (sharper, slower; tiled).
- `mode` `t2v` / `i2v` (`image`: a data URL or `/files/outputs/...` URL, scaled and centre-cropped to the size);
  `steps`/`guidance` for Wan (LTX's distilled transformer runs fixed schedules without guidance).

Frame counts are rounded to what the model needs: 4n+1 for Wan, 8n+1 for LTX.

## Models

| Catalog id | Model | Notes |
|---|---|---|
| `ltx-2.5` | LTX-2.5 (Lightricks), 22B | Video **with audio**. Transformer: a Q5_K_S GGUF (`vantagewithai/LTX-2.5-GGUF`, a catalog `extras` source); text encoder in 4-bit NF4; everything else — duration head, prompt enhancer, latent upsampler, diffusion decoder — from the gated `Lightricks/LTX-2.5-Diffusers` (accept its terms, set an HF token). Native 960×544 at 24 fps. |
| `wan2.2-ti2v-5b` | Wan 2.2 TI2V 5B (Alibaba), Apache 2.0 | Text- and image-to-video in one model, silent. Native 1280×704 at 24 fps; 40 steps and guidance 5 by default. |

Both load with model CPU offload and tiled VAE decoding. LTX-2.5's text encoder is quantized to 4-bit on its first
load and saved to `<model>/text_encoder_nf4` (~7 GB), which later loads read directly; the prompt enhancer, latent
upsampler and diffusion decoder load on first use and sit on the GPU only while they run. Audio is muxed at the
model's own level (48 kHz stereo, no normalization); the worker logs its peak and RMS.

- **Image-to-video** re-compresses the start frame with H.264 at CRF 18 (what LTX-2.5 was trained on; diffusers
  picks it from the Gemma 4 text encoder), which needs PyAV (`av`, part of the `image` env).
- **Diffusion decoder**: diffusers runs its 3D neighborhood attention through FlexAttention, which without Triton
  (Windows) falls back to an eager path that builds the full score matrix — ~56 GiB for 4 s at 960×544. The worker
  swaps in `workers/ltx_attention.py`, the same attention (window centred, shifted inward at the borders) computed
  block by block with SDPA; it matches diffusers' output to float precision and its memory follows the block size.

The diffusers 0.40 LTX-2 converter doesn't know LTX-2.5's `prompt_adaln_single` / `audio_prompt_adaln_single` names; the worker renames
them to `prompt_adaln` / `audio_prompt_adaln` before loading the GGUF.

Measured on an RTX 4090, models on a USB drive (`seconds_per_mpx_frame` in the profiles comes from these):

| | Load | Generation | Peak VRAM |
|---|---|---|---|
| Wan 2.2 5B, 832×480, 3 s, 20 steps | ~2.5 min | 80 s | 14 GB |
| LTX-2.5, 960×544, 5 s with audio | ~12 min first time (builds the 4-bit cache), ~4.7 min after | 155–162 s | 18.4 GB |

The agent's `generate_video(prompt, image?, duration_s?, width?, height?, portrait?, model_id?)` tool uses the
`video` default from `Settings.default_models`, else the first installed video model.
