"""OmniVoice runtime (k2-fsa/OmniVoice): zero-shot TTS in 646 languages with voice cloning and
tag-based voice design, 24 kHz output. Runs in the ``omnivoice`` env (transformers >= 5.10).

Routes (stable contract, also used by the dubbing pipeline — see docs/api/voice.md):
  POST /tts        {text, language?, ref_audio?, ref_text?, instruct?, duration?, speed=1.0, num_step=16,
                    guidance_scale=2.0, t_shift?, position_temperature?, class_temperature?, seed?,
                    denoise=true, postprocess_output=true, out_path} -> {path, duration_s, sample_rate, seed}
  POST /tts_batch  {items: [<same fields as /tts>]} -> {items: [{path, duration_s, seed}]}

Text may carry ``[pause]`` / ``[pause 500ms]`` / ``[pause 1.5s]`` markers (silence) and non-verbal tags
(``[laughter]``, ``[sigh]``…, passed to the model). Long text is split at sentence boundaries into
~800-character chunks that are joined with a 50 ms crossfade. ``duration`` (seconds) fixes the length
of the whole utterance and overrides ``speed``.
"""

from __future__ import annotations

import os

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")

import random
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from worker_base import BadRequest, Worker, log, serve

import numpy as np
import soundfile as sf
import torch
from speech_chunks import concatenate, split_text_into_chunks

from omnivoice.models.omnivoice import OmniVoice, OmniVoiceGenerationConfig, VoiceClonePrompt
from omnivoice.utils.text import parse_pause_markers

_PROMPT_CACHE_MAX = 16
_BATCH_MAX = 8
_GEN_DEFAULTS: dict[str, Any] = {
    "num_step": 16, "guidance_scale": 2.0, "t_shift": 0.1, "position_temperature": 5.0,
    "class_temperature": 0.0, "denoise": True, "postprocess_output": True,
}


@dataclass
class _Item:
    """One validated /tts request, split into pause-separated spans of text chunks."""

    out_path: str
    seed: int
    language: str | None
    instruct: str | None
    speed: float
    prompt: VoiceClonePrompt | None
    config: OmniVoiceGenerationConfig
    config_key: tuple[Any, ...]
    # [(chunks as [(text, duration_s | None)], pause_ms_after)]
    spans: list[tuple[list[tuple[str, float | None]], int]]

    @property
    def chunk_count(self) -> int:
        return sum(len(chunks) for chunks, _ in self.spans)

    @property
    def single_chunk(self) -> bool:
        return len(self.spans) == 1 and len(self.spans[0][0]) == 1 and self.spans[0][1] == 0


class OmniVoiceWorker(Worker):
    def __init__(self, runtime: str) -> None:
        super().__init__(runtime)
        self.model: Any = None
        self.prompts: OrderedDict[tuple[Any, ...], VoiceClonePrompt] = OrderedDict()
        self.routes["/tts"] = self.tts
        self.routes["/tts_batch"] = self.tts_batch

    # -- lifecycle -------------------------------------------------------

    def _load(self, req: dict[str, Any]) -> None:
        # Eager attention (no torch.compile / triton on Windows); fp16 like VoiceStudio.
        self.model = OmniVoice.from_pretrained(req["path"], device_map="cuda", dtype=torch.float16)

    def _unload(self) -> None:
        self.model = None
        self.prompts.clear()

    @property
    def sample_rate(self) -> int:
        return int(self.model.sampling_rate)

    # -- request preparation ---------------------------------------------

    def _prompt(self, ref_audio: str, ref_text: str) -> VoiceClonePrompt:
        """Encode a reference clip once per (path, mtime, transcript); LRU-cached in memory."""
        path = Path(ref_audio)
        try:
            mtime = path.stat().st_mtime_ns
        except OSError as exc:
            raise BadRequest(f"Reference audio not found: {ref_audio}") from exc
        key = (str(path.resolve()), mtime, ref_text)
        hit = self.prompts.get(key)
        if hit is not None:
            self.prompts.move_to_end(key)
            return hit
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        wav = torch.from_numpy(data.mean(axis=1)).unsqueeze(0)
        try:
            prompt = self.model.create_voice_clone_prompt((wav, sr), ref_text=ref_text)
        except ValueError as exc:
            raise BadRequest(str(exc)) from exc
        self.prompts[key] = prompt
        while len(self.prompts) > _PROMPT_CACHE_MAX:
            self.prompts.popitem(last=False)
        return prompt

    def _prepare(self, req: dict[str, Any]) -> _Item:
        text = str(req.get("text") or "").strip()
        if not text:
            raise BadRequest("text is empty")
        if not req.get("out_path"):
            raise BadRequest("out_path is required")
        prompt = None
        if req.get("ref_audio"):
            ref_text = str(req.get("ref_text") or "").strip()
            if not ref_text:
                raise BadRequest("ref_text (the transcript of ref_audio) is required for voice cloning")
            prompt = self._prompt(req["ref_audio"], ref_text)
        gen = {k: (req[k] if req.get(k) is not None else v) for k, v in _GEN_DEFAULTS.items()}
        gen["num_step"] = int(gen["num_step"])
        config = OmniVoiceGenerationConfig.from_dict(gen)

        spans: list[tuple[list[str], int]] = []
        for span_text, pause_ms in parse_pause_markers(text):
            spans.append((split_text_into_chunks(span_text), pause_ms))
        if not any(chunks for chunks, _ in spans):
            raise BadRequest("text has nothing to speak besides pause markers")

        duration = req.get("duration")
        per_char: float | None = None
        if duration is not None:
            speech_s = float(duration) - sum(p for _, p in spans) / 1000.0
            chars = sum(len(c) for chunks, _ in spans for c in chunks)
            if speech_s <= 0.2:
                raise BadRequest(f"duration {duration}s leaves no time for speech after the pauses")
            per_char = speech_s / chars

        seed = int(req["seed"]) if req.get("seed") is not None else random.randint(0, 2**31 - 1)
        return _Item(
            out_path=str(req["out_path"]), seed=seed, language=req.get("language") or None,
            instruct=req.get("instruct") or None, speed=float(req.get("speed") or 1.0), prompt=prompt,
            config=config, config_key=(prompt is not None, *sorted(gen.items())),
            spans=[([(c, len(c) * per_char if per_char else None) for c in chunks], pause) for chunks, pause in spans],
        )

    # -- synthesis --------------------------------------------------------

    def _generate(self, items: list[_Item], texts: list[str], durations: list[float | None]) -> list[np.ndarray]:
        """One (possibly batched) model call; every item in ``items`` shares one generation config."""
        prompts = [it.prompt for it in items]
        audios = self.model.generate(
            text=texts, language=[it.language for it in items], instruct=[it.instruct for it in items],
            voice_clone_prompt=prompts if prompts[0] is not None else None,
            duration=durations if any(d is not None for d in durations) else None,
            speed=[it.speed for it in items], generation_config=items[0].config,
        )
        return [np.nan_to_num(a.squeeze(0).float().cpu().numpy()) for a in audios]

    def _render(self, item: _Item) -> np.ndarray:
        torch.manual_seed(item.seed)
        parts: list[np.ndarray] = []
        for chunks, pause_ms in item.spans:
            rendered = []
            for text, dur in chunks:
                self.progress.check()
                rendered.append(self._generate([item], [text], [dur])[0])
                self.progress.step += 1
            if rendered:
                parts.append(concatenate(rendered, self.sample_rate))
            if pause_ms:
                parts.append(np.zeros(int(self.sample_rate * pause_ms / 1000), dtype=np.float32))
        return np.concatenate(parts)

    def _write(self, item: _Item, audio: np.ndarray) -> dict[str, Any]:
        Path(item.out_path).parent.mkdir(parents=True, exist_ok=True)
        sf.write(item.out_path, audio, self.sample_rate, subtype="PCM_16")
        return {"path": item.out_path, "duration_s": round(audio.size / self.sample_rate, 3), "seed": item.seed}

    # -- routes -------------------------------------------------------------

    def tts(self, req: dict[str, Any]) -> dict[str, Any]:
        with self.busy:
            self.require_loaded()
            item = self._prepare(req)
            self.progress.reset(total=item.chunk_count, message="Synthesizing speech")
            result = self._write(item, self._render(item))
            return {**result, "sample_rate": self.sample_rate}

    def tts_batch(self, req: dict[str, Any]) -> dict[str, Any]:
        """Single-chunk items with the same generation settings run as native batches of up to 8
        (they share the RNG seed of the batch's first item); the rest render one by one."""
        with self.busy:
            self.require_loaded()
            raw = req.get("items") or []
            if not raw:
                raise BadRequest("items is empty")
            items = [self._prepare(r) for r in raw]
            self.progress.reset(total=sum(it.chunk_count for it in items), message="Synthesizing speech")
            results: list[dict[str, Any] | None] = [None] * len(items)
            groups: dict[tuple[Any, ...], list[int]] = {}
            for i, it in enumerate(items):
                if it.single_chunk:
                    groups.setdefault(it.config_key, []).append(i)
            for indices in groups.values():
                for start in range(0, len(indices), _BATCH_MAX):
                    batch = indices[start:start + _BATCH_MAX]
                    self.progress.check()
                    leader = items[batch[0]]
                    torch.manual_seed(leader.seed)
                    members = [items[i] for i in batch]
                    audios = self._generate(members, [m.spans[0][0][0][0] for m in members],
                                            [m.spans[0][0][0][1] for m in members])
                    for i, audio in zip(batch, audios, strict=True):
                        items[i].seed = leader.seed
                        results[i] = self._write(items[i], audio)
                        self.progress.step += 1
            for i, it in enumerate(items):
                if results[i] is None:
                    results[i] = self._write(it, self._render(it))
            return {"items": results}


def _factory(runtime: str) -> Worker:
    if runtime != "omnivoice":
        raise SystemExit(f"omnivoice_worker: unknown runtime {runtime!r}")
    log(f"torch {torch.__version__}, CUDA available: {torch.cuda.is_available()}")
    return OmniVoiceWorker(runtime)


if __name__ == "__main__":
    serve(_factory)
