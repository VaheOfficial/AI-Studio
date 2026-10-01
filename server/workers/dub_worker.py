"""Dubbing / audio-tools runtime: Demucs separation, faster-whisper ASR with word timestamps, pyannote 3.1
diarization, NLLB-200 translation, onset analysis, clone-reference cutting and dub-track assembly.

Ported from VoiceStudio (``services/dub_pipeline.py`` separation, ``services/asr_backend.py``,
``api/routers/dub_core.py`` diarization + phrase-embedding recovery, ``services/onset_align.py``,
``services/speaker_clone.py``, ``api/routers/dub_translate.py`` NLLB, ``api/routers/dub_generate.py`` assembly,
``services/dub_background.py`` bed splice). Stage models load lazily and stay resident until ``/unload``; the
server unloads them between pipeline stages so the TTS model can take the GPU.
"""

from __future__ import annotations

import gc
import os
import subprocess
from pathlib import Path
from typing import Any

from worker_base import BadRequest, Worker, free_cuda, log, serve

import numpy as np
import soundfile as sf
import torch

NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

# ------------------------------------------------------------------ onset analysis (onset_align.py)

FRAME_S = 0.02
PRE_ROLL_S = 0.05
MIN_SHIFT_S = 0.15
MIN_SEG_DUR_S = 0.30
RELATIVE_THRESHOLD = 0.10
ABS_RMS_FLOOR = 1e-3
SUSTAIN_WINDOW_S = 0.30
SUSTAIN_MIN_S = 0.16
MAX_SNAP_S = 1.5
SKIPPED_AUDIBLE_FRAC = 0.10
SKIPPED_FLOOR_PEAK_FRAC = 0.02
MIN_ONSET_GAP_S = 0.15


def _frame_rms(x: np.ndarray, frame_len: int) -> np.ndarray:
    n = (len(x) // frame_len) * frame_len
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    frames = x[:n].reshape(-1, frame_len).astype(np.float64, copy=False)
    return np.sqrt((frames * frames).mean(axis=1)).astype(np.float32)


def _detect_speech_onset(audio: np.ndarray, sr: int, start_s: float, end_s: float) -> float | None:
    """First *sustained* speech-like frame in [start_s, end_s] (footsteps/clicks don't count)."""
    i0, i1 = max(0, int(start_s * sr)), min(len(audio), int(end_s * sr))
    if i1 <= i0:
        return None
    frame_len = max(1, int(FRAME_S * sr))
    rms = _frame_rms(audio[i0:i1], frame_len)
    if rms.size == 0 or float(rms.max()) < ABS_RMS_FLOOR:
        return None
    above = rms >= max(RELATIVE_THRESHOLD * float(rms.max()), ABS_RMS_FLOOR)
    candidates = np.nonzero(above)[0]
    if candidates.size == 0:
        return None
    frame_s = frame_len / sr
    win = max(1, int(round(SUSTAIN_WINDOW_S / frame_s)))
    need = max(1, int(round(SUSTAIN_MIN_S / frame_s)))
    cum = np.concatenate(([0], np.cumsum(above)))
    counts = cum[np.minimum(candidates + win, above.size)] - cum[candidates]
    sustained = candidates[counts >= need]
    return None if sustained.size == 0 else start_s + float(sustained[0]) * frame_s


def _region_mostly_silent(audio: np.ndarray, sr: int, start_s: float, end_s: float) -> bool:
    i0, i1 = max(0, int(start_s * sr)), min(len(audio), int(end_s * sr))
    if i1 <= i0:
        return True
    rms = _frame_rms(audio[i0:i1], max(1, int(FRAME_S * sr)))
    if rms.size == 0:
        return True
    floor = max(ABS_RMS_FLOOR, SKIPPED_FLOOR_PEAK_FRAC * float(rms.max()))
    return float((rms >= floor).mean()) <= SKIPPED_AUDIBLE_FRAC


def _detect_onsets(audio: np.ndarray, sr: int) -> list[float]:
    frame_len = max(1, int(FRAME_S * sr))
    rms = _frame_rms(audio, frame_len)
    if rms.size == 0 or float(rms.max()) < ABS_RMS_FLOOR:
        return []
    threshold = max(RELATIVE_THRESHOLD * float(rms.max()), ABS_RMS_FLOOR)
    gap_frames = max(1, int(round(MIN_ONSET_GAP_S / FRAME_S)))
    frame_s = frame_len / sr
    onsets: list[float] = []
    below = gap_frames
    for i, v in enumerate(rms):
        if v >= threshold:
            if below >= gap_frames:
                onsets.append(round(i * frame_s, 3))
            below = 0
        else:
            below += 1
    return onsets


def _mono(path: str) -> tuple[np.ndarray, int]:
    audio, sr = sf.read(path, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return audio, int(sr)


# ------------------------------------------------------------------ clone references (speaker_clone.py)

MIN_REF_DURATION_S = 5.0
MAX_REF_DURATION_S = 15.0
IDEAL_REF_DURATION_S = 8.0
MIN_SEGMENT_REF_DURATION_S = 3.0
MIN_SLICE_DURATION_S = 1.5
ADJACENT_TURN_GUARD_S = 0.3
# OmniVoice sizes an un-timed render from its reference's speaking rate (transcript length per second of
# reference audio). Chants, singing and drawn-out lines have few characters per second, so a reference built
# from them makes every cloned line come out several times too long; normal speech is ~9-15 chars/s.
MIN_REF_CHARS_PER_S = 5.0
MAX_REF_PAUSE_S = 0.3   # pauses inside a reference line longer than this are shortened to REF_PAUSE_S
REF_PAUSE_S = 0.15
WORD_PAD_S = 0.05       # kept around each word run so trimming never clips a word edge
NEXT_LINE_GUARD_S = 0.05  # silence kept before the next line when a concise line runs on into the gap
OVERFLOW_FADE_S = 0.12    # fade-out on a line trimmed because it doesn't fit even after using the gap


def _safe_name(value: str) -> str:
    out = "".join(ch if ch.isalnum() else "_" if ch in " -" else "" for ch in value.lower())
    return out or "speaker"


def _adjacent_to_other(seg: dict, speaker: str, segments: list[dict]) -> bool:
    s0, s1 = float(seg["start"]), float(seg["end"])
    for other in segments:
        if other is seg or other["speaker"] == speaker:
            continue
        if max(float(other["start"]) - s1, s0 - float(other["end"])) < ADJACENT_TURN_GUARD_S:
            return True
    return False


def _speech_runs(seg: dict) -> list[tuple[float, float]]:
    """The segment's speech as time runs from its word timings: leading/trailing silence dropped and the line
    split wherever it pauses longer than ``MAX_REF_PAUSE_S``. Without word timings, the whole segment."""
    s0, s1 = float(seg["start"]), float(seg["end"])
    runs: list[list[float]] = []
    for w in seg.get("words") or []:
        a, b = max(s0, float(w["start"]) - WORD_PAD_S), min(s1, float(w["end"]) + WORD_PAD_S)
        if b <= a:
            continue
        if runs and a - runs[-1][1] <= MAX_REF_PAUSE_S:
            runs[-1][1] = max(runs[-1][1], b)
        else:
            runs.append([a, b])
    return [(a, b) for a, b in runs] or [(s0, s1)]


def _speech_seconds(seg: dict) -> float:
    return sum(b - a for a, b in _speech_runs(seg))


def _natural_rate(seg: dict) -> bool:
    """Whether the line is spoken at a rate a TTS voice reference can be sized from (see MIN_REF_CHARS_PER_S)."""
    seconds = _speech_seconds(seg)
    return seconds > 0 and len(seg["text"].strip()) / seconds >= MIN_REF_CHARS_PER_S


def _speech_audio(audio: np.ndarray, sr: int, seg: dict) -> np.ndarray:
    """The segment's speech runs joined with short ``REF_PAUSE_S`` silences."""
    pause = np.zeros(int(REF_PAUSE_S * sr), dtype=np.float32)
    parts: list[np.ndarray] = []
    for a, b in _speech_runs(seg):
        s, e = max(0, int(a * sr)), min(audio.size, int(b * sr))
        if e > s:
            parts.extend([pause, audio[s:e]] if parts else [audio[s:e]])
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)


def _pick_reference_slices(items: list[tuple[int, dict]], speaker: str, segments: list[dict]) -> list[tuple[int, dict]]:
    """Natural-rate lines only, clean turns (not next to another speaker) first, longest speech first;
    accumulate ~8 s of speech, cap 15 s, need ≥5 s."""
    def dur(pair: tuple[int, dict]) -> float:
        return _speech_seconds(pair[1])

    natural = [p for p in items if _natural_rate(p[1])]
    ranked = sorted(natural, key=lambda p: (_adjacent_to_other(p[1], speaker, segments), -dur(p)))
    picked: list[tuple[int, dict]] = []
    total = 0.0
    for pair in ranked:
        d = dur(pair)
        if d < MIN_SLICE_DURATION_S or (total + d > MAX_REF_DURATION_S and picked):
            continue
        picked.append(pair)
        total += d
        if total >= IDEAL_REF_DURATION_S:
            break
    if total < MIN_REF_DURATION_S:
        return []
    return sorted(picked, key=lambda p: p[0])


# ------------------------------------------------------------------ NLLB language codes (dub_translate.py)

FLORES_CODES = {
    "en": "eng_Latn", "es": "spa_Latn", "fr": "fra_Latn", "de": "deu_Latn", "it": "ita_Latn", "pt": "por_Latn",
    "ru": "rus_Cyrl", "ja": "jpn_Jpan", "ko": "kor_Hang", "zh": "zho_Hans", "zh-cn": "zho_Hans",
    "zh-hans": "zho_Hans", "zh-tw": "zho_Hant", "zh-hant": "zho_Hant", "yue": "yue_Hant", "ar": "arb_Arab",
    "hi": "hin_Deva", "tr": "tur_Latn", "pl": "pol_Latn", "nl": "nld_Latn", "sv": "swe_Latn", "th": "tha_Thai",
    "vi": "vie_Latn", "id": "ind_Latn", "uk": "ukr_Cyrl", "bn": "ben_Beng", "ta": "tam_Taml", "te": "tel_Telu",
    "ml": "mal_Mlym", "kn": "kan_Knda", "gu": "guj_Gujr", "mr": "mar_Deva", "ur": "urd_Arab", "fa": "pes_Arab",
    "he": "heb_Hebr", "el": "ell_Grek", "cs": "ces_Latn", "da": "dan_Latn", "fi": "fin_Latn", "nb": "nob_Latn",
    "no": "nob_Latn", "nn": "nno_Latn", "ro": "ron_Latn", "hu": "hun_Latn", "bg": "bul_Cyrl", "sk": "slk_Latn",
    "sl": "slv_Latn", "hr": "hrv_Latn", "sr": "srp_Cyrl", "lt": "lit_Latn", "et": "est_Latn", "sw": "swh_Latn",
    "af": "afr_Latn", "ms": "zsm_Latn",
}


def _flores(code: str) -> str | None:
    from transformers.models.nllb.tokenization_nllb import FAIRSEQ_LANGUAGE_CODES

    norm = code.strip().replace("_", "-").lower()
    if norm in FLORES_CODES:
        return FLORES_CODES[norm]
    exact = [c for c in FAIRSEQ_LANGUAGE_CODES if c.replace("_", "-").lower() == norm]
    if exact:
        return exact[0]
    matches = [c for c in FAIRSEQ_LANGUAGE_CODES if c.split("_")[0] == norm]
    return matches[0] if len(matches) == 1 else None


# ------------------------------------------------------------------ assembly helpers (dub_generate.py)


def _trim_speech_padding(audio: np.ndarray, sr: int) -> np.ndarray:
    """Remove generated edge silence (−50 dBFS) keeping 50 ms of context; internal pauses untouched."""
    voiced = np.nonzero(np.abs(audio) > 10 ** (-50 / 20))[0]
    if voiced.size == 0:
        return audio
    margin = int(sr * 0.05)
    return audio[max(0, int(voiced[0]) - margin):min(audio.size, int(voiced[-1]) + 1 + margin)]


def _atempo_chain(ratio: float) -> str:
    stages: list[str] = []
    while ratio > 2.0:
        stages.append("atempo=2.0")
        ratio /= 2.0
    while ratio < 0.5:
        stages.append("atempo=0.5")
        ratio /= 0.5
    stages.append(f"atempo={ratio:.6f}")
    return ",".join(stages)


def _stretch(ffmpeg: str, audio: np.ndarray, target: int, sr: int) -> np.ndarray:
    """Pitch-preserving stretch to exactly ``target`` samples through ffmpeg atempo; linear fallback."""
    if target <= 0 or audio.size == target or audio.size == 0:
        return audio
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", "1",
             "-i", "pipe:0", "-af", _atempo_chain(audio.size / target), "-f", "f32le", "-ar", str(sr), "-ac", "1",
             "pipe:1"], input=audio.astype(np.float32).tobytes(), capture_output=True, timeout=300,
            creationflags=NO_WINDOW)
        out = np.frombuffer(proc.stdout, dtype=np.float32)
        if proc.returncode != 0 or out.size == 0:
            raise RuntimeError(proc.stderr.decode(errors="replace")[-200:])
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        log(f"atempo failed ({exc}); linear interpolation fallback")
        out = np.interp(np.linspace(0, audio.size - 1, target), np.arange(audio.size), audio).astype(np.float32)
    if out.size < target:
        out = np.concatenate([out, np.zeros(target - out.size, dtype=np.float32)])
    return out[:target].copy()


def _load_resampled(path: str, sr: int) -> np.ndarray:
    audio, file_sr = _mono(path)
    if file_sr != sr and audio.size:
        n = int(round(audio.size * sr / file_sr))
        audio = np.interp(np.linspace(0, audio.size - 1, n), np.arange(audio.size), audio).astype(np.float32)
    return audio


# ------------------------------------------------------------------ worker


class DubWorker(Worker):
    def __init__(self, runtime: str) -> None:
        super().__init__(runtime)
        self.demucs: dict[str, Any] = {}
        self.whisper: tuple[str, Any] | None = None
        self.diarizer: Any = None
        self.nllb: tuple[str, Any, Any] | None = None
        self.routes.update({
            "/separate": self.separate,
            "/transcribe": self.transcribe,
            "/diarize": self.diarize,
            "/analyze": self.analyze,
            "/cut_refs": self.cut_refs,
            "/translate_mt": self.translate_mt,
            "/assemble": self.assemble,
            "/splice_bed": self.splice_bed,
        })

    # -------------------------------------------------------------- lifecycle

    def unload(self, _req: dict[str, Any]) -> dict[str, Any]:
        with self.busy:
            freed = [k for k, v in (("demucs", self.demucs), ("whisper", self.whisper), ("pyannote", self.diarizer),
                                    ("nllb", self.nllb)) if v]
            self.demucs, self.whisper, self.diarizer, self.nllb = {}, None, None, None
            gc.collect()
            free_cuda()
        if freed:
            log(f"Unloaded {', '.join(freed)}")
        return {"ok": True, "freed": freed}

    def health(self) -> dict[str, Any]:
        loaded = [k for k, v in (("demucs", self.demucs), ("whisper", self.whisper), ("pyannote", self.diarizer),
                                 ("nllb", self.nllb)) if v]
        return {**super().health(), "loaded_model": ",".join(loaded) or None}

    # -------------------------------------------------------------- separation

    def _demucs_model(self, name: str) -> Any:
        if name not in self.demucs:
            from demucs.pretrained import get_model

            self.progress.message = f"Loading {name} (first use downloads its weights)"
            model = get_model(name)
            model.to("cuda").eval()
            self.demucs = {name: model}
        return self.demucs[name]

    def separate(self, req: dict[str, Any]) -> dict[str, Any]:
        """``{input, out_dir, model, stems: "two"|"all"}`` → stem wav paths. Input must be a wav at the model
        rate (44.1 kHz stereo), which the server extracts with ffmpeg."""
        import demucs.apply

        with self.busy:
            self.progress.reset(message="Separating")
            model = self._demucs_model(req.get("model") or "htdemucs")
            self.progress.message = "Separating"
            audio, sr = sf.read(req["input"], dtype="float32", always_2d=True)
            if sr != model.samplerate:
                raise BadRequest(f"Separation input must be {model.samplerate} Hz (got {sr})")
            wav = torch.from_numpy(audio.T.copy())
            if wav.shape[0] == 1:
                wav = wav.repeat(2, 1)
            ref = wav.mean(0)
            mean, std = ref.mean(), ref.std() + 1e-8
            progress = self.progress

            class _Tqdm:  # demucs.apply reports its chunk loop through tqdm.tqdm(...)
                @staticmethod
                def tqdm(iterable: Any, **_kw: Any) -> Any:
                    items = list(iterable)
                    progress.total = len(items)
                    for i, item in enumerate(items):
                        progress.check()
                        progress.step = i
                        yield item
                    progress.step = len(items)

            demucs.apply.tqdm = _Tqdm
            with torch.inference_mode():
                sources = demucs.apply.apply_model(model, ((wav - mean) / std)[None], device="cuda", shifts=1,
                                                   split=True, overlap=0.25, progress=True)[0]
            sources = (sources * std + mean).cpu().numpy()
            out_dir = Path(req["out_dir"])
            out_dir.mkdir(parents=True, exist_ok=True)
            names: list[str] = list(model.sources)
            result: dict[str, str] = {}
            if req.get("stems", "two") == "two":
                vocals = sources[names.index("vocals")]
                rest = sources[[i for i, n in enumerate(names) if n != "vocals"]].sum(axis=0)
                for name, data in (("vocals", vocals), ("no_vocals", rest)):
                    path = out_dir / f"{name}.wav"
                    sf.write(str(path), data.T, sr, subtype="PCM_16")
                    result[name] = str(path)
            else:
                for i, name in enumerate(names):
                    path = out_dir / f"{name}.wav"
                    sf.write(str(path), sources[i].T, sr, subtype="PCM_16")
                    result[name] = str(path)
            return {"stems": result, "sample_rate": sr}

    # -------------------------------------------------------------- ASR

    def _whisper(self, model_path: str) -> Any:
        if self.whisper is None or self.whisper[0] != model_path:
            from faster_whisper import WhisperModel

            self.whisper = None
            gc.collect()
            self.progress.message = "Loading speech recognition model"
            model = None
            for compute in ("float16", "int8_float16", "int8"):
                try:
                    model = WhisperModel(model_path, device="cuda", compute_type=compute)
                    break
                except (ValueError, RuntimeError) as exc:
                    log(f"faster-whisper compute_type={compute} failed: {exc}")
            if model is None:
                raise BadRequest(f"Could not load the speech recognition model at {model_path}")
            self.whisper = (model_path, model)
        return self.whisper[1]

    @staticmethod
    def _asr_row(seg: Any, words_on: bool, offset: float = 0.0) -> dict[str, Any]:
        row: dict[str, Any] = {"start": round(seg.start + offset, 3), "end": round(seg.end + offset, 3),
                               "text": seg.text.strip()}
        if words_on:
            # ``sp``: whether a space precedes the word — Whisper tokens carry it, and it is absent for
            # continuations ("Тили" + "-мили") and scripts written without spaces (see segmentation.Word).
            row["words"] = [{"word": w.word.strip(), "sp": w.word[:1].isspace(), "start": round(w.start + offset, 3),
                             "end": round(w.end + offset, 3), "prob": round(float(w.probability), 3)}
                            for w in (seg.words or []) if w.word.strip()]
        return row

    def transcribe(self, req: dict[str, Any]) -> dict[str, Any]:
        """``{path, model_path, language?, word_timestamps=true, gap_pass?: {min_gap, min_dbfs}}`` → segments with
        words. ``gap_pass`` re-listens to speech-loud stretches the full-file pass left empty (see ``_gap_pass``)."""
        with self.busy:
            self.progress.reset(message="Transcribing")
            model = self._whisper(req["model_path"])
            words_on = bool(req.get("word_timestamps", True))
            segments, info = model.transcribe(req["path"], language=req.get("language") or None,
                                              word_timestamps=words_on, vad_filter=True, beam_size=5)
            total = float(info.duration or 0.0)
            self.progress.total = int(total) or 0
            out = []
            for seg in segments:
                self.progress.check()
                out.append(self._asr_row(seg, words_on))
                self.progress.step = int(seg.end)
                self.progress.message = f"Transcribed {seg.end:.0f}s / {total:.0f}s"
            recovered = 0
            if req.get("gap_pass"):
                extra = self._gap_pass(model, req, out, total, words_on)
                recovered = len(extra)
                out = sorted(out + extra, key=lambda r: r["start"])
            return {"segments": out, "language": info.language, "recovered": recovered,
                    "language_probability": round(float(info.language_probability or 0.0), 3), "duration": total}

    def _gap_pass(self, model: Any, req: dict[str, Any], out: list[dict[str, Any]], total: float,
                  words_on: bool) -> list[dict[str, Any]]:
        """Whisper decodes long audio in 30 s windows and drops short lines in them (notably next to music or
        singing), yet finds them when given the stretch on its own. Re-transcribe each empty stretch whose
        (separated) vocals are as loud as speech; keep only confident results, since Whisper invents text —
        e.g. phantom subtitle credits — over non-speech."""
        import numpy as np
        from faster_whisper import decode_audio

        opts = req["gap_pass"]
        min_gap, min_dbfs = float(opts.get("min_gap", 1.0)), float(opts.get("min_dbfs", -30.0))
        sr = 16000
        audio = decode_audio(req["path"], sampling_rate=sr)
        spans = sorted((r["start"], r["end"]) for r in out)
        gaps, cursor = [], 0.0
        for a, b in spans + [(total, total)]:
            if a - cursor >= min_gap:
                gaps.append((cursor, a))
            cursor = max(cursor, b)
        loud = []
        for a, b in gaps:
            clip = audio[int(a * sr):int(b * sr)]
            if clip.size and 20 * np.log10(np.sqrt(np.mean(clip ** 2)) + 1e-9) >= min_dbfs:
                loud.append((a, clip))
        found: list[dict[str, Any]] = []
        for i, (a, clip) in enumerate(loud):
            self.progress.check()
            self.progress.message = f"Re-checking missed speech ({i + 1}/{len(loud)})"
            # No VAD here: the stretch was already chosen by its speech-level loudness, and Silero VAD is what cut
            # these short lines (and bright cartoon voices) in the first place. no_speech_prob does the filtering.
            segs, _ = model.transcribe(clip, language=req.get("language") or None, word_timestamps=words_on,
                                       vad_filter=False, beam_size=5, condition_on_previous_text=False)
            for seg in segs:
                if seg.no_speech_prob > 0.6 or seg.avg_logprob < -1.0 or seg.compression_ratio > 2.4:
                    continue
                row = self._asr_row(seg, words_on, offset=a)
                if row["text"] and (not words_on or row["words"]):
                    found.append(row)
        log(f"gap pass: {len(gaps)} gaps, {len(loud)} speech-loud, {len(found)} segments recovered")
        return found

    # -------------------------------------------------------------- diarization

    def _pyannote(self) -> Any:
        if self.diarizer is None:
            from pyannote.audio import Pipeline

            self.progress.message = "Loading pyannote speaker-diarization-3.1"
            # pyannote 3.x checkpoints (Lightning) predate torch's weights_only default; they come from the
            # pinned official repos, so load them the way they were saved — for this call only.
            original_load = torch.load

            def trusted_load(*args: Any, **kwargs: Any) -> Any:
                kwargs["weights_only"] = False
                return original_load(*args, **kwargs)

            torch.load = trusted_load
            try:
                pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1",
                                                use_auth_token=os.environ.get("HF_TOKEN") or None)
            finally:
                torch.load = original_load
            if pipe is None:
                raise PermissionError("pyannote returned no pipeline (terms not accepted?)")
            pipe.to(torch.device("cuda"))
            self.diarizer = pipe
        return self.diarizer

    def diarize(self, req: dict[str, Any]) -> dict[str, Any]:
        """``{path, num_speakers?, phrases?}`` → ``{available, reason?, detail?, turns, phrase_turns?}``.
        ``phrase_turns`` is the two-speaker recovery (pyannote embeddings of ASR phrases + agglomerative
        clustering) when pyannote collapsed a two-speaker exchange into one voice."""
        with self.busy:
            self.progress.reset(message="Identifying speakers")
            if not os.environ.get("HF_TOKEN"):
                return {"available": False, "reason": "no_token", "turns": []}
            try:
                pipe = self._pyannote()
            except Exception as exc:  # gated repo / missing weights / load failure
                text = f"{type(exc).__name__}: {exc}"
                reason = ("license" if type(exc).__name__ in ("GatedRepoError", "PermissionError") or "403" in text
                          else "no_token" if "401" in text else "load_failed")
                log(f"pyannote unavailable ({reason}): {text[:300]}")
                return {"available": False, "reason": reason, "detail": text[:400], "turns": []}
            audio, sr = sf.read(req["path"], dtype="float32", always_2d=True)
            file = {"waveform": torch.from_numpy(audio.mean(axis=1, keepdims=True).T.copy()), "sample_rate": sr}
            num = req.get("num_speakers")
            diar = pipe(file, num_speakers=int(num)) if num else pipe(file)
            turns = [{"start": round(t.start, 3), "end": round(t.end, 3), "speaker": str(label)}
                     for t, _, label in diar.itertracks(yield_label=True)]
            result: dict[str, Any] = {"available": True, "turns": turns}
            speakers = {t["speaker"] for t in turns}
            if len(speakers) <= 1 and (num in (None, 2)) and req.get("phrases"):
                recovered = self._recover_two_speakers(pipe, file, req["phrases"], num)
                if recovered:
                    result["phrase_turns"], result["separation"] = recovered
            return result

    def _recover_two_speakers(self, pipe: Any, file: dict, phrases: list[dict], requested: int | None
                              ) -> tuple[list[dict], float] | None:
        usable = [p for p in phrases if p.get("text") and float(p["end"]) - float(p["start"]) >= 0.75]
        embedding, audio = getattr(pipe, "_embedding", None), getattr(pipe, "_audio", None)
        if len(usable) < 4 or embedding is None or audio is None:
            return None
        try:
            from pyannote.core import Segment
            from sklearn.cluster import AgglomerativeClustering

            vectors, durations = [], []
            for p in usable:
                start, end = float(p["start"]), float(p["end"])
                waveform, _ = audio.crop(file, Segment(start, end), duration=end - start, mode="pad")
                vector = np.asarray(embedding(waveform[None])).reshape(-1)
                if not np.isfinite(vector).all():
                    return None
                vectors.append(vector)
                durations.append(end - start)
            matrix = np.vstack(vectors)
            labels = np.asarray(AgglomerativeClustering(n_clusters=2, metric="cosine", linkage="average")
                                .fit_predict(matrix))
            if len(set(labels.tolist())) != 2:
                return None
            counts = [int(np.sum(labels == c)) for c in (0, 1)]
            spans = [sum(d for d, lab in zip(durations, labels) if lab == c) for c in (0, 1)]
            if min(counts) < 2 or min(spans) < 1.5:
                return None
            normed = matrix / np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-8)
            sims = normed @ normed.T
            within, cross = [], []
            for a in range(len(labels)):
                for b in range(a + 1, len(labels)):
                    (within if labels[a] == labels[b] else cross).append(float(sims[a, b]))
            if not within or not cross:
                return None
            separation = float(np.mean(within) - np.mean(cross))
            if separation < (0.12 if requested == 2 else 0.18):
                log(f"phrase-embedding speaker recovery rejected (separation={separation:.3f})")
                return None
            names: dict[int, str] = {}
            turns = []
            for p, lab in zip(usable, labels.tolist()):
                names.setdefault(lab, f"SPEAKER_{len(names):02d}")
                turns.append({"start": float(p["start"]), "end": float(p["end"]), "speaker": names[lab]})
            return turns, round(separation, 3)
        except Exception as exc:  # recovery is best-effort; the plain pyannote result stands
            log(f"phrase-embedding speaker recovery failed: {exc}")
            return None

    # -------------------------------------------------------------- analysis

    def analyze(self, req: dict[str, Any]) -> dict[str, Any]:
        """``{path, segments?, separated}`` → speech onsets for the timeline, and (for separated
        vocals) segment starts snapped forward to the real speech onset (onset_align.snap_segment_starts)."""
        audio, sr = _mono(req["path"])
        starts: dict[str, float] = {}
        if req.get("separated") and req.get("segments"):
            for seg in req["segments"]:
                start, end = float(seg["start"]), float(seg["end"])
                if end - start < MIN_SEG_DUR_S + MIN_SHIFT_S:
                    continue
                onset = _detect_speech_onset(audio, sr, start, end)
                if onset is None:
                    continue
                new_start = max(start, onset - PRE_ROLL_S)
                if new_start - start < MIN_SHIFT_S:
                    continue
                if new_start - start > MAX_SNAP_S and not _region_mostly_silent(audio, sr, start, onset):
                    continue
                new_start = min(new_start, end - MIN_SEG_DUR_S)
                if new_start - start >= MIN_SHIFT_S:
                    starts[str(seg["id"])] = round(new_start, 3)
        return {"onsets": _detect_onsets(audio, sr), "starts": starts,
                "duration": round(audio.size / sr, 3) if sr else 0.0}

    def cut_refs(self, req: dict[str, Any]) -> dict[str, Any]:
        """Per-speaker pooled references (skipped for heuristic labels) + per-segment clips with ≥3 s of speech.
        Each reference is the speech of natural-rate lines only — trimmed to their word timings, long pauses
        shortened — paired with those lines' own transcript, so its speaking rate is the speaker's real one."""
        audio, sr = _mono(req["vocals"])
        segments: list[dict] = req["segments"]
        out_dir = Path(req["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        speakers: dict[str, dict] = {}
        if req.get("labels_source") != "heuristic":
            by_speaker: dict[str, list[tuple[int, dict]]] = {}
            for i, seg in enumerate(segments):
                by_speaker.setdefault(seg["speaker"], []).append((i, seg))
            pause = np.zeros(int(REF_PAUSE_S * sr), dtype=np.float32)
            for speaker, items in by_speaker.items():
                chosen = _pick_reference_slices(items, speaker, segments)
                parts: list[np.ndarray] = []
                for _, seg in chosen:
                    speech = _speech_audio(audio, sr, seg)
                    if speech.size:
                        parts.extend([pause, speech] if parts else [speech])
                if not parts:
                    continue
                clip = np.concatenate(parts)
                path = out_dir / f"voice_{_safe_name(speaker)}.wav"
                sf.write(str(path), clip, sr, subtype="PCM_16")
                speakers[speaker] = {"path": str(path), "text": " ".join(s["text"] for _, s in chosen).strip(),
                                     "duration": round(clip.size / sr, 3), "count": len(chosen)}
        clips: dict[str, dict] = {}
        for seg in segments:
            if _speech_seconds(seg) < MIN_SEGMENT_REF_DURATION_S or not _natural_rate(seg):
                continue
            speech = _speech_audio(audio, sr, seg)
            if not speech.size:
                continue
            path = out_dir / f"seg_{_safe_name(str(seg['id']))}.wav"
            sf.write(str(path), speech, sr, subtype="PCM_16")
            clips[str(seg["id"])] = {"path": str(path), "text": seg["text"], "duration": round(speech.size / sr, 3)}
        return {"speakers": speakers, "segments": clips}

    # -------------------------------------------------------------- NLLB

    def translate_mt(self, req: dict[str, Any]) -> dict[str, Any]:
        """``{repo, source, target, texts[]}`` → ``{texts, errors}``; batches of ≤24, one forced BOS per pass."""
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        with self.busy:
            self.progress.reset(message="Translating with NLLB")
            src, tgt = _flores(req["source"]), _flores(req["target"])
            if not src or not tgt:
                bad = [c for c, f in ((req["source"], src), (req["target"], tgt)) if not f]
                raise BadRequest(f"NLLB does not support: {', '.join(bad)}")
            repo = req["repo"]
            if self.nllb is None or self.nllb[0] != repo:
                self.nllb = None
                gc.collect()
                self.progress.message = f"Loading {repo} (first use downloads it)"
                tok = AutoTokenizer.from_pretrained(repo)
                model = AutoModelForSeq2SeqLM.from_pretrained(repo, torch_dtype=torch.float16).to("cuda").eval()
                self.nllb = (repo, tok, model)
            _, tok, model = self.nllb
            texts: list[str] = req["texts"]
            out: list[str] = list(texts)
            errors: dict[int, str] = {}
            todo = [i for i, t in enumerate(texts) if t and t.strip()]
            self.progress.total = len(todo)
            tok.src_lang = src
            bos = tok.convert_tokens_to_ids(tgt)

            def run(rows: list[int]) -> list[str]:
                inputs = tok([texts[i] for i in rows], return_tensors="pt", padding=True).to("cuda")
                with torch.inference_mode():
                    tokens = model.generate(**inputs, forced_bos_token_id=bos, max_length=400, num_beams=4)
                return tok.batch_decode(tokens, skip_special_tokens=True)

            for b in range(0, len(todo), 24):
                self.progress.check()
                rows = todo[b:b + 24]
                try:
                    for i, text in zip(rows, run(rows)):
                        out[i] = text
                except RuntimeError:
                    free_cuda()
                    for i in rows:  # one long row must not sink its neighbours
                        try:
                            out[i] = run([i])[0]
                        except RuntimeError as exc:
                            errors[i] = str(exc)[:200]
                self.progress.step = min(len(todo), b + 24)
            return {"texts": out, "errors": {str(k): v for k, v in errors.items()}}

    # -------------------------------------------------------------- assembly

    def assemble(self, req: dict[str, Any]) -> dict[str, Any]:
        """Place per-segment TTS clips on the dub timeline (dub_generate.py mix loop).

        Strategies: ``strict_slot`` (stretch overruns to the slot, slow underruns ≥ min_rate), ``smart_fit`` and
        ``stretch_video`` (placement + audio rate precomputed by the server's fit planner), ``concise`` (never
        compress; a line may run on through the silence after it). A line that still doesn't fit is trimmed with a
        fade and flagged ``overflow_trimmed`` (an empty render is flagged ``silent``) rather than failing the track —
        the editor badges those lines so they can be fixed one by one. Returns per-segment fit verdicts and actual
        cue spans."""
        ffmpeg: str = req["ffmpeg"]
        items: list[dict] = req["items"]
        strategy: str = req["strategy"]
        sr = int(req.get("sample_rate") or sf.info(items[0]["path"]).samplerate)
        total = max(1, int(float(req["total_s"]) * sr))
        min_rate = float(req.get("min_rate", 0.85))
        mix = np.zeros(total, dtype=np.float32)
        fits: list[dict] = []
        cues: list[dict] = []
        self.progress.reset(total=len(items), message="Assembling dub track")
        for i, item in enumerate(items):
            self.progress.check()
            start, end = float(item["start"]), float(item["end"])
            wav = _load_resampled(item["path"], sr)
            if item.get("text", True):
                if wav.size == 0 or not np.isfinite(wav).all() or not np.any(np.abs(wav) > 1e-6):
                    fits.append({"status": "silent"})
                    cues.append({"start": round(start, 3), "end": round(end, 3)})  # subtitles keep the source slot
                    continue
                wav = _trim_speech_padding(wav, sr)
            wav = wav * max(0.0, min(2.0, float(item.get("gain", 1.0))))
            natural = wav.size / sr
            fit: dict[str, Any]
            limit = 0  # samples the line may occupy; 0 = unbounded
            if strategy in ("smart_fit", "stretch_video"):
                place = float(item["place_at"])
                rate = float(item.get("audio_rate", 1.0))
                if abs(rate - 1.0) > 1e-6 and wav.size:
                    wav = _stretch(ffmpeg, wav, max(1, int(round(wav.size / rate))), sr)
                fit = dict(item.get("fit") or {"status": "fits"})
                if strategy == "smart_fit":
                    limit = int(max(0.0, float(item["new_end"]) - float(item["new_start"])) * sr) + int(sr * 0.02)
            elif strategy == "concise":
                place = start
                # Run on through the silence after the line, keeping a short guard before the next one
                nxt = items[i + 1]["start"] if i + 1 < len(items) else float(req["total_s"])
                effective_end = max(end, nxt - (NEXT_LINE_GUARD_S if i + 1 < len(items) else 0.0))
                effective_end += float(req.get("overflow_budget_s", 0.0))
                limit = int(max(0.0, effective_end - start) * sr)
                fit = {"status": "fits"}
            else:  # strict_slot
                place = start
                slot = int(max(0.0, end - start) * sr)
                fit = {"status": "fits"}
                if slot > 0 and wav.size > slot:
                    fit = {"status": "audio_stretched", "audio_rate": round(wav.size / slot, 3)}
                    wav = _stretch(ffmpeg, wav, slot, sr)
                elif slot > 0 and 0 < wav.size < slot * 0.95 and min_rate < 1.0:
                    rate = max(wav.size / slot, min_rate)
                    fit = {"status": "audio_slowed", "audio_rate": round(rate, 3)}
                    wav = _stretch(ffmpeg, wav, int(round(wav.size / rate)), sr)
            if limit > 0 and wav.size > limit:
                fit.update(status="overflow_trimmed", overflow_s=round((wav.size - limit) / sr, 3))
                wav = wav[:limit].copy()
                tail = min(int(OVERFLOW_FADE_S * sr), wav.size)
                wav[wav.size - tail:] *= np.linspace(1, 0, tail, dtype=np.float32)
            fit["natural_s"] = round(natural, 3)
            fade = int(0.015 * sr)
            if wav.size > fade * 2:
                wav = wav.copy()
                wav[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
                wav[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
            s = int(place * sr)
            if s < 0:
                wav, s = wav[-s:], 0
            e = min(s + wav.size, total)
            if e > s:
                mix[s:e] += np.clip(wav[:e - s], -1.0, 1.0)
            fits.append(fit)
            cues.append({"start": round(place, 3), "end": round(place + wav.size / sr, 3)})
            self.progress.step = i + 1
        out = Path(req["out_path"])
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp.wav")
        sf.write(str(tmp), np.clip(mix, -1.0, 1.0), sr, subtype="PCM_16")
        os.replace(tmp, out)
        return {"fit": fits, "cues": cues, "duration": round(total / sr, 3), "sample_rate": sr}

    def splice_bed(self, req: dict[str, Any]) -> dict[str, Any]:
        """Original audio outside dialogue, separated bed inside (10 ms crossfades inside each interval)."""
        intervals: list[list[float]] = req["intervals"]
        fade_s = 0.01
        with sf.SoundFile(req["original"]) as src, sf.SoundFile(req["separated"]) as bed:
            if src.samplerate != bed.samplerate or src.channels != bed.channels:
                raise BadRequest("Background inputs must have matching sample format")
            with sf.SoundFile(req["output"], "w", samplerate=src.samplerate, channels=src.channels,
                              subtype="FLOAT") as out:
                offset = active = 0
                while True:
                    wave = src.read(65536, dtype="float32", always_2d=True)
                    if not len(wave):
                        break
                    background = bed.read(len(wave), dtype="float32", always_2d=True)
                    if len(background) < len(wave):
                        background = np.pad(background, ((0, len(wave) - len(background)), (0, 0)))
                    times = np.arange(offset, offset + len(wave)) / src.samplerate
                    mask = np.zeros(len(wave), dtype="float32")
                    while active < len(intervals) and intervals[active][1] < times[0]:
                        active += 1
                    for a, b in intervals[active:]:
                        if a > times[-1]:
                            break
                        fade = min(fade_s, (b - a) / 2)
                        mask = np.maximum(mask, np.clip(np.minimum((times - a) / fade, (b - times) / fade), 0, 1))
                    out.write(wave * (1 - mask[:, None]) + background * mask[:, None])
                    offset += len(wave)
        return {"path": req["output"]}


def _factory(runtime: str) -> Worker:
    if runtime != "dub":
        raise SystemExit(f"dub_worker: unknown runtime {runtime!r}")
    log(f"torch {torch.__version__}, CUDA available: {torch.cuda.is_available()}")
    return DubWorker(runtime)


if __name__ == "__main__":
    serve(_factory)
