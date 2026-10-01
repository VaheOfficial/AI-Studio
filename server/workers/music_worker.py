"""Music runtime: ACE-Step text-to-music."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from worker_base import Worker, log, serve

import soundfile as sf
import torch


class AceStepWorker(Worker):
    def __init__(self, runtime: str) -> None:
        super().__init__(runtime)
        self.pipe: Any = None
        self.routes["/generate"] = self.generate
        self._patch_tqdm()

    def _patch_tqdm(self) -> None:
        """ACE-Step reports diffusion steps only through tqdm; route them into our progress."""
        import acestep.pipeline_ace_step as ace

        progress = self.progress

        def tracked(iterable: Iterable[Any], total: int | None = None, **_kw: Any) -> Iterator[Any]:
            if total and total > 1:
                progress.total, progress.step = total, 0
            for item in iterable:
                progress.check()
                yield item
                if total and total > 1:
                    progress.step += 1

        ace.tqdm = tracked

    def _load(self, req: dict[str, Any]) -> None:
        from acestep.pipeline_ace_step import ACEStepPipeline

        pipe = ACEStepPipeline(checkpoint_dir=req["path"], dtype="bfloat16", torch_compile=False,
                               cpu_offload=req.get("offload", "none") != "none")
        pipe.load_checkpoint(pipe.checkpoint_dir)
        self.pipe = pipe

    def _unload(self) -> None:
        self.pipe = None

    def generate(self, req: dict[str, Any]) -> dict[str, Any]:
        with self.busy:
            self.require_loaded()
            self.progress.reset(message="Composing")
            out_path = req["out_path"]
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            self.pipe(
                format="wav", audio_duration=float(req["duration_s"]), prompt=req["tags"],
                lyrics=req.get("lyrics") or "[instrumental]", infer_step=int(req["steps"]),
                guidance_scale=float(req["guidance"]), manual_seeds=[int(req["seed"])], save_path=out_path,
            )
            info = sf.info(out_path)
            return {"duration_s": info.frames / info.samplerate}


def _factory(runtime: str) -> Worker:
    if runtime != "ace-step":
        raise SystemExit(f"music_worker: unknown runtime {runtime!r}")
    log(f"torch {torch.__version__}, CUDA available: {torch.cuda.is_available()}")
    return AceStepWorker(runtime)


if __name__ == "__main__":
    serve(_factory)
