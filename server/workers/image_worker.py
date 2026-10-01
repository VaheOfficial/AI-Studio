"""Image runtimes: any diffusers pipeline (incl. GGUF / fp8 / NF4 variants) and HunyuanImage 3 (transformers,
trust_remote_code)."""

from __future__ import annotations

import inspect
import json
import struct
import time
from pathlib import Path
from typing import Any

from latent_preview import LatentPreviewer
from worker_base import BadRequest, Worker, log, serve

import torch

# Sampler choices for UNet (SD 1.x / SDXL) pipelines; flow-matching DiTs keep their own scheduler.
SCHEDULERS: dict[str, tuple[str, dict[str, Any]]] = {
    "euler": ("EulerDiscreteScheduler", {}),
    "euler_a": ("EulerAncestralDiscreteScheduler", {}),
    "dpmpp_2m": ("DPMSolverMultistepScheduler", {}),
    "dpmpp_2m_karras": ("DPMSolverMultistepScheduler", {"use_karras_sigmas": True}),
    "dpmpp_sde_karras": ("DPMSolverMultistepScheduler", {"algorithm_type": "sde-dpmsolver++",
                                                         "use_karras_sigmas": True}),
    "unipc": ("UniPCMultistepScheduler", {}),
    "ddim": ("DDIMScheduler", {}),
}
# Edit pipelines diffusers' AutoPipeline mappings don't cover: (text-to-image class, mode) → class
EXTRA_PIPELINES = {
    ("Flux2KleinPipeline", "inpaint"): "Flux2KleinInpaintPipeline",
    ("ChromaPipeline", "img2img"): "ChromaImg2ImgPipeline",
    ("ChromaPipeline", "inpaint"): "ChromaInpaintPipeline",
}
_PREVIEW_INTERVAL_S = 0.35


def _gib(n: float) -> float:
    return round(n / 2**30, 2)


def _is_fp8(path: Path) -> bool:
    with path.open("rb") as f:
        (length,) = struct.unpack("<Q", f.read(8))
        header = json.loads(f.read(length))
    return any(isinstance(t, dict) and str(t.get("dtype", "")).startswith("F8") for t in header.values())


class DiffusersWorker(Worker):
    """Any diffusers image pipeline: a pipeline folder, a GGUF / safetensors denoiser on base components, or a
    full single-file checkpoint. Text-to-image, img2img, inpainting and reference edits share one set of weights."""

    def __init__(self, runtime: str) -> None:
        super().__init__(runtime)
        self.pipe: Any = None
        self.offload = "none"
        self.derived: dict[str, Any] = {}  # mode → pipeline sharing self.pipe's components
        self.armed: Any = None  # the pipeline whose CPU-offload hooks are installed
        self.base_scheduler: Any = None
        self.previewer: LatentPreviewer | None = None
        self.routes["/generate"] = self.generate

    # ------------------------------- loading -------------------------------

    def _load(self, req: dict[str, Any]) -> None:
        import diffusers
        from diffusers import DiffusionPipeline

        dtype = torch.bfloat16
        weights = Path(req["weights"]) if req.get("weights") else None
        pipeline_dir = Path(req.get("pipeline_dir") or req["path"])
        torch.cuda.reset_peak_memory_stats()
        if weights is not None and req.get("full_checkpoint"):
            cls = getattr(diffusers, req.get("pipeline_class") or "", None)
            if cls is None:
                raise BadRequest(f"Unrecognized single-file checkpoint {weights.name}")
            log(f"Loading full checkpoint {weights.name} as {cls.__name__}")
            pipe = cls.from_single_file(str(weights), dtype=dtype)
        elif weights is not None:
            pipe = self._pipeline_with_denoiser(pipeline_dir, weights, req.get("weights_format") or "", dtype)
        else:
            kwargs: dict[str, Any] = {"dtype": dtype}
            if any(pipeline_dir.glob("*/*.fp16.safetensors")):
                kwargs["variant"] = "fp16"  # repos where we only downloaded the fp16 files (SDXL)
            pipe = DiffusionPipeline.from_pretrained(str(pipeline_dir), **kwargs)
        self.offload = req.get("offload", "none")
        self._place(pipe)
        # Decode the latent in tiles: a 1024² decode otherwise needs ~10 GB at once, which spills into
        # Windows shared memory (very slow) whenever other models are resident on the GPU.
        vae = getattr(pipe, "vae", None)
        if vae is not None and hasattr(vae, "enable_tiling"):
            vae.enable_tiling()
        pipe.set_progress_bar_config(disable=True)
        self.pipe, self.armed, self.derived = pipe, pipe, {}
        self.base_scheduler = getattr(pipe, "scheduler", None)
        self.previewer = LatentPreviewer(pipe)
        log(f"{type(pipe).__name__} ready (offload={self.offload}): {_gib(torch.cuda.memory_allocated())} GiB "
            f"allocated, peak {_gib(torch.cuda.max_memory_allocated())} GiB")

    def _pipeline_with_denoiser(self, pipeline_dir: Path, weights: Path, fmt: str, dtype: Any) -> Any:
        """Load a single-file transformer/unet (GGUF or safetensors, e.g. fp8) and build the pipeline around it
        from the base components in ``pipeline_dir``."""
        import diffusers
        from diffusers import DiffusionPipeline, GGUFQuantizationConfig

        index = json.loads((pipeline_dir / "model_index.json").read_text(encoding="utf-8"))
        slot = "transformer" if "transformer" in index else "unet"
        model_cls = getattr(diffusers, index[slot][1])
        kwargs: dict[str, Any] = {"config": str(pipeline_dir), "subfolder": slot, "dtype": dtype}
        if fmt == "gguf":
            kwargs["quantization_config"] = GGUFQuantizationConfig(compute_dtype=dtype)
        log(f"Loading {fmt} {slot} {weights.name} into {model_cls.__name__} (base: {pipeline_dir})")
        denoiser = model_cls.from_single_file(str(weights), **kwargs)
        if fmt == "safetensors" and _is_fp8(weights):
            # Keep fp8 weights in fp8 and upcast per layer: half the VRAM of bf16
            denoiser.enable_layerwise_casting(storage_dtype=torch.float8_e4m3fn, compute_dtype=dtype)
        return DiffusionPipeline.from_pretrained(str(pipeline_dir), **{slot: denoiser}, dtype=dtype)

    def _place(self, pipe: Any) -> None:
        if self.offload == "sequential":
            pipe.enable_sequential_cpu_offload()
        elif self.offload == "model":
            pipe.enable_model_cpu_offload()
        else:
            pipe.to("cuda")

    def _unload(self) -> None:
        self.pipe = self.armed = self.base_scheduler = self.previewer = None
        self.derived = {}

    def _pipe_for(self, mode: str) -> Any:
        """The pipeline for a mode, built from the loaded one without copying weights."""
        if mode in ("txt2img", "edit"):
            pipe = self.pipe
        elif mode in self.derived:
            pipe = self.derived[mode]
        else:
            import diffusers
            from diffusers import AutoPipelineForImage2Image, AutoPipelineForInpainting

            extra = EXTRA_PIPELINES.get((type(self.pipe).__name__, mode))
            auto = AutoPipelineForImage2Image if mode == "img2img" else AutoPipelineForInpainting
            try:
                pipe = getattr(diffusers, extra).from_pipe(self.pipe) if extra else auto.from_pipe(self.pipe)
            except ValueError as exc:
                raise BadRequest(f"{type(self.pipe).__name__} has no {mode} pipeline: {exc}") from exc
            pipe.set_progress_bar_config(disable=True)
            self.derived[mode] = pipe
        if self.offload != "none" and self.armed is not pipe:
            self._place(pipe)  # offload hooks are per pipeline: re-arm them on the shared components
            self.armed = pipe
        return pipe

    def _set_scheduler(self, pipe: Any, scheduler: str | None) -> None:
        if self.base_scheduler is None:
            return
        if not scheduler:
            pipe.scheduler = self.base_scheduler
            return
        if scheduler not in SCHEDULERS:
            raise BadRequest(f"Unknown scheduler {scheduler!r}")
        import diffusers

        cls_name, opts = SCHEDULERS[scheduler]
        pipe.scheduler = getattr(diffusers, cls_name).from_config(self.base_scheduler.config, **opts)

    # ------------------------------ generation ------------------------------

    def generate(self, req: dict[str, Any]) -> dict[str, Any]:
        with self.busy:
            self.require_loaded()
            mode = req.get("mode") or "txt2img"
            pipe = self._pipe_for(mode)
            self._set_scheduler(pipe, req.get("scheduler"))
            seeds: list[int] = req["seeds"]
            paths: list[str] = req["out_paths"]
            steps = int(req["steps"])
            # img2img / inpaint only run the last `strength` fraction of the schedule
            partial = mode in ("img2img", "inpaint")
            run_steps = max(1, int(steps * float(req.get("strength") or 1))) if partial else steps
            self.progress.reset(total=run_steps * len(seeds), message="Denoising")
            images_in = self._inputs(req, mode)
            params = inspect.signature(pipe.__call__).parameters
            torch.cuda.reset_peak_memory_stats()
            started = time.monotonic()
            images = []
            for i, (seed, out_path) in enumerate(zip(seeds, paths, strict=True)):
                kwargs = self._call_kwargs(pipe, req, params, seed, mode, images_in, offset=i * run_steps,
                                           run_steps=run_steps)
                image = pipe(**kwargs).images[0]
                Path(out_path).parent.mkdir(parents=True, exist_ok=True)
                image.save(out_path)
                images.append({"path": out_path, "width": image.width, "height": image.height, "seed": seed})
                self.progress.step = (i + 1) * run_steps
            log(f"{type(pipe).__name__} {mode}: {len(seeds)} image(s) {req['width']}x{req['height']}, {steps} steps "
                f"in {time.monotonic() - started:.1f}s; peak VRAM {_gib(torch.cuda.max_memory_allocated())} GiB")
            return {"images": images}

    def _inputs(self, req: dict[str, Any], mode: str) -> dict[str, Any]:
        from PIL import Image, ImageOps

        if mode == "txt2img":
            return {}
        paths = req.get("images") or []
        if not paths:
            raise BadRequest(f"{mode} needs an input image")
        opened = [ImageOps.exif_transpose(Image.open(p)).convert("RGB") for p in paths]
        if mode == "edit":
            return {"image": opened if len(opened) > 1 else opened[0]}
        size = (int(req["width"]), int(req["height"]))
        out: dict[str, Any] = {"image": opened[0].resize(size, Image.LANCZOS)}
        if mode == "inpaint":
            if not req.get("mask"):
                raise BadRequest("inpaint needs a mask")
            out["mask_image"] = Image.open(req["mask"]).convert("L").resize(size, Image.LANCZOS)
        return out

    def _call_kwargs(self, pipe: Any, req: dict[str, Any], params: Any, seed: int, mode: str,
                     images_in: dict[str, Any], offset: int, run_steps: int) -> dict[str, Any]:
        width, height = int(req["width"]), int(req["height"])
        kwargs: dict[str, Any] = {
            "prompt": req["prompt"], "width": width, "height": height,
            "num_inference_steps": int(req["steps"]),
            "generator": torch.Generator(device="cpu").manual_seed(int(seed)),
            **images_in,
        }
        if mode in ("img2img", "inpaint"):
            kwargs["strength"] = float(req.get("strength") or 0.7)
        guidance = float(req["guidance"])
        negative = req.get("negative_prompt")
        if type(pipe).__name__.startswith("QwenImage"):
            # Qwen-Image: real CFG is enabled by true_cfg_scale plus a negative prompt
            kwargs["true_cfg_scale"] = guidance
            kwargs["negative_prompt"] = negative or " "
        elif "guidance_scale" in params:
            kwargs["guidance_scale"] = guidance  # CFG, or the embedded guidance of distilled FLUX models
        elif "distilled_guidance_scale" in params:
            kwargs["distilled_guidance_scale"] = guidance
        if negative and "negative_prompt" in params:
            kwargs["negative_prompt"] = negative
        if "callback_on_step_end" in params:
            kwargs["callback_on_step_end"] = self._on_step(width, height, offset, run_steps)
            if "callback_on_step_end_tensor_inputs" in params and self.previewer and self.previewer.available:
                kwargs["callback_on_step_end_tensor_inputs"] = ["latents"]
        return {k: v for k, v in kwargs.items() if k in params or k == "prompt"}

    def _on_step(self, width: int, height: int, offset: int, run_steps: int) -> Any:
        last = [0.0]
        prev: list[Any] = [None]  # latents after the previous step

        def on_step(pipe: Any, step: int, _timestep: Any, cb_kwargs: dict[str, Any]) -> dict[str, Any]:
            done = step + 1
            self.progress.step = offset + done
            # The VAE decode after the last step can take a while — say so instead of sitting at 100%
            self.progress.message = "Decoding image" if done >= run_steps else "Denoising"
            self.progress.check()  # raising here aborts the denoising loop
            latents = cb_kwargs.get("latents")
            if latents is None or not self.previewer:
                return cb_kwargs
            now = time.monotonic()
            if prev[0] is not None and (now - last[0] >= _PREVIEW_INTERVAL_S or done >= run_steps):
                last[0] = now
                try:
                    image = self.previewer.jpeg_data_url(_denoised(pipe.scheduler, prev[0], latents), height, width)
                except (RuntimeError, ValueError) as exc:  # a preview must never break generation
                    log(f"Preview skipped: {exc}")
                    image = None
                if image:
                    self.progress.preview = {"step": self.progress.step, "image": image}
            prev[0] = latents.detach().clone()
            return cb_kwargs

        return on_step


def _denoised(scheduler: Any, before: Any, after: Any) -> Any:
    """Estimate the clean latent from two consecutive steps, so previews show the image instead of noise.

    Euler-style samplers (flow matching and k-diffusion sigmas alike) move ``x`` along
    ``d = (x_next - x) / (σ_next - σ)``, and the clean sample is ``x_next - σ_next · d``. Exact for Euler, close
    enough for multistep samplers; falls back to the raw latent when the scheduler has no sigma schedule.
    Data-prediction multistep samplers (DPM++, UniPC) keep their last clean-sample estimate: use that."""
    outputs = getattr(scheduler, "model_outputs", None)
    config = getattr(scheduler, "config", {})
    x0_mode = config.get("algorithm_type", "") in ("dpmsolver++", "sde-dpmsolver++") or config.get("predict_x0", False)
    if outputs and x0_mode and outputs[-1] is not None and outputs[-1].shape == after.shape:
        return outputs[-1]
    sigmas = getattr(scheduler, "sigmas", None)
    index = getattr(scheduler, "step_index", None)
    if sigmas is None or not index or index >= len(sigmas) or before.shape != after.shape:
        return after
    s_prev, s_next = float(sigmas[index - 1]), float(sigmas[index])
    if s_prev == s_next:
        return after
    return after - s_next * (after - before) / (s_next - s_prev)


class HunyuanImage3Worker(Worker):
    def __init__(self, runtime: str) -> None:
        super().__init__(runtime)
        self.model: Any = None
        self.routes["/generate"] = self.generate

    def _load(self, req: dict[str, Any]) -> None:
        from transformers import AutoModelForCausalLM

        kwargs: dict[str, Any] = {"attn_implementation": "sdpa", "trust_remote_code": True, "torch_dtype": "auto",
                                  "device_map": "auto", "moe_impl": "eager"}
        if req.get("offload", "none") != "none":
            import psutil

            vram = torch.cuda.get_device_properties(0).total_memory / 2**30
            ram = psutil.virtual_memory().total / 2**30
            kwargs["max_memory"] = {0: f"{int(vram * 0.9)}GiB", "cpu": f"{int(ram * 0.75)}GiB"}
            kwargs["offload_folder"] = str(Path(req["path"]) / ".offload")
        self.model = AutoModelForCausalLM.from_pretrained(req["path"], **kwargs)
        self.model.load_tokenizer(req["path"])

    def _unload(self) -> None:
        self.model = None

    def generate(self, req: dict[str, Any]) -> dict[str, Any]:
        with self.busy:
            self.require_loaded()
            if (req.get("mode") or "txt2img") != "txt2img":
                raise BadRequest("HunyuanImage 3 supports text-to-image only")
            params = inspect.signature(self.model.generate_image).parameters
            self.progress.reset(total=0, message="Generating (autoregressive; no step progress)")
            images = []
            for seed, out_path in zip(req["seeds"], req["out_paths"], strict=True):
                self.progress.check()
                kwargs: dict[str, Any] = {"prompt": req["prompt"], "seed": int(seed),
                                          "image_size": f"{int(req['height'])}x{int(req['width'])}",
                                          "diff_infer_steps": int(req["steps"]), "stream": True}
                image = self.model.generate_image(**{k: v for k, v in kwargs.items() if k in params or k == "prompt"})
                if isinstance(image, (list, tuple)):
                    image = image[0]
                if not hasattr(image, "save"):
                    raise BadRequest(f"Unexpected generate_image result type {type(image).__name__}")
                Path(out_path).parent.mkdir(parents=True, exist_ok=True)
                image.save(out_path)
                images.append({"path": out_path, "width": image.width, "height": image.height, "seed": seed})
            return {"images": images}


def _factory(runtime: str) -> Worker:
    workers = {"diffusers": DiffusersWorker, "hunyuan-image3": HunyuanImage3Worker}
    if runtime not in workers:
        raise SystemExit(f"image_worker: unknown runtime {runtime!r}")
    log(f"torch {torch.__version__}, CUDA available: {torch.cuda.is_available()}")
    return workers[runtime](runtime)


if __name__ == "__main__":
    serve(_factory)
