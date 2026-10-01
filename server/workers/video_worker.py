"""Video runtime: Wan 2.2 (TI2V-5B: text- and image-to-video in one model) and LTX-2.5 (video with its own
audio) through diffusers. Frames (and LTX's audio) are encoded to H.264 MP4 by the studio's ffmpeg, whose path
comes with each request, so this env needs no video libraries of its own.

LTX-2.5 uses its whole checkpoint: the 22B transformer (GGUF), the 4-bit text encoder, the duration head (auto
length), the prompt enhancer, the latent upsampler (two-stage generation above the native size) and the diffusion
decoder (sharper decoding); the last three load on first use."""

from __future__ import annotations

import inspect
import json
import subprocess
import time
import wave
from pathlib import Path
from typing import Any

from ltx_attention import use_blocked_attention
from worker_base import BadRequest, Worker, free_cuda, log, serve

import numpy as np
import torch

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_NF4_TEXT_ENCODER = "text_encoder_nf4"  # cache of LTX's text encoder quantized to 4-bit (see _load_ltx2)
_LTX25_RENAMES = {"prompt_adaln_single": "prompt_adaln", "audio_prompt_adaln_single": "audio_prompt_adaln"}


def _gib(n: float) -> float:
    return round(n / 2**30, 2)


class VideoWorker(Worker):
    def __init__(self, runtime: str) -> None:
        super().__init__(runtime)
        self.pipe: Any = None
        self.path: Path | None = None
        self.family = ""  # "wan" | "ltx2"
        self.derived: dict[str, Any] = {}  # mode → pipeline sharing self.pipe's components
        self.armed: Any = None
        self.upsampler: Any = None  # LTX latent upsampler, loaded on first two-stage run
        self.decoder: Any = None  # LTX diffusion decoder, loaded on first use
        self.enhancer: Any = None  # LTX prompt enhancer, loaded on first use
        self.routes["/generate"] = self.generate
        if torch.cuda.is_available():
            # Windows' CUDA sysmem fallback would let an oversized allocation spill into system RAM, stalling the
            # whole machine; capped at the card's own memory it fails fast with an out-of-memory error instead
            torch.cuda.set_per_process_memory_fraction(0.98)

    # ------------------------------- loading -------------------------------

    def _load(self, req: dict[str, Any]) -> None:
        path = Path(req["path"])
        index = json.loads((path / "model_index.json").read_text(encoding="utf-8"))
        cls_name = index.get("_class_name", "")
        torch.cuda.reset_peak_memory_stats()
        if cls_name.startswith("LTX2"):
            self.family, pipe = "ltx2", self._load_ltx2(path, req.get("weights"))
        elif cls_name.startswith("Wan"):
            self.family, pipe = "wan", self._load_wan(path)
        else:
            raise BadRequest(f"Not a supported video model: {cls_name or path.name}")
        # Model offload: the text encoder, denoiser and VAE take turns on the GPU (together they are larger than it)
        pipe.enable_model_cpu_offload()
        vae = getattr(pipe, "vae", None)
        if vae is not None and hasattr(vae, "enable_tiling"):
            vae.enable_tiling()  # decoding 100+ frames at once would not fit
        pipe.set_progress_bar_config(disable=True)
        self.pipe, self.armed, self.derived, self.path = pipe, pipe, {}, path
        log(f"{type(pipe).__name__} ready: {_gib(torch.cuda.memory_allocated())} GiB allocated")

    @staticmethod
    def _load_wan(path: Path) -> Any:
        from diffusers import WanPipeline

        return WanPipeline.from_pretrained(str(path), dtype=torch.bfloat16)

    @staticmethod
    def _load_ltx2(path: Path, weights: str | None) -> Any:
        """LTX-2.5: the 22B transformer from a GGUF file (bf16 would need 44 GB) and the Gemma text encoder in 4-bit
        NF4 (24 GB in bf16), everything else from the diffusers folder."""
        import transformers
        from diffusers import GGUFQuantizationConfig, LTX2Pipeline, LTX2VideoTransformer3DModel
        from diffusers.models.model_loading_utils import load_gguf_checkpoint
        from diffusers.quantizers import PipelineQuantizationConfig

        dtype = torch.bfloat16
        kwargs: dict[str, Any] = {"dtype": dtype}
        if weights:
            log(f"Loading GGUF transformer {Path(weights).name}")
            # LTX-2.5 checkpoints name the prompt AdaLN layers `*prompt_adaln_single`; diffusers 0.40's converter
            # expects `*prompt_adaln` and would leave those 12 tensors empty
            state = {_ltx25_key(k): v for k, v in load_gguf_checkpoint(weights).items()}
            kwargs["transformer"] = LTX2VideoTransformer3DModel.from_single_file(
                state, config=str(path), subfolder="transformer", dtype=dtype,
                quantization_config=GGUFQuantizationConfig(compute_dtype=dtype))
        # The prompt enhancer (a 10 GB Gemma) loads on first use, not with every load
        kwargs["prompt_enhancer"] = None
        if not (path / "duration_head").is_dir():
            kwargs["duration_head"] = None
        # Quantizing the 24 GB text encoder takes minutes, so the 4-bit result is kept next to the model (~7 GB) and
        # read back directly on later loads
        cached = path / _NF4_TEXT_ENCODER
        if (cached / "config.json").is_file():
            cls_name = json.loads((path / "model_index.json").read_text(encoding="utf-8"))["text_encoder"][1]
            log(f"Loading the 4-bit text encoder from {cached.name}")
            kwargs["text_encoder"] = getattr(transformers, cls_name).from_pretrained(str(cached), dtype=dtype)
            return LTX2Pipeline.from_pretrained(str(path), **kwargs)
        kwargs["quantization_config"] = PipelineQuantizationConfig(
            quant_backend="bitsandbytes_4bit", components_to_quantize=["text_encoder"],
            quant_kwargs={"load_in_4bit": True, "bnb_4bit_quant_type": "nf4", "bnb_4bit_compute_dtype": dtype})
        pipe = LTX2Pipeline.from_pretrained(str(path), **kwargs)
        try:
            pipe.text_encoder.save_pretrained(str(cached))
            log(f"Saved the 4-bit text encoder to {cached.name} for faster loads")
        except Exception as exc:  # a missing cache only costs time
            log(f"Could not cache the 4-bit text encoder: {exc}")
        return pipe

    def _unload(self) -> None:
        self.pipe = self.armed = self.upsampler = self.decoder = self.enhancer = None
        self.derived = {}

    def _pipe_for(self, mode: str) -> Any:
        if mode == "t2v":
            pipe = self.pipe
        elif mode in self.derived:
            pipe = self.derived[mode]
        else:
            import diffusers

            cls = getattr(diffusers, "LTX2ImageToVideoPipeline" if self.family == "ltx2" else "WanImageToVideoPipeline")
            # Built from the loaded components as they are: `from_pipe` re-casts them, which quantized (GGUF / 4-bit)
            # weights don't allow
            accepted = inspect.signature(cls.__init__).parameters
            parts = {k: v for k, v in self.pipe.components.items() if k in accepted}
            # Plain settings too (Wan's expand_timesteps / boundary_ratio), not just the modules
            settings = {k: v for k, v in self.pipe.config.items() if k in accepted and k not in parts and
                        not isinstance(v, (list, tuple))}
            pipe = cls(**parts, **settings)
            pipe.set_progress_bar_config(disable=True)
            self.derived[mode] = pipe
        if self.armed is not pipe:
            pipe.enable_model_cpu_offload()  # offload hooks are per pipeline: re-arm them on the shared components
            self.armed = pipe
        return pipe

    # --------------------------- LTX extras (lazy) ---------------------------

    def _enhance(self, prompt: str, image: Any) -> str:
        """Rewrite the prompt with LTX-2.5's own enhancer (on the GPU only while it runs)."""
        from diffusers.pipelines.ltx2 import utils as ltx_utils
        from transformers import AutoModelForImageTextToText

        assert self.path is not None
        if self.enhancer is None:
            self.progress.message = "Loading the prompt enhancer"
            self.enhancer = AutoModelForImageTextToText.from_pretrained(str(self.path / "prompt_enhancer"),
                                                                        dtype=torch.bfloat16)
            self.pipe.register_modules(prompt_enhancer=self.enhancer)
        self.progress.message = "Enhancing the prompt"
        system = ltx_utils.LTX2_5_I2V_DEFAULT_SYSTEM_PROMPT if image is not None else \
            ltx_utils.LTX2_5_T2V_DEFAULT_SYSTEM_PROMPT
        self.enhancer.to("cuda")
        try:
            enhanced = self.pipe.enhance_prompt(prompt=prompt, system_prompt=system, device="cuda", image=image)
        finally:
            self.enhancer.to("cpu")
            free_cuda()
        text = enhanced[0] if isinstance(enhanced, list) else str(enhanced)
        log(f"Enhanced prompt: {text[:300]}")
        return text

    def _upsample(self, latents: Any) -> Any:
        from diffusers.pipelines.ltx2 import LTX2LatentUpsamplePipeline
        from diffusers.pipelines.ltx2.latent_upsampler import LTX2LatentUpsamplerModel

        assert self.path is not None
        if self.upsampler is None:
            self.progress.message = "Loading the latent upsampler"
            self.upsampler = LTX2LatentUpsamplerModel.from_pretrained(str(self.path / "latent_upsampler"),
                                                                       dtype=torch.bfloat16)
        self.progress.message = "Upscaling 2x"
        self.upsampler.to("cuda")
        try:
            up = LTX2LatentUpsamplePipeline(vae=self.pipe.vae, latent_upsampler=self.upsampler)
            up.set_progress_bar_config(disable=True)
            return up(latents=latents, output_type="latent", return_dict=False)[0]
        finally:
            self.upsampler.to("cpu")
            free_cuda()

    def _diffusion_decode(self, latents: Any, generator: Any) -> Any:
        from diffusers import LTX2VideoDiffusionDecodePipeline, LTX2VideoDiffusionDecoderModel

        assert self.path is not None
        if self.decoder is None:
            self.progress.message = "Loading the diffusion decoder"
            self.decoder = LTX2VideoDiffusionDecoderModel.from_pretrained(str(self.path / "diffusion_decoder"),
                                                                          dtype=torch.bfloat16)
            self.decoder.enable_tiling()  # peak memory follows the tile size, not the video size
            use_blocked_attention(self.decoder)  # FlexAttention without Triton would build the full score matrix
        self.progress.message = "Decoding (diffusion decoder)"
        self.decoder.to("cuda")
        try:
            decode = LTX2VideoDiffusionDecodePipeline(diffusion_decoder=self.decoder, scheduler=self.pipe.scheduler,
                                                      vae=self.pipe.vae)
            decode.set_progress_bar_config(disable=True)
            return decode(latents, generator=generator, output_type="np", denormalize=False, return_dict=False)[0]
        finally:
            self.decoder.to("cpu")
            free_cuda()

    # ------------------------------ generation ------------------------------

    def generate(self, req: dict[str, Any]) -> dict[str, Any]:
        with self.busy:
            self.require_loaded()
            mode = req.get("mode") or "t2v"
            if mode not in ("t2v", "i2v"):
                raise BadRequest(f"Unknown video mode {mode!r}")
            width, height, fps = int(req["width"]), int(req["height"]), float(req["fps"])
            frames = int(req["frames"]) if req.get("frames") else None
            image = None
            if mode == "i2v":
                from PIL import Image, ImageOps

                image = ImageOps.exif_transpose(Image.open(req["image"])).convert("RGB")
            generator = torch.Generator(device="cpu").manual_seed(int(req["seed"]))
            self.progress.reset(total=0, message="Encoding the prompt")
            torch.cuda.reset_peak_memory_stats()
            started = time.monotonic()
            prompt = req["prompt"]
            if self.family == "ltx2":
                if req.get("enhance_prompt"):
                    prompt = self._enhance(prompt, _cover(image, width, height) if image is not None else None)
                video, audio = self._run_ltx(mode, req, prompt, image, width, height, frames, fps, generator)
            else:
                video, audio = self._run_wan(mode, req, image, width, height, frames or 81, generator), None
            elapsed = time.monotonic() - started
            if req.get("skip_first_frame") and video.shape[0] > 1:
                video = video[1:]  # it repeats the previous segment's last frame
                if audio is not None:
                    rate = int(self.pipe.vocoder.config.output_sampling_rate)
                    audio = audio[..., round(rate / fps):]
            self.progress.message = "Encoding the video"
            out = Path(req["out_path"])
            out.parent.mkdir(parents=True, exist_ok=True)
            rate = int(self.pipe.vocoder.config.output_sampling_rate) if audio is not None else 0
            _encode(req["ffmpeg"], video, fps, out, audio, rate)
            if req.get("last_frame_path"):
                _save_frame(video[-1], Path(req["last_frame_path"]))
            log(f"{self.family} {mode}: {video.shape[0]} frames {width}x{height} in {elapsed:.0f}s; "
                f"peak VRAM {_gib(torch.cuda.max_memory_allocated())} GiB")
            return {"path": str(out), "width": width, "height": height, "frames": int(video.shape[0]),
                    "fps": fps, "duration_s": round(video.shape[0] / fps, 2), "audio": audio is not None,
                    "seconds": round(elapsed, 1), "prompt": prompt}

    def _run_wan(self, mode: str, req: dict[str, Any], image: Any, width: int, height: int, frames: int,
                 generator: Any) -> Any:
        pipe = self._pipe_for(mode)
        steps = int(req["steps"])
        self.progress.total = steps
        kwargs: dict[str, Any] = {
            "prompt": req["prompt"], "width": width, "height": height, "num_frames": frames,
            "num_inference_steps": steps, "guidance_scale": float(req["guidance"]), "generator": generator,
            "output_type": "np", "return_dict": False, "callback_on_step_end": self._on_step(steps, 0, steps),
        }
        if image is not None:
            kwargs["image"] = _cover(image, width, height)
        if req.get("negative_prompt"):
            kwargs["negative_prompt"] = req["negative_prompt"]
        return pipe(**kwargs)[0][0]

    @torch.no_grad()  # the diffusion-decoder path decodes the audio itself, outside the pipeline's no_grad
    def _run_ltx(self, mode: str, req: dict[str, Any], prompt: str, image: Any, width: int, height: int,
                 frames: int | None, fps: float, generator: Any) -> tuple[Any, Any]:
        from diffusers.pipelines.ltx2.utils import (DEFAULT_NEGATIVE_PROMPT, DISTILLED_SIGMA_VALUES,
                                                    STAGE_2_DISTILLED_SIGMA_VALUES)

        two_stage = bool(req.get("two_stage"))
        diffusion = req.get("decoder") == "diffusion"
        stage1 = len(DISTILLED_SIGMA_VALUES)
        stage2 = len(STAGE_2_DISTILLED_SIGMA_VALUES) if two_stage else 0
        self.progress.total = stage1 + stage2
        # The distilled transformer runs fixed sigma schedules without guidance (per the model card)
        common: dict[str, Any] = {
            "prompt": prompt, "negative_prompt": req.get("negative_prompt") or DEFAULT_NEGATIVE_PROMPT,
            "frame_rate": fps, "guidance_scale": 1.0, "audio_guidance_scale": 1.0, "stg_scale": 0.0,
            "audio_stg_scale": 0.0, "modality_scale": 1.0, "audio_modality_scale": 1.0, "generator": generator,
            "return_dict": False,
        }
        if frames is None:  # the duration head picks the length, up to max_seconds
            common.update(min_seconds=1.0, max_seconds=float(req.get("max_seconds") or 20))
        first = self._pipe_for(mode)
        w1, h1 = (width // 2, height // 2) if two_stage else (width, height)
        kw1: dict[str, Any] = {**common, "width": w1, "height": h1, "num_frames": frames,
                               "sigmas": DISTILLED_SIGMA_VALUES,
                               "callback_on_step_end": self._on_step(stage1, 0, stage1 + stage2)}
        if image is not None:
            kw1["image"] = _cover(image, w1, h1)
        final_latent = two_stage or diffusion
        latents, audio = first(**kw1, output_type="latent" if final_latent else "np")
        if two_stage:
            upscaled = self._upsample(latents)
            count = (upscaled.shape[2] - 1) * self.pipe.vae_temporal_compression_ratio + 1
            refine = self._pipe_for("t2v")
            kw2 = {**common, "width": width, "height": height, "num_frames": count, "latents": upscaled,
                   "audio_latents": audio, "sigmas": STAGE_2_DISTILLED_SIGMA_VALUES,
                   "noise_scale": STAGE_2_DISTILLED_SIGMA_VALUES[0],
                   "callback_on_step_end": self._on_step(stage2, stage1, stage1 + stage2)}
            kw2.pop("min_seconds", None)
            kw2.pop("max_seconds", None)
            latents, audio = refine(**kw2, output_type="latent" if diffusion else "np")
        if not final_latent or (two_stage and not diffusion):
            return latents[0], audio[0]
        # Latent output for the diffusion decoder: decode the video with it and the audio ourselves
        video = self._diffusion_decode(latents, generator)[0]
        wave_out = self.pipe.vocoder(self.pipe.audio_vae.decode(audio.to(self.pipe.audio_vae.dtype),
                                                                return_dict=False)[0])
        return video, wave_out[0]

    def _on_step(self, total: int, offset: int, overall: int) -> Any:
        def on_step(_pipe: Any, step: int, _timestep: Any, cb_kwargs: dict[str, Any]) -> dict[str, Any]:
            done = offset + step + 1
            self.progress.step = done
            self.progress.message = "Decoding the video" if done >= overall else "Denoising"
            self.progress.check()  # raising here aborts the denoising loop
            return cb_kwargs

        return on_step


def _ltx25_key(key: str) -> str:
    head, dot, rest = key.partition(".")
    return _LTX25_RENAMES.get(head, head) + dot + rest


def _cover(image: Any, width: int, height: int) -> Any:
    """Scale and centre-crop the start frame to the video's size (keeps its aspect ratio)."""
    from PIL import Image

    scale = max(width / image.width, height / image.height)
    resized = image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)
    left, top = (resized.width - width) // 2, (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def _to_uint8(frames: Any) -> Any:
    frames = np.asarray(frames)
    if frames.dtype != np.uint8:
        frames = (np.clip(frames, 0.0, 1.0) * 255).round().astype(np.uint8)
    return frames


def _save_frame(frame: Any, path: Path) -> None:
    """The last frame, as the start image of the next segment."""
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(_to_uint8(frame)).save(path)


def _encode(ffmpeg: str, video: Any, fps: float, out: Path, audio: Any, rate: int) -> None:
    """Pipe raw RGB frames into ffmpeg (H.264, yuv420p, web-playable); mux the audio track when there is one."""
    frames = _to_uint8(video)
    n, h, w = frames.shape[0], frames.shape[1], frames.shape[2]
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
           "-r", f"{fps:g}", "-i", "-"]
    wav = None
    if audio is not None:
        wav = out.with_suffix(".wav")
        _write_wav(wav, audio, rate)
        # The model's own levels, untouched (no normalization)
        cmd += ["-i", str(wav), "-c:a", "aac", "-b:a", "256k", "-shortest"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "17", "-preset", "medium", "-movflags", "+faststart",
            str(out)]
    try:
        proc = subprocess.run(cmd, input=frames.tobytes(), capture_output=True, creationflags=_NO_WINDOW)
    finally:
        if wav is not None:
            wav.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.decode(errors='replace')[-600:]}")
    log(f"Encoded {n} frames to {out.name}")


def _write_wav(path: Path, audio: Any, rate: int) -> None:
    data = audio.float().cpu().numpy() if hasattr(audio, "cpu") else np.asarray(audio, dtype=np.float32)
    if data.ndim == 1:
        data = data[None]
    if data.shape[0] > data.shape[-1]:  # (samples, channels) → (channels, samples)
        data = data.T
    peak, rms = float(np.abs(data).max(initial=0.0)), float(np.sqrt(np.mean(data**2))) if data.size else 0.0
    log(f"Audio: {data.shape[0]} ch at {rate} Hz, peak {_db(peak)} dBFS, RMS {_db(rms)} dBFS")
    pcm = (np.clip(data, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as f:
        f.setnchannels(pcm.shape[0])
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(pcm.T.tobytes())


def _db(x: float) -> str:
    return f"{20 * np.log10(x):.1f}" if x > 0 else "-inf"


def _factory(runtime: str) -> Worker:
    if runtime != "diffusers-video":
        raise SystemExit(f"video_worker: unknown runtime {runtime!r}")
    log(f"torch {torch.__version__}, CUDA available: {torch.cuda.is_available()}")
    return VideoWorker(runtime)


if __name__ == "__main__":
    serve(_factory)
