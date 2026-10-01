"""Audiobook rendering as a Job (ported from VoiceStudio ``services/audiobook.py`` ``synthesize_chapter``,
``services/longform_render.py`` and ``services/loudness.py``).

Per span: voice from ``[voice:NAME]`` → cast, text synthesized (the TTS worker chunks long text and crossfades),
line/paragraph gaps and ``[pause]`` silences joined in. Every spoken span is content-addressed in a segment cache
and every chapter in a chapter cache, so an edit re-renders only what changed and an interrupted book resumes.
Chapters mux into m4b (AAC + chapter marks + cover) or mp3, optionally two-pass loudness-normalised."""

from __future__ import annotations

import hashlib
import json
import math
import re
import wave
import zlib
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import db, media
from ..dub import tts, worker
from ..jobs import JobContext, JobError, jobs
from ..schemas import Job
from ..schemas_dub import AudiobookSettings
from . import script, store

LOUDNESS = {"acx": (-19.0, -3.0, 11.0), "podcast": (-16.0, -1.5, 11.0)}
_GLOBAL_TAGS = [("title", "title"), ("author", "artist"), ("narrator", "composer"), ("year", "date"),
                ("genre", "genre"), ("description", "comment")]
TRIM_FLOOR = int(32767 * 10 ** (-45 / 20))  # −45 dBFS
TRIM_KEEP_S = 0.04
MAX_JOIN_SILENCE_MS = 15 * 60 * 1000


class AudiobookError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def ref(pid: str) -> str:
    return f"audiobook:{pid}"


def run(pid: str, preview_chapter: int | None) -> Job:
    p = store.get(pid)
    chapters = script.parse(p["script"])
    if not chapters:
        raise AudiobookError("The script is empty")
    if preview_chapter is not None and preview_chapter >= len(chapters):
        raise AudiobookError("No such chapter")
    if jobs.find_active(lambda j: j.ref == ref(pid)):
        raise AudiobookError("A render is already running for this audiobook", 409)
    title = (f"Audiobook · preview {chapters[preview_chapter].title[:30]}" if preview_chapter is not None
             else f"Audiobook · {p['name'][:40]}")
    return jobs.submit("generate", title, lambda ctx: _render(ctx, pid, preview_chapter), ref=ref(pid))


def segment_seed(base: int, text: str) -> int:
    """Pinned-seed renders stay reproducible per line (VoiceStudio ``audiobook.segment_seed``)."""
    return (int(base) + zlib.crc32(text.encode("utf-8"))) % (2**31)


def _key(payload: Any) -> str:
    return hashlib.sha1(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode(), usedforsecurity=False
                        ).hexdigest()[:20]


def _read_pcm(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            raise JobError(f"Unexpected audio format in {path.name}")
        return w.readframes(w.getnframes()), w.getframerate()


def _trim(pcm: bytes, rate: int) -> bytes:
    """Drop engine lead-in/tail silence (keep 40 ms) so the configured gaps are the real gaps."""
    samples = memoryview(pcm).cast("h")
    n = len(samples)
    first = next((i for i in range(n) if abs(samples[i]) > TRIM_FLOOR), None)
    if first is None:
        return pcm
    last = next(i for i in range(n - 1, -1, -1) if abs(samples[i]) > TRIM_FLOOR)
    keep = int(rate * TRIM_KEEP_S)
    return pcm[max(0, first - keep) * 2:min(n, last + 1 + keep) * 2]


def _silence(ms: int, rate: int) -> bytes:
    return b"\x00\x00" * int(rate * ms / 1000)


def _gap_after(span: script.Span, st: AudiobookSettings) -> int:
    if span.pause_ms_after > 0 or span.join == "continue":
        return 0
    if span.join == "paragraph":
        return st.paragraph_gap_ms or st.line_gap_ms
    return st.line_gap_ms


def _render(ctx: JobContext, pid: str, preview_chapter: int | None) -> None:
    p = store.get(pid)
    st = AudiobookSettings.model_validate(p["settings"])
    chapters = script.parse(p["script"])
    m = tts.model(st.tts_model_id)
    lang = st.language or None
    tts.check_language(m, lang)
    d = store.project_dir(pid)
    seg_dir, ch_dir = d / "segments", d / "chapters"
    seg_dir.mkdir(parents=True, exist_ok=True)
    ch_dir.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    unmapped = sorted({s.voice for c in chapters for s in c.spans if s.voice and s.voice not in st.voice_map})
    if unmapped:
        notes.append(f"Uncast voices use the default voice: {', '.join(unmapped)}")

    worker.acquire_gpu(ctx)
    try:
        tts.load(ctx, m)
        voices: dict[str, tts.Voice] = {}

        def voice_for(name: str | None) -> tuple[str, tts.Voice]:
            vid = st.voice_map.get(name or "", st.default_voice) if name else st.default_voice
            if vid not in voices:
                voices[vid] = tts.profile_voice(m, vid, lang)
            return vid, voices[vid]

        engine_sig = {"model": m.id, "steps": st.num_step, "cfg": st.guidance, "lang": lang, "seed": st.seed,
                      "speed": st.speed}
        selected = [preview_chapter] if preview_chapter is not None else list(range(len(chapters)))
        spans_total = sum(len(chapters[i].spans) for i in selected) or 1
        done_spans = 0
        chapter_files: list[tuple[str, Path, float]] = []
        cached_chapters = 0
        for ci in selected:
            ch = chapters[ci]
            sigs = {}
            for span in ch.spans:
                vid, v = voice_for(span.voice)
                sigs[vid] = [v.ref_audio, v.ref_text, v.instruct, v.seed]
            ch_key = _key({"spans": [[s.voice, s.text, s.pause_ms_after, s.speed, s.join] for s in ch.spans],
                           "engine": engine_sig, "voices": sigs, "map": st.voice_map, "default": st.default_voice,
                           "gaps": [st.line_gap_ms, st.paragraph_gap_ms]})
            ch_path = ch_dir / f"{ch_key}.wav"
            if ch_path.is_file():
                cached_chapters += 1
                done_spans += len(ch.spans)
                with wave.open(str(ch_path), "rb") as w:
                    chapter_files.append((ch.title, ch_path, w.getnframes() / w.getframerate()))
                continue
            rate = 0
            parts: list[bytes] = []
            pending_gap = 0
            silence_ms = 0
            for span in ch.spans:
                ctx.check_cancelled()
                if span.text:
                    vid, v = voice_for(span.voice)
                    paragraphs = script.split_paragraphs(span.text) if st.paragraph_gap_ms else [span.text]
                    rendered: list[bytes] = []
                    for para in paragraphs or [span.text]:
                        base_seed = st.seed if st.seed is not None else v.seed
                        seg_voice = replace(v, seed=segment_seed(base_seed, para)) if base_seed is not None else v
                        speed = (span.speed or 1.0) * st.speed
                        seg_key = _key({"text": para, "voice": vid, "sig": sigs[vid], "speed": speed,
                                        "engine": engine_sig})
                        seg_path = seg_dir / f"{seg_key}.wav"
                        if not seg_path.is_file():
                            ctx.update(progress=round(0.9 * done_spans / spans_total, 3),
                                       message=f"{ch.title}: {para[:60]}")
                            tts.synthesize(m, tts.Line(text=para, out_path=seg_path, lang=lang, voice=seg_voice,
                                                       speed=speed, num_step=st.num_step, guidance=st.guidance))
                        pcm, r = _read_pcm(seg_path)
                        rate = rate or r
                        if r != rate:
                            raise JobError("Segments came back at different sample rates")
                        rendered.append(_trim(pcm, rate))
                    if pending_gap:
                        parts.append(_silence(pending_gap, rate))
                        silence_ms += pending_gap
                    for k, chunk in enumerate(rendered):
                        if k:
                            parts.append(_silence(st.paragraph_gap_ms, rate))
                            silence_ms += st.paragraph_gap_ms
                        parts.append(chunk)
                    pending_gap = _gap_after(span, st)
                if span.pause_ms_after:
                    pending_gap = 0
                    parts.append(_silence(span.pause_ms_after, rate or 24000))
                if silence_ms > MAX_JOIN_SILENCE_MS:
                    raise JobError("The line/paragraph gaps add up to over 15 minutes in one chapter — reduce them")
                done_spans += 1
            pcm = b"".join(parts)
            with wave.open(str(ch_path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rate or 24000)
                w.writeframes(pcm)
            chapter_files.append((ch.title, ch_path, len(pcm) / 2 / (rate or 24000)))
    finally:
        worker.gpu.release()

    if preview_chapter is not None:
        title, path, dur = chapter_files[0]
        rel = path.relative_to(d).as_posix()
        store.update(pid, lambda proj: proj["previews"].update(
            {str(preview_chapter): {"url": store.url(pid, rel), "duration": round(dur, 2)}}))
        ctx.update(progress=1.0, message=f"Preview of {title} ready")
        return
    _mux(ctx, pid, st, chapter_files, cached_chapters, notes)


def _ffmetadata(chapters: list[tuple[str, float]], meta: dict[str, str]) -> str:
    def esc(value: str) -> str:
        return re.sub(r"([=;#\\\n])", r"\\\1", value)

    lines = [";FFMETADATA1"]
    lines += [f"{tag}={esc(meta[key].strip())}" for key, tag in _GLOBAL_TAGS if meta.get(key, "").strip()]
    start = 0
    for title, seconds in chapters:
        end = start + max(0, int(round(seconds * 1000)))
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={end}", f"title={esc(title)}"]
        start = end
    return "\n".join(lines) + "\n"


def _measure(ctx: JobContext, concat: Path, preset: str) -> dict[str, float] | None:
    """First loudnorm pass; any failure falls back to single-pass normalisation."""
    i, tp, lra = LOUDNESS[preset]
    try:
        err = media.run([media.ffmpeg(), "-hide_banner", "-f", "concat", "-safe", "0", "-i", str(concat), "-af",
                         f"loudnorm=I={i}:TP={tp}:LRA={lra}:print_format=json", "-f", "null", "-"], ctx,
                        what="loudness measure")
    except media.MediaError:
        return None
    block = err[err.rfind("{"):err.rfind("}") + 1]
    try:
        obj = json.loads(block)
        values = {k: float(obj[k]) for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}
    except (ValueError, KeyError):
        return None
    return values if all(math.isfinite(v) for v in values.values()) else None


def _mux(ctx: JobContext, pid: str, st: AudiobookSettings, files: list[tuple[str, Path, float]], cached: int,
         notes: list[str]) -> None:
    p = store.get(pid)
    d = store.project_dir(pid)
    concat = d / "concat.txt"
    concat.write_text("".join(f"file '{path.as_posix()}'\n" for _, path, _ in files), encoding="utf-8")
    meta_path = d / "chapters.ffmeta"
    meta = st.metadata.model_dump()
    meta["title"] = meta["title"] or p["name"]
    meta_path.write_text(_ffmetadata([(t, dur) for t, _, dur in files], meta), encoding="utf-8")
    cover = d / p["cover"] if p.get("cover") and st.format == "m4b" else None
    af = None
    if st.loudness != "off":
        i, tp, lra = LOUDNESS[st.loudness]
        ctx.update(progress=0.92, message=f"Measuring loudness ({st.loudness.upper()})…")
        measured = _measure(ctx, concat, st.loudness)
        af = f"loudnorm=I={i}:TP={tp}:LRA={lra}"
        if measured:
            af += (f":measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
                   f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
                   f":offset={measured['target_offset']}:linear=true")
        else:
            notes.append("Loudness measurement failed; used single-pass normalisation")
    stamp = db.now_iso().replace(":", "").replace("-", "")[:15]
    safe = re.sub(r"[^\w\- ]+", "", p["name"]).strip().replace(" ", "_") or "audiobook"
    out = d / f"{safe}_{stamp}.{st.format}"
    cmd = [media.ffmpeg(), "-y", "-hide_banner", "-f", "concat", "-safe", "0", "-i", str(concat), "-i", str(meta_path)]
    if cover:
        cmd += ["-i", str(cover)]
    cmd += ["-map", "0:a", "-map_metadata", "1"]
    if cover:
        cmd += ["-map", "2:v", "-disposition:v", "attached_pic"]
    if af:
        cmd += ["-af", af]
    if st.format == "mp3":
        cmd += ["-c:a", "libmp3lame", "-b:a", st.bitrate, "-f", "mp3", str(out)]
    else:
        cmd += ["-c:a", "aac", "-b:a", st.bitrate] + (["-c:v", "copy"] if cover else []) + [
            "-movflags", "+faststart", "-f", "mp4", str(out)]
    ctx.update(progress=0.95, message=f"Muxing {st.format.upper()}…")
    media.run(cmd, ctx, what="audiobook mux", timeout=7200)
    marks, start = [], 0.0
    for title, _, dur in files:
        marks.append({"title": title, "start": round(start, 3), "end": round(start + dur, 3)})
        start += dur
    entry = {"id": hashlib.sha1(out.name.encode(), usedforsecurity=False).hexdigest()[:12],
             "url": store.url(pid, out.name), "filename": out.name, "format": st.format,
             "duration": round(media.duration(out), 2), "size": out.stat().st_size, "chapters": marks,
             "cached_chapters": cached, "created_at": db.now_iso()}
    store.update(pid, lambda proj: proj["renders"].insert(0, entry))
    notes.insert(0, f"{len(files)} chapter(s), {cached} from cache")
    ctx.update(progress=1.0, message="; ".join(notes))
