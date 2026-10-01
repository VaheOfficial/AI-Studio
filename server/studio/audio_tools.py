"""Audio tools: stem isolation (Demucs) and voice conversion (ASR → TTS in a chosen voice, duration-matched).

Ported from VoiceStudio's Demucs clean-audio path (``dub_pipeline.py`` separation) and ``voice_convert.py``
(``POST /convert``: transcript → profile TTS → single-stage atempo toward the source length, skipped within ±2 %,
clamped 0.5–2.0). Results are regular audio ``Output``s."""

from __future__ import annotations

import shutil
import tempfile
import uuid
import wave
from pathlib import Path

from . import config, db, generation, media
from .dub import tts, worker
from .jobs import JobContext, JobError, jobs
from .models import ModelError
from .runtimes import WorkerError
from .schemas import Job, JobResult, Output

REF = "audio-tools"
ISOLATE_MODES = {"vocals": ("htdemucs", "two"), "stems4": ("htdemucs", "all"), "stems4_ft": ("htdemucs_ft", "all"),
                 "stems6": ("htdemucs_6s", "all")}
STEM_LABELS = {"vocals": "Vocals", "no_vocals": "Instrumental", "drums": "Drums", "bass": "Bass", "other": "Other",
               "guitar": "Guitar", "piano": "Piano"}


def _output_path() -> tuple[str, Path, str]:
    oid = uuid.uuid4().hex[:16]
    return oid, config.OUTPUTS_DIR / "audio" / f"{oid}.wav", f"/files/outputs/audio/{oid}.wav"


def _seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def isolate(upload: Path, filename: str, mode: str) -> Job:
    if mode not in ISOLATE_MODES:
        raise ValueError(f"Unknown mode {mode}")
    return jobs.submit("generate", f"Isolate · {filename[:48]}", lambda ctx: _isolate(ctx, upload, filename, mode),
                       ref=REF)


def _isolate(ctx: JobContext, upload: Path, filename: str, mode: str) -> JobResult:
    model, stems = ISOLATE_MODES[mode]
    tmp = Path(tempfile.mkdtemp(prefix="isolate-", dir=config.UPLOADS_DIR))
    try:
        ctx.update(progress=0.02, message="Decoding audio…")
        src = tmp / "input.wav"
        media.run([media.ffmpeg(), "-y", "-i", str(upload), "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
                   str(src)], ctx, what="decode")
        worker.acquire_gpu(ctx)
        try:
            worker.free_vram(4)
            res = worker.call(ctx, "/separate", {"input": str(src), "out_dir": str(tmp / "stems"), "model": model,
                                                 "stems": stems}, "Separating", (0.05, 0.95))
        finally:
            worker.release_stage_models()
            worker.gpu.release()
        outputs = []
        order = ["vocals", "no_vocals", "drums", "bass", "guitar", "piano", "other"]
        for stem in sorted(res["stems"], key=lambda s: order.index(s) if s in order else 99):
            oid, path, url = _output_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(res["stems"][stem], path)
            o = Output(id=oid, kind="audio", url=url, model_id=model, prompt=f"{STEM_LABELS.get(stem, stem)} · {filename}",
                       params={"tool": "isolate", "stem": stem, "mode": mode, "source": filename},
                       created_at=db.now_iso(), duration_s=round(_seconds(path), 3))
            db.insert_output(o, str(path))
            outputs.append(o)
        return JobResult(outputs=outputs)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        upload.unlink(missing_ok=True)


def convert(upload: Path, filename: str, voice_id: str, tts_model_id: str | None, stt_model_id: str,
            language: str | None, match_duration: bool) -> Job:
    return jobs.submit("generate", f"Convert voice · {filename[:40]}",
                       lambda ctx: _convert(ctx, upload, filename, voice_id, tts_model_id, stt_model_id, language,
                                            match_duration), ref=REF)


def _convert(ctx: JobContext, upload: Path, filename: str, voice_id: str, tts_model_id: str | None,
             stt_model_id: str, language: str | None, match_duration: bool) -> JobResult:
    tmp = Path(tempfile.mkdtemp(prefix="convert-", dir=config.UPLOADS_DIR))
    try:
        src = tmp / "source.wav"
        media.run([media.ffmpeg(), "-y", "-i", str(upload), "-vn", "-ar", "16000", "-ac", "1", str(src)], ctx,
                  what="decode")
        source_s = _seconds(src)
        worker.acquire_gpu(ctx)
        try:
            ctx.update(progress=0.1, message="Transcribing the source…")
            try:
                heard = generation.transcribe(stt_model_id, src, language)
            except (ModelError, WorkerError) as exc:
                raise JobError(f"Transcription failed: {exc}") from exc
            text = heard.text.strip()
            if not text:
                raise JobError("No speech was recognised in the source audio")
            from .dub.pipeline import voice_lang

            lang = language or voice_lang(heard.language)
            m = tts.model(tts_model_id)
            tts.check_language(m, lang)
            tts.load(ctx, m)
            voice = tts.profile_voice(m, voice_id, lang)
            ctx.update(progress=0.5, message="Speaking it in the new voice…")
            spoken = tmp / "spoken.wav"
            natural = tts.synthesize(m, tts.Line(text=text, out_path=spoken, lang=lang, voice=voice))
        finally:
            worker.gpu.release()
        oid, path, url = _output_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        ratio = natural / source_s if source_s else 1.0
        if match_duration and abs(ratio - 1.0) > 0.02:
            rate = max(0.5, min(2.0, ratio))
            ctx.update(progress=0.9, message=f"Matching the source length ({rate:.2f}×)…")
            media.run([media.ffmpeg(), "-y", "-i", str(spoken), "-af", media.atempo_chain(rate), str(path)], ctx,
                      what="duration match")
        else:
            shutil.move(spoken, path)
        o = Output(id=oid, kind="audio", url=url, model_id=m.id, prompt=text,
                   params={"tool": "convert", "voice_id": voice_id, "voice": voice.label, "source": filename,
                           "language": lang, "source_s": round(source_s, 2)},
                   created_at=db.now_iso(), duration_s=round(_seconds(path), 3))
        db.insert_output(o, str(path))
        return JobResult(outputs=[o])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        upload.unlink(missing_ok=True)
