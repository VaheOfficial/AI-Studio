"""Voice runtimes: Kokoro (preset TTS), Chatterbox (zero-shot cloning TTS), faster-whisper (STT)."""

from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any

from worker_base import BadRequest, Worker, log, serve

import numpy as np
import soundfile as sf
import torch

KOKORO_REPO = "hexgrad/Kokoro-82M"
KOKORO_SR = 24000


def _chunks(text: str, limit: int = 280) -> list[str]:
    """Split long text on sentence boundaries into pieces the TTS models handle well."""
    sentences = re.split(r"(?<=[.!?…])\s+", text.strip())
    out: list[str] = []
    cur = ""
    for s in sentences:
        if cur and len(cur) + len(s) + 1 > limit:
            out.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        out.append(cur)
    return out


def _write(path: str, audio: np.ndarray, sr: int) -> float:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, audio, sr, subtype="PCM_16")
    return len(audio) / sr


class KokoroWorker(Worker):
    def __init__(self, runtime: str) -> None:
        super().__init__(runtime)
        self.model: Any = None
        self.pipelines: dict[str, Any] = {}
        self.routes["/tts"] = self.tts

    def _load(self, req: dict[str, Any]) -> None:
        from kokoro import KModel

        root = Path(req["path"])
        self.model = KModel(repo_id=KOKORO_REPO, config=str(root / "config.json"),
                            model=str(root / "kokoro-v1_0.pth")).to("cuda").eval()

    def _unload(self) -> None:
        self.model = None
        self.pipelines.clear()

    def _pipeline(self, lang_code: str) -> Any:
        from kokoro import KPipeline

        if lang_code not in self.pipelines:
            self.pipelines[lang_code] = KPipeline(lang_code=lang_code, repo_id=KOKORO_REPO, model=self.model)
        return self.pipelines[lang_code]

    def tts(self, req: dict[str, Any]) -> dict[str, Any]:
        with self.busy:
            self.require_loaded()
            if not req.get("voice_path"):
                raise BadRequest("Kokoro needs a preset voice")
            self.progress.reset(message="Synthesizing speech")
            pipeline = self._pipeline(req.get("lang_code") or "a")
            parts: list[np.ndarray] = []
            for result in pipeline(req["text"], voice=req["voice_path"], speed=float(req.get("speed") or 1.0)):
                self.progress.check()
                if result.audio is not None:
                    parts.append(result.audio.detach().cpu().numpy())
                    self.progress.message = f"Synthesized {len(parts)} segment(s)"
            if not parts:
                raise BadRequest("Kokoro produced no audio (empty or unpronounceable text?)")
            return {"duration_s": _write(req["out_path"], np.concatenate(parts), KOKORO_SR)}


class ChatterboxWorker(Worker):
    def __init__(self, runtime: str) -> None:
        super().__init__(runtime)
        self.model: Any = None
        self.routes["/tts"] = self.tts

    def _load(self, req: dict[str, Any]) -> None:
        from chatterbox.tts import ChatterboxTTS

        self.model = ChatterboxTTS.from_local(req["path"], "cuda")

    def _unload(self) -> None:
        self.model = None

    def tts(self, req: dict[str, Any]) -> dict[str, Any]:
        with self.busy:
            self.require_loaded()
            pieces = _chunks(req["text"])
            self.progress.reset(total=len(pieces), message="Synthesizing speech")
            kwargs: dict[str, Any] = {}
            if req.get("exaggeration") is not None:
                kwargs["exaggeration"] = float(req["exaggeration"])
            if req.get("cfg_weight") is not None:
                kwargs["cfg_weight"] = float(req["cfg_weight"])
            if req.get("reference_wav"):
                # Conditioning is computed once; later chunks reuse model.conds.
                self.model.prepare_conditionals(req["reference_wav"], exaggeration=kwargs.get("exaggeration", 0.5))
            parts: list[np.ndarray] = []
            for i, piece in enumerate(pieces):
                self.progress.check()
                wav = self.model.generate(piece, **kwargs)
                parts.append(wav.squeeze(0).detach().cpu().numpy())
                self.progress.step = i + 1
            audio = np.concatenate(parts)
            speed = float(req.get("speed") or 1.0)
            if abs(speed - 1.0) > 1e-3:
                import librosa

                audio = librosa.effects.time_stretch(audio, rate=speed)
            return {"duration_s": _write(req["out_path"], audio, self.model.sr)}


class WhisperWorker(Worker):
    def __init__(self, runtime: str) -> None:
        super().__init__(runtime)
        self.model: Any = None
        self.routes["/transcribe"] = self.transcribe

    def _load(self, req: dict[str, Any]) -> None:
        from faster_whisper import WhisperModel

        self.model = WhisperModel(req["path"], device="cuda", compute_type="float16")

    def _unload(self) -> None:
        self.model = None

    def transcribe(self, req: dict[str, Any]) -> dict[str, Any]:
        """``path`` (any file ffmpeg reads) or ``pcm16`` (base64 16 kHz mono int16, used by live
        dictation: greedy decoding, no VAD, no cross-window conditioning)."""
        with self.busy:
            self.require_loaded()
            self.progress.reset(message="Transcribing")
            language = req.get("language") or None
            if req.get("pcm16"):
                pcm = np.frombuffer(base64.b64decode(req["pcm16"]), dtype=np.int16).astype(np.float32) / 32768.0
                segments, info = self.model.transcribe(pcm, language=language, beam_size=1,
                                                       condition_on_previous_text=False, vad_filter=False)
            else:
                segments, info = self.model.transcribe(req["path"], language=language, vad_filter=True)
            out = []
            for seg in segments:  # lazy generator: decoding happens here
                self.progress.check()
                out.append({"start": round(seg.start, 3), "end": round(seg.end, 3), "text": seg.text.strip()})
                if info.duration:
                    self.progress.message = f"Transcribed {seg.end:.0f}s / {info.duration:.0f}s"
            return {"text": " ".join(s["text"] for s in out).strip(), "language": info.language, "segments": out}


def _factory(runtime: str) -> Worker:
    workers = {"kokoro": KokoroWorker, "chatterbox": ChatterboxWorker, "faster-whisper": WhisperWorker}
    if runtime not in workers:
        raise SystemExit(f"voice_worker: unknown runtime {runtime!r}")
    log(f"torch {torch.__version__}, CUDA available: {torch.cuda.is_available()}")
    return workers[runtime](runtime)


if __name__ == "__main__":
    serve(_factory)
