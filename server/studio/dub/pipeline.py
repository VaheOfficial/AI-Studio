"""Dub pipeline as studio Jobs (ported from VoiceStudio ``services/dub_pipeline.py`` ingest/extract/separate,
``api/routers/dub_core.py`` transcribe/segment/diarize/clone-refs, ``dub_translate.py`` and ``dub_generate.py``).

Every job's ``ref`` is ``dub:<project id>`` so the editor follows its progress over ``job.update`` and reloads
the project when it finishes. Project documents are read-modify-written under ``store.lock()``."""

from __future__ import annotations

import re
import shutil
import subprocess
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..osenv import NO_WINDOW
from .. import db, events, media, settings
from ..jobs import JobContext, JobError, jobs
from ..runtimes import envs
from ..schemas import InstalledModel, Job
from ..schemas_dub import DubRunRequest, DubSettings
from ..textutil import clean_line
from ..voice import languages as voice_langs
from . import director, fit_planner, incremental, qc, segmentation, store, translate as tr, tts, waveform, worker
from .llm import Chat, LLMError

MAX_SEG_REF_S = 15.0
CONSISTENT_MIN_REF_S = 3.0
# A clone reference whose transcript is this sparse for its audio (chars per second) would make OmniVoice size
# every line several times too long; same floor as the worker's MIN_REF_CHARS_PER_S.
MIN_REF_CHARS_PER_S = 5.0


class DubError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def ref(pid: str) -> str:
    return f"dub:{pid}"


def _submit(pid: str, title: str, fn: Callable[[JobContext], None]) -> Job:
    if jobs.find_active(lambda j: j.ref == ref(pid)):
        raise DubError("Another job is already running for this project — wait for it or cancel it", 409)
    return jobs.submit("generate", title, fn, ref=ref(pid))


def _stt_models() -> list[InstalledModel]:
    found = [m for m in db.list_installed() if m.kind == "stt" and m.runtime == "faster-whisper"]
    return sorted(found, key=lambda m: ("large" not in m.id, m.id))


def _asr(p: dict[str, Any]) -> InstalledModel:
    models = _stt_models()
    chosen = next((m for m in models if m.id == p["settings"].get("asr_model_id")), None) or (models[0] if models else None)
    if chosen is None:
        raise JobError("No speech-recognition model is installed. Install a Whisper (faster-whisper) model from Models.")
    return chosen


def default_settings() -> DubSettings:
    s = DubSettings()
    installed = db.list_installed()
    tts_models = [m for m in installed if m.runtime in tts.TTS_RUNTIMES]
    tts_model = next((m for m in tts_models if m.runtime == "omnivoice"), None) or (tts_models[0] if tts_models else None)
    s.tts.model_id = tts_model.id if tts_model else None
    stt = _stt_models()
    s.asr_model_id = stt[0].id if stt else None
    s.translation.model = settings.load().default_chat_model
    return s


def voice_lang(code: str | None) -> str | None:
    """Whisper/ISO code → the OmniVoice language id used across the studio ('ar' → 'arb' etc.)."""
    if not code:
        return None
    if voice_langs.is_known(code):
        return code
    name = tr.L.LANG_NAMES.get(code)
    if name:
        try:
            return voice_langs.id_for_name(name.split(" (")[0])
        except KeyError:
            pass
    return code


def lang_name(code: str) -> str:
    return voice_langs.name_of(code) or tr.L.name(code)


def whisper_lang(code: str | None) -> str | None:
    """OmniVoice id → a Whisper language code (Whisper only takes its own ~100 two-letter codes)."""
    if not code:
        return None
    return {"arb": "ar", "cmn": "zh", "yue": "yue"}.get(code, code if len(code) == 2 else None)


# ------------------------------------------------------------------ create / ingest


def create(upload: Path | None, url: str | None, filename: str, name: str | None, source_lang: str | None,
           num_speakers: int | None) -> tuple[dict[str, Any], Job]:
    pid = store.new_id()
    d = store.project_dir(pid)
    d.mkdir(parents=True, exist_ok=True)
    source: dict[str, Any] = {"id": pid, "kind": "url" if url else "file", "filename": filename,
                              "input_type": "video", "duration": 0.0}
    if url:
        source["url"] = url
    else:
        assert upload is not None
        dest = d / f"original{upload.suffix.lower() or '.bin'}"
        shutil.move(str(upload), dest)
        source["original"] = dest.name
    project = store.create(name or Path(filename).stem or "Untitled dub", source, source_lang,
                           num_speakers or None, default_settings())
    return project, _submit(pid, f"Dub · prepare {filename[:40]}", lambda ctx: _prepare(ctx, pid))


def _yt_dlp(ctx: JobContext, url: str, d: Path) -> str:
    if not envs.is_ready("dub"):
        raise JobError("Downloading from a URL needs the dubbing runtime (yt-dlp) — install it first.")
    cmd = [str(envs.env_python("dub")), "-m", "yt_dlp", "--no-playlist", "--newline", "--no-part",
           "-f", "bv*[height<=1080]+ba/b", "--merge-output-format", "mp4", "-o", str(d / "original.%(ext)s"),
           "--print", "after_move:filepath", "--ffmpeg-location", str(Path(media.ffmpeg()).parent), url]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace", creationflags=NO_WINDOW)
    from ..proc import kill_tree

    ctx.on_cancel(lambda: kill_tree(proc))
    final, tail = "", []
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = clean_line(raw)
        if not line:
            continue
        tail = (tail + [line])[-8:]
        m = re.search(r"\[download\]\s+([\d.]+)%", line)
        if m:
            ctx.update(progress=round(0.1 * float(m.group(1)) / 100, 3), message=f"Downloading {m.group(1)}%")
        elif Path(line).is_file():
            final = line
    if proc.wait() != 0 or not final:
        ctx.check_cancelled()
        raise JobError("Download failed:\n" + "\n".join(tail))
    return Path(final).name


def _stream_info(path: Path) -> dict[str, Any]:
    info = media.probe(path)
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not (s.get("disposition") or {}).get("attached_pic")), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    return {"video": video, "audio": audio, "format": (info.get("format") or {}).get("format_name", ""),
            "duration": float((info.get("format") or {}).get("duration") or 0.0)}


def _playable(d: Path, original: Path, info: dict[str, Any], ctx: JobContext) -> str:
    """A browser-playable copy: the original when its codecs already are, else an h264/aac (or aac) transcode."""
    ff = media.ffmpeg()
    acodec = (info["audio"] or {}).get("codec_name", "")
    if info["video"]:
        if (original.suffix.lower() in (".mp4", ".m4v") and info["video"].get("codec_name") == "h264"
                and acodec in ("aac", "mp3")):
            return original.name
        ctx.update(message="Making a browser-playable copy…")
        media.run([ff, "-y", "-i", str(original), "-map", "0:v:0", "-map", "0:a:0", "-c:v", "libx264", "-preset",
                   "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags",
                   "+faststart", str(d / "media.mp4")], ctx, what="transcode")
        return "media.mp4"
    if original.suffix.lower() in (".wav", ".mp3", ".m4a", ".ogg", ".flac", ".opus") and acodec:
        return original.name
    media.run([ff, "-y", "-i", str(original), "-vn", "-c:a", "aac", "-b:a", "192k", str(d / "media.m4a")], ctx,
              what="transcode")
    return "media.m4a"


def _scene_cuts(ctx: JobContext, video: Path) -> list[float]:
    err = media.run([media.ffmpeg(), "-hide_banner", "-i", str(video), "-filter:v", "select='gt(scene,0.3)',showinfo",
                     "-f", "null", "-"], ctx, what="scene detection")
    return [round(float(m), 3) for m in re.findall(r"pts_time:([\d.]+)", err)]


def _prepare(ctx: JobContext, pid: str) -> None:
    p = store.get(pid)
    d = store.project_dir(pid)
    ff = media.ffmpeg()
    src = p["source"]
    if src["kind"] == "url" and not src.get("original"):
        ctx.update(progress=0.0, message="Downloading…")
        src["original"] = _yt_dlp(ctx, src["url"], d)
    original = d / src["original"]
    ctx.update(progress=0.1, message="Reading media…")
    info = _stream_info(original)
    if not info["audio"]:
        raise JobError("This file has no audio track to dub.")
    src["input_type"] = "video" if info["video"] else "audio"
    src["duration"] = round(info["duration"], 3)
    src["media"] = _playable(d, original, info, ctx)
    ctx.update(progress=0.12, message="Extracting audio…")
    media.run([ff, "-y", "-i", str(original), "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
               str(d / "audio16k.wav")], ctx, what="audio extract")
    media.run([ff, "-y", "-i", str(original), "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
               str(d / "audio_hq.wav")], ctx, what="audio extract")
    scene_cuts: list[float] = []
    if info["video"]:
        at = max(0.5, min(1.5, src["duration"] * 0.1))
        media.run([ff, "-y", "-ss", f"{at:.2f}", "-i", str(original), "-vframes", "1", "-vf", "scale=320:-2", "-q:v",
                   "4", str(d / "thumb.jpg")], ctx, what="thumbnail")
        src["thumb"] = "thumb.jpg"
        ctx.update(message="Detecting scene cuts…")
        scene_cuts = _scene_cuts(ctx, original)
    store.update(pid, lambda proj: proj.update(source=src))

    worker.acquire_gpu(ctx)
    try:
        worker.free_vram(4)
        try:
            res = worker.call(ctx, "/separate", {"input": str(d / "audio_hq.wav"), "out_dir": str(d / "stems"),
                                                 "stems": "two", "model": "htdemucs"},
                              "Separating voices from the background", (0.15, 0.4))
            separation = {"vocals": "stems/vocals.wav", "background": "stems/no_vocals.wav"}
            assert Path(res["stems"]["vocals"]).is_file()
        except JobError as exc:
            ctx.check_cancelled()
            ctx.log(f"Separation failed, continuing with the mixed audio: {exc}", "warn")
            separation = None
        store.update(pid, lambda proj: proj.update(separation=separation))
        _transcribe_stage(ctx, pid, scene_cuts, (0.4, 1.0))
    finally:
        worker.release_stage_models()
        worker.gpu.release()


def retranscribe(pid: str) -> Job:
    p = store.get(pid)
    if not (store.project_dir(pid) / "audio16k.wav").is_file():
        raise DubError("The source audio has not been prepared yet", 409)
    return _submit(pid, f"Dub · transcribe {p['source']['filename'][:40]}", lambda ctx: _retranscribe(ctx, pid))


def _retranscribe(ctx: JobContext, pid: str) -> None:
    worker.acquire_gpu(ctx)
    try:
        _transcribe_stage(ctx, pid, [], (0.0, 1.0))
    finally:
        worker.release_stage_models()
        worker.gpu.release()


# ------------------------------------------------------------------ transcribe / diarize / refs

_DIARIZATION_WARNINGS = {
    "no_token": "Speakers were estimated from pauses (no Hugging Face token). Add a token in Settings and accept "
                "the terms of pyannote/speaker-diarization-3.1 and pyannote/segmentation-3.0 for real diarization.",
    "license": "Speakers were estimated from pauses: your Hugging Face account has not accepted the terms of "
               "pyannote/speaker-diarization-3.1 and pyannote/segmentation-3.0 (accept them on huggingface.co).",
    "load_failed": "Speakers were estimated from pauses: pyannote could not be loaded.",
}


def _label(raw: str) -> str:
    m = re.search(r"(\d+)$", raw)
    return f"Speaker {int(m.group(1)) + 1}" if m and raw.upper().startswith("SPEAKER_") else raw


def _transcribe_stage(ctx: JobContext, pid: str, scene_cuts: list[float], span: tuple[float, float]) -> None:
    p = store.get(pid)
    lo, hi = span

    def at(frac: float) -> float:
        return lo + (hi - lo) * frac

    separated = bool(p.get("separation"))
    audio = waveform.speech_audio(p)
    asr = _asr(p)
    worker.free_vram(5)
    # The gap re-pass needs separated vocals: on the full mix, music makes every empty stretch "loud"
    res = worker.call(ctx, "/transcribe", {"path": str(audio), "model_path": asr.path,
                                           "language": whisper_lang(p.get("source_lang")), "word_timestamps": True,
                                           **({"gap_pass": {"min_gap": 1.0, "min_dbfs": -30.0}} if separated else {})},
                      "Transcribing", (at(0.0), at(0.55)))
    duration = float(p["source"].get("duration") or res.get("duration") or 0.0)
    source_lang = p.get("source_lang") or voice_lang(res.get("language")) or "en"
    segs = segmentation.segment_transcript(res, duration, scene_cuts or None)
    for i, s in enumerate(segs):
        s["id"] = f"s{i:05x}"
    if not segs:
        raise JobError("No speech was recognised in this audio.")

    ctx.update(progress=at(0.6), message="Aligning segment starts to speech onsets…")
    analysis = worker.call(ctx, "/analyze", {"path": str(audio), "separated": separated,
                                             "segments": [{"id": s["id"], "start": s["start"], "end": s["end"]}
                                                          for s in segs]}, "Analysing speech onsets")
    for s in segs:
        if s["id"] in analysis["starts"]:
            s["start"] = analysis["starts"][s["id"]]
    waveform.write(p, analysis["onsets"], analysis["duration"] or duration)

    words = [segmentation.asr_word(w, float(w["start"]), float(w["end"]))
             for seg in res["segments"] for w in seg.get("words", [])]
    num = p.get("num_speakers")
    warning = None
    if num == 1:
        for s in segs:
            s["speaker"] = "Speaker 1"
        source = "single"
    else:
        diar = worker.call(ctx, "/diarize", {"path": str(audio), "num_speakers": num,
                                             "phrases": [{"start": x["start"], "end": x["end"], "text": x["text"]}
                                                         for x in res["segments"]]},
                           "Identifying speakers", (at(0.62), at(0.8)))
        if diar["available"]:
            turns = diar.get("phrase_turns") or diar["turns"]
            source = "phrase_embeddings" if diar.get("phrase_turns") else "pyannote"
            normalized = [{**t, "speaker": _label(t["speaker"])} for t in turns]
            segs = segmentation.assign_speakers_from_turns(segs, normalized)
            segs = segmentation.resplit_segments_by_turns(segs, words, normalized)
        else:
            segs = segmentation.assign_speakers_heuristic(segs, num)
            source = "heuristic"
            warning = _DIARIZATION_WARNINGS.get(diar.get("reason", ""), _DIARIZATION_WARNINGS["load_failed"])
            ctx.log(warning, "warn")

    # Number speakers by first appearance (diarizer labels are arbitrary).
    renumber = {old: f"Speaker {i + 1}" for i, old in enumerate(dict.fromkeys(s["speaker"] for s in segs))}
    for s in segs:
        s["speaker"] = renumber[s["speaker"]]
    speakers_order = list(renumber.values())
    refs = _cut_refs(ctx, pid, segs, source)
    previous_voice = {spk["id"]: spk.get("voice", "auto") for spk in p.get("speakers") or []}

    def apply(proj: dict[str, Any]) -> None:
        proj["segments"] = [{"id": s["id"], "start": round(s["start"], 3), "end": round(s["end"], 3),
                             "speaker": s["speaker"], "text": s["text"], "words": s.get("words", []),
                             "translations": {}} for s in segs]
        proj["source_lang"] = source_lang
        proj["diarization"] = {"source": source, "warning": warning} if warning else {"source": source}
        proj["speakers"] = [{"id": spk, "voice": previous_voice.get(spk, "auto"), "ref": refs["speakers"].get(spk)}
                            for spk in speakers_order]
        proj["seg_refs"] = refs["segments"]
        proj["refs_key"] = _refs_key(proj["segments"])
        proj["tracks"] = {}
        proj["natural_durs"] = {}
        proj["translation_context"] = {}
        proj["prepared"] = True

    store.update(pid, apply)
    ctx.update(progress=hi, message=f"{len(segs)} segments, {len(speakers_order)} speaker(s)")


# Bumped when clone references are cut differently, so existing projects re-cut theirs on the next render
# (2: natural-rate lines only, trimmed to their words, own transcripts).
REFS_VERSION = 2


def _refs_key(segments: list[dict]) -> str:
    return incremental.fingerprint({"layout": [[s["id"], s["start"], s["end"], s["speaker"]] for s in segments],
                                    "refs_version": REFS_VERSION}, lang="", voice_match="per_line")


def _cut_refs(ctx: JobContext, pid: str, segs: list[dict], labels_source: str) -> dict[str, dict]:
    """Per-speaker pooled clone references + per-segment clips from the separated vocals. The worker trims each
    clip to the words' speech, so the lines' own (possibly user-corrected) transcript is its ``ref_text``; a
    mismatched pair makes the TTS speak the reference text or misjudge the speaking rate."""
    p = store.get(pid)
    d = store.project_dir(pid)
    if not p.get("separation"):
        return {"speakers": {}, "segments": {}}
    shutil.rmtree(d / "refs", ignore_errors=True)
    cut = worker.call(ctx, "/cut_refs", {"vocals": str(d / p["separation"]["vocals"]), "out_dir": str(d / "refs"),
                                         "labels_source": labels_source,
                                         "segments": [{"id": s["id"], "start": s["start"], "end": s["end"],
                                                       "speaker": s["speaker"], "text": s["text"],
                                                       "words": s.get("words") or []} for s in segs]},
                      "Cutting voice references")

    def rel(path: str) -> str:
        return Path(path).relative_to(d).as_posix()

    speakers = {spk: {"path": rel(v["path"]), "text": v["text"], "duration": v["duration"], "kind": "speaker"}
                for spk, v in cut["speakers"].items()}
    segments = {sid: {"path": rel(v["path"]), "text": v["text"], "duration": v["duration"]}
                for sid, v in cut["segments"].items()}
    # Speakers without a pooled clone (heuristic labels) still show their longest line clip in the cast.
    for s in segs:
        clip = segments.get(s["id"])
        current = speakers.get(s["speaker"])
        if clip and (current is None or (current["kind"] == "segment" and clip["duration"] > current["duration"])):
            speakers[s["speaker"]] = {**clip, "kind": "segment"}
    return {"speakers": speakers, "segments": segments}


# ------------------------------------------------------------------ voices + fingerprints


def _binding(p: dict[str, Any], s: dict[str, Any]) -> str:
    if s.get("voice") is not None:
        return s["voice"]
    spk = next((x for x in p["speakers"] if x["id"] == s["speaker"]), None)
    return spk.get("voice", "auto") if spk else "auto"


def _usable_ref(ref: dict | None) -> bool:
    """A reference whose transcript fits its audio (see MIN_REF_CHARS_PER_S) — older projects may hold ones cut
    from chants or singing, with only a word or two for many seconds of sound."""
    return bool(ref) and ref["duration"] > 0 and len((ref.get("text") or "").strip()) / ref["duration"] >= MIN_REF_CHARS_PER_S


def _auto_ref(p: dict[str, Any], s: dict[str, Any], voice_match: str) -> dict | None:
    """Clone source for an ``auto`` binding: a sample the user picked for the speaker, for every line; else per
    line = the line's own clip (≤15 s), else the speaker's pooled clone; consistent = one reference per speaker
    (pooled clone, else its longest ≥3 s clip). Automatic references whose transcript doesn't fit their audio are
    skipped."""
    seg_refs = {sid: r for sid, r in (p.get("seg_refs") or {}).items() if _usable_ref(r)}
    spk = next((x for x in p["speakers"] if x["id"] == s["speaker"]), None)
    ref = store.speaker_ref(p, spk) if spk else None
    if ref and ref.get("pinned"):
        return ref
    pooled = ref if ref and ref.get("kind") == "speaker" and _usable_ref(ref) else None
    if voice_match == "per_line":
        own = seg_refs.get(s["id"])
        if own and own["duration"] <= MAX_SEG_REF_S:
            return own
        if pooled:
            return pooled
    if pooled and pooled["duration"] <= MAX_SEG_REF_S:
        return pooled
    mine = [(sid, r) for sid, r in seg_refs.items() if r["duration"] <= MAX_SEG_REF_S and
            any(x["id"] == sid and x["speaker"] == s["speaker"] for x in p["segments"])]
    usable = [c for c in mine if c[1]["duration"] >= CONSISTENT_MIN_REF_S] or mine
    usable.sort(key=lambda c: (-c[1]["duration"], c[0]))
    return usable[0][1] if usable else None


def line_text(p: dict[str, Any], s: dict[str, Any], lang: str) -> str | None:
    line = (s.get("translations") or {}).get(lang)
    if line:
        return line.get("text") or ""
    if lang == p.get("source_lang"):
        return s["text"]
    return None


def segment_fingerprint(p: dict[str, Any], s: dict[str, Any], lang: str) -> str:
    st = p["settings"]
    binding = _binding(p, s)
    ref_path = None
    if binding == "auto":
        chosen = _auto_ref(p, s, st["voice_match"])
        ref_path = chosen["path"] if chosen else None
    strict = st["timing"] == "strict_slot"
    return incremental.fingerprint({
        "text": line_text(p, s, lang) or "", "voice": binding, "ref": ref_path, "speed": s.get("speed"),
        "direction": s.get("direction"), "model": st["tts"].get("model_id"), "num_step": st["tts"]["num_step"],
        "guidance": st["tts"]["guidance"], "global_speed": st["tts"]["speed"], "instruct": st["tts"]["instruct"],
        "slot": round(s["end"] - s["start"], 3) if strict else None,
    }, lang=lang, voice_match=st["voice_match"])


# ------------------------------------------------------------------ translate


def run_translate(pid: str, req: DubRunRequest) -> Job:
    p = store.get(pid)
    if not p.get("prepared"):
        raise DubError("Transcribe the source first", 409)
    langs = req.langs or p["settings"]["targets"]
    if not langs:
        raise DubError("Choose at least one target language")
    return _submit(pid, f"Dub · translate → {', '.join(langs)}", lambda ctx: _translate(ctx, pid, req, langs))


def _nllb(ctx: JobContext, repo: str) -> Callable[[list[str], str, str], tuple[list[str], dict[int, str]]]:
    def mt(texts: list[str], src: str, tgt: str) -> tuple[list[str], dict[int, str]]:
        worker.acquire_gpu(ctx)
        try:
            worker.free_vram(3)
            res = worker.call(ctx, "/translate_mt", {"repo": repo, "source": src, "target": tgt, "texts": texts},
                              "Translating with NLLB")
        finally:
            worker.release_stage_models()
            worker.gpu.release()
        return res["texts"], {int(k): v for k, v in res["errors"].items()}
    return mt


def _translate(ctx: JobContext, pid: str, req: DubRunRequest, langs: list[str]) -> None:
    p = store.get(pid)
    st = DubSettings.model_validate(p["settings"])
    t = st.translation
    src = p.get("source_lang") or tr.L.guess_from_text([s["text"] for s in p["segments"]]) or "en"
    glossary = [g.model_dump() for g in store.glossary(pid)]
    total = len(langs)
    notes: list[str] = []
    for li, lang in enumerate(langs):
        ctx.check_cancelled()
        wanted = set(req.segment_ids or [])
        segs = [tr.SegIn(id=s["id"], text=s["text"], start=s["start"], end=s["end"], direction=s.get("direction"))
                for s in p["segments"]
                if (not wanted or s["id"] in wanted)
                and (not req.only_failed or ((s.get("translations") or {}).get(lang) or {}).get("error"))]
        if not segs:
            continue
        durs = (p.get("natural_durs") or {}).get(lang) or {}
        cps = tr.calibrate_cps((v["chars"], v["dur"]) for v in durs.values())
        opts = tr.Options(engine=t.engine, model=t.model, nllb_repo=t.nllb_repo, quality=t.quality,
                          auto_glossary=t.auto_glossary, reflect=t.reflect, condense=t.condense,
                          dialect=t.dialects.get(lang), instructions=t.instructions)
        cache = dict(p.get("translation_context") or {})

        def progress(msg: str, frac: float, li: int = li) -> None:
            ctx.update(progress=round((li + frac) / total, 3), message=f"{lang_name(lang)}: {msg}")

        try:
            rows, warns = tr.translate(segs, src=src, tgt=lang, opts=opts, glossary=glossary, context_cache=cache,
                                       cps=cps, total_s=float(p["source"].get("duration") or 0.0),
                                       mt=_nllb(ctx, t.nllb_repo), progress=progress)
        except LLMError as exc:
            raise JobError(str(exc)) from exc
        notes += warns
        failed = sum(1 for r in rows if r.get("error"))
        if failed:
            notes.append(f"{lang_name(lang)}: {failed} line(s) failed and kept the source text")

        def apply(proj: dict[str, Any], rows: list[dict] = rows, lang: str = lang) -> None:
            by_id = {r["id"]: r for r in rows}
            for s in proj["segments"]:
                row = by_id.get(s["id"])
                if row is None:
                    continue
                old = (s.get("translations") or {}).get(lang) or {}
                line = {k: v for k, v in row.items() if k != "id" and v is not None}
                for keep in ("fingerprint", "fit"):
                    if keep in old:
                        line[keep] = old[keep]
                if old.get("qc") and old.get("text") == line["text"]:
                    line["qc"] = old["qc"]
                s.setdefault("translations", {})[lang] = line
            proj["translation_context"] = cache
            if lang not in proj["settings"]["targets"]:
                proj["settings"]["targets"].append(lang)

        with store.lock():
            p = store.update(pid, apply)
    ctx.update(progress=1.0, message="; ".join(notes) if notes else "Translation done")


# ------------------------------------------------------------------ generate


def run_generate(pid: str, req: DubRunRequest) -> Job:
    p = store.get(pid)
    if not p.get("prepared"):
        raise DubError("Transcribe the source first", 409)
    langs = req.langs or p["settings"]["targets"]
    if not langs:
        raise DubError("Choose at least one target language")
    for lang in langs:
        missing = [s["id"] for s in p["segments"] if line_text(p, s, lang) is None]
        if missing:
            raise DubError(f"{len(missing)} line(s) have no {lang_name(lang)} text yet — translate first", 409)
    return _submit(pid, f"Dub · generate {', '.join(langs)}", lambda ctx: _generate(ctx, pid, req, langs))


def _wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def _refresh_refs(ctx: JobContext, pid: str) -> None:
    """Segment timing/speaker edits invalidate per-line clone clips; cut fresh ones before rendering."""
    p = store.get(pid)
    if not p.get("separation") or p.get("refs_key") == _refs_key(p["segments"]):
        return
    ctx.update(message="Segments changed — cutting fresh voice references…")
    source = (p.get("diarization") or {}).get("source", "heuristic")
    refs = _cut_refs(ctx, pid, p["segments"], source)
    worker.release_stage_models()

    def apply(proj: dict[str, Any]) -> None:
        proj["seg_refs"] = refs["segments"]
        for spk in proj["speakers"]:
            spk["ref"] = refs["speakers"].get(spk["id"])
        known = {spk["id"] for spk in proj["speakers"]}
        for s in proj["segments"]:
            if s["speaker"] not in known:
                proj["speakers"].append({"id": s["speaker"], "voice": "auto", "ref": refs["speakers"].get(s["speaker"])})
                known.add(s["speaker"])
        proj["refs_key"] = _refs_key(proj["segments"])

    store.update(pid, apply)


def _generate(ctx: JobContext, pid: str, req: DubRunRequest, langs: list[str]) -> None:
    worker.acquire_gpu(ctx)
    try:
        _refresh_refs(ctx, pid)
        p = store.get(pid)
        st = DubSettings.model_validate(p["settings"])
        m = tts.model(st.tts.model_id)
        for lang in langs:
            tts.check_language(m, lang)
        tts.load(ctx, m)
        notes: list[str] = []
        for li, lang in enumerate(langs):
            notes += _generate_lang(ctx, pid, lang, m, st, req, (li / len(langs), (li + 1) / len(langs)))
        ctx.update(progress=1.0, message="; ".join(notes) if notes else "Dub ready")
    finally:
        worker.gpu.release()


def _line(p: dict[str, Any], s: dict[str, Any], lang: str, m: InstalledModel, st: DubSettings, out: Path,
          voice_cache: dict[str, tts.Voice]) -> tts.Line:
    """The synthesis request for one segment: its text, resolved voice (auto clone ref or profile) and pacing.
    Lip-sync (strict slot) asks OmniVoice for the exact slot length, nudged by the line's direction."""
    binding = _binding(p, s)
    d = store.project_dir(p["id"])
    if binding == "auto":
        chosen = _auto_ref(p, s, st.voice_match)
        voice = tts.Voice(ref_audio=str(d / chosen["path"]), ref_text=chosen["text"]) if chosen else tts.Voice()
    else:
        if binding not in voice_cache:
            voice_cache[binding] = tts.profile_voice(m, binding, lang)
        voice = voice_cache[binding]
    strict = st.timing == "strict_slot"
    slot = max(0.3, s["end"] - s["start"])
    speed = (s.get("speed") or st.tts.speed) * (director.rate_bias(s.get("direction")) if strict else 1.0)
    return tts.Line(text=line_text(p, s, lang) or "", out_path=out, lang=lang, voice=voice, speed=speed,
                    duration=slot if strict and m.runtime == "omnivoice" else None, num_step=st.tts.num_step,
                    guidance=st.tts.guidance, instruct=st.tts.instruct or None)


def _generate_lang(ctx: JobContext, pid: str, lang: str, m: InstalledModel, st: DubSettings, req: DubRunRequest,
                   span: tuple[float, float]) -> list[str]:
    p = store.get(pid)
    d = store.project_dir(pid)
    notes: list[str] = []
    segs = sorted(p["segments"], key=lambda s: s["start"])
    track = p["tracks"].get(lang) or {}
    prints = dict(track.get("fingerprints") or {})
    seg_dir = d / "segs" / lang
    voice_cache: dict[str, tts.Voice] = {}
    naturals: dict[str, dict] = dict((p.get("natural_durs") or {}).get(lang) or {})
    todo = []
    for s in segs:
        fp = segment_fingerprint(p, s, lang)
        wav_path = seg_dir / f"{s['id']}.wav"
        if req.only_stale and prints.get(s["id"]) == fp and wav_path.is_file():
            continue
        todo.append((s, fp))
    lo, hi = span
    render_hi = lo + (hi - lo) * 0.85
    lines: list[tuple[dict, tts.Line]] = []
    for s, fp in todo:
        prints[s["id"]] = fp
        wav_path = seg_dir / f"{s['id']}.wav"
        if not (line_text(p, s, lang) or "").strip():
            wav_path.unlink(missing_ok=True)
            continue
        lines.append((s, _line(p, s, lang, m, st, wav_path, voice_cache)))

    def progress(done: int) -> None:
        ctx.update(progress=round(lo + (render_hi - lo) * done / max(1, len(lines)), 3),
                   message=f"{lang_name(lang)}: {done}/{len(lines)} lines rendered")

    progress(0)
    durations = tts.synthesize_many(m, [x for _, x in lines], progress, ctx.check_cancelled)
    for (s, x), natural in zip(lines, durations):
        if x.duration is None:  # only natural-rate renders calibrate the speaking-rate estimate
            naturals[s["id"]] = {"chars": len(x.text), "dur": round(natural, 3)}

    if st.translation.quality == "agent" and st.translation.model and st.timing != "strict_slot":
        notes += _agent_fit(ctx, pid, lang, m, st, segs, voice_cache, prints, naturals)
        p = store.get(pid)
        segs = sorted(p["segments"], key=lambda s: s["start"])

    ctx.update(progress=round(render_hi, 3), message=f"{lang_name(lang)}: assembling the track…")
    result = _assemble(ctx, p, lang, st, segs)

    def apply(proj: dict[str, Any]) -> None:
        proj.setdefault("natural_durs", {})[lang] = naturals
        by_id = {s["id"]: s for s in proj["segments"]}
        for sid, fit in result["fits"].items():
            seg = by_id.get(sid)
            if seg is None:
                continue
            line = seg.setdefault("translations", {}).setdefault(lang, {"text": line_text(proj, seg, lang) or ""})
            line["fit"] = fit
            line["fingerprint"] = prints.get(sid)
            line.pop("qc", None)
        proj["tracks"][lang] = {
            "file": result["file"], "duration": result["duration"], "timing": st.timing,
            "created_at": db.now_iso(), "cues": result["cues"], "plan": result.get("plan"),
            "orig_duration": float(proj["source"].get("duration") or 0.0), "fingerprints": prints,
        }

    store.update(pid, apply)
    _prune_tracks(d, lang, result["file"])
    flagged = sum(1 for fit in result["fits"].values() if fit["status"] in ("overflow_trimmed", "silent"))
    if flagged:
        notes.append(f"{lang_name(lang)}: {flagged} line{'s' if flagged != 1 else ''} didn't fit and "
                     f"{'were' if flagged != 1 else 'was'} cut — marked in the editor")
    return notes


def _agent_fit(ctx: JobContext, pid: str, lang: str, m: InstalledModel, st: DubSettings, segs: list[dict],
               voice_cache: dict[str, tts.Voice], prints: dict[str, str], naturals: dict[str, dict]) -> list[str]:
    """Agent quality: measure real renders, ask the LLM for evidence-based rewrites of lines outside
    [0.9, 1.04]× their slot, re-render only those — at most two passes."""
    assert st.translation.model
    chat = Chat(st.translation.model)
    d = store.project_dir(pid)
    changed_total = 0
    for pass_no in range(2):
        p = store.get(pid)
        misses = []
        for i, s in enumerate(segs):
            nat = (naturals.get(s["id"]) or {}).get("dur")
            slot = s["end"] - s["start"]
            if nat and slot > 0 and not tr.MEASURED_TOL_LOW <= nat / slot <= tr.MEASURED_TOL_HIGH and nat / slot >= 0.45:
                misses.append((i, s, nat, slot))
        if not misses:
            break
        ctx.update(message=f"{lang_name(lang)}: agent fit pass {pass_no + 1} — adapting {len(misses)} line(s)")
        changed: list[tuple[dict, str]] = []
        for i, s, nat, slot in misses:
            ctx.check_cancelled()
            res = tr.adjust_for_measured(chat, line_text(p, s, lang) or "", slot=slot, measured=nat, tgt=lang,
                                         source=s["text"], before=segs[i - 1]["text"] if i else None,
                                         after=segs[i + 1]["text"] if i + 1 < len(segs) else None,
                                         instructions=st.translation.instructions)
            if res.get("changed"):
                changed.append((s, res["text"]))
        if not changed:
            break

        def apply(proj: dict[str, Any], changed: list[tuple[dict, str]] = changed) -> None:
            texts = {s["id"]: t for s, t in changed}
            for seg in proj["segments"]:
                if seg["id"] in texts:
                    line = seg.setdefault("translations", {}).setdefault(lang, {})
                    line["text"] = texts[seg["id"]]
                    line.pop("plan", None)

        p = store.update(pid, apply)
        redo = [next(x for x in p["segments"] if x["id"] == s["id"]) for s, _text in changed]
        requests = [_line(p, seg, lang, m, st, d / "segs" / lang / f"{seg['id']}.wav", voice_cache) for seg in redo]
        durations = tts.synthesize_many(m, requests, lambda n: None, ctx.check_cancelled)
        for seg, x, nat in zip(redo, requests, durations):
            if x.duration is None:
                naturals[seg["id"]] = {"chars": len(x.text), "dur": round(nat, 3)}
            prints[seg["id"]] = segment_fingerprint(p, seg, lang)
        changed_total += len(changed)
        segs = sorted(p["segments"], key=lambda x: x["start"])
    return [f"{lang_name(lang)}: agent adapted {changed_total} line(s)"] if changed_total else []


def _prune_tracks(d: Path, lang: str, keep: str) -> None:
    """Delete earlier renders of a language's track. One still open (a player streaming it — Windows can't
    delete or replace an open file, which is why every render gets a new name) goes on the next render."""
    for f in [*(d / "tracks").glob(f"dubbed_{lang}.wav"), *(d / "tracks").glob(f"dubbed_{lang}.*.wav")]:
        if f.name != Path(keep).name:
            try:
                f.unlink()
            except OSError:
                pass


def _assemble(ctx: JobContext, p: dict[str, Any], lang: str, st: DubSettings, segs: list[dict]) -> dict[str, Any]:
    d = store.project_dir(p["id"])
    rel = f"tracks/dubbed_{lang}.{store.new_id()}.wav"
    total = float(p["source"].get("duration") or 0.0) or max((s["end"] for s in segs), default=0.0)
    spoken = [s for s in segs if (d / "segs" / lang / f"{s['id']}.wav").is_file()]
    if not spoken:
        raise JobError("Nothing to assemble — every line is empty")
    items: list[dict[str, Any]] = [{"id": s["id"], "path": str(d / "segs" / lang / f"{s['id']}.wav"), "start": s["start"],
                                    "end": s["end"], "gain": s.get("gain") if s.get("gain") is not None else 1.0}
                                   for s in spoken]
    plan: list[dict] | None = None
    if st.timing == "smart_fit":
        params = fit_planner.FitParams(max_audio_only_rate=st.fit.max_audio_only_rate,
                                       audio_rate_cap=st.fit.audio_rate_cap, video_slow_cap=st.fit.video_slow_cap,
                                       allow_video_retime=st.fit.allow_video_retime and p["source"]["input_type"] == "video")
        fp = fit_planner.plan_fit([{"id": it["id"], "start": it["start"], "end": it["end"]} for it in items],
                                  [_wav_seconds(Path(it["path"])) for it in items], total, params)
        for it, sf in zip(items, fp.segments):
            fit: dict[str, Any] = {"status": sf.status}
            if abs(sf.audio_rate - 1.0) > 1e-6:
                fit["audio_rate"] = round(sf.audio_rate, 3)
            if sf.video_ratio > 1.0 + 1e-6:
                fit["video_ratio"] = round(sf.video_ratio, 3)
            if sf.overflow_s > 0:
                fit["overflow_s"] = round(sf.overflow_s, 3)
            it.update(place_at=sf.new_start, audio_rate=sf.audio_rate, new_start=sf.new_start, new_end=sf.new_end,
                      fit=fit)
        total = fp.total_duration
        plan = fp.video_plan if fp.needs_video_retime else None
    elif st.timing == "stretch_video":
        cursor = 0.0
        plan = []
        for i, it in enumerate(items):
            natural = _wav_seconds(Path(it["path"]))
            cursor = it["start"] if i == 0 else cursor + max(0.0, it["start"] - items[i - 1]["end"])
            orig = max(1e-3, it["end"] - it["start"])
            it.update(place_at=cursor, audio_rate=1.0, new_start=cursor, new_end=cursor + natural,
                      fit={"status": "video_stretched", "video_ratio": round(natural / orig, 3)})
            plan.append({"orig_start": it["start"], "orig_end": it["end"], "new_start": round(cursor, 4),
                         "new_end": round(cursor + natural, 4), "stretch_ratio": round(natural / orig, 4)})
            cursor += natural
        total = max(cursor + max(0.0, total - items[-1]["end"]), total)
    res = worker.call(ctx, "/assemble", {"ffmpeg": media.ffmpeg(), "strategy": st.timing, "total_s": total,
                                         "out_path": str(d / rel), "min_rate": 0.85,
                                         "items": items}, f"{lang_name(lang)}: assembling")
    return {"fits": {it["id"]: fit for it, fit in zip(items, res["fit"])},
            "cues": [{"id": it["id"], **cue} for it, cue in zip(items, res["cues"])],
            "duration": res["duration"], "plan": plan, "file": rel}


# ------------------------------------------------------------------ preview + QC


def preview(pid: str, segment_id: str, lang: str) -> tuple[Path, float]:
    """Blocking single-line render with the current voice/settings (not written into the track)."""
    p = store.get(pid)
    s = next((x for x in p["segments"] if x["id"] == segment_id), None)
    if s is None:
        raise DubError("Segment not found", 404)
    text = line_text(p, s, lang)
    if not text:
        raise DubError(f"This line has no {lang_name(lang)} text yet", 409)
    if not worker.gpu.acquire(timeout=1):
        raise DubError("Another audio job is using the GPU — try again when it finishes", 409)
    try:
        st = DubSettings.model_validate(p["settings"])
        m = tts.model(st.tts.model_id)
        tts.check_language(m, lang)
        tts.load(None, m)
        out = store.project_dir(pid) / "preview" / f"{segment_id}_{lang}.wav"
        return out, tts.synthesize(m, _line(p, s, lang, m, st, out, {}))
    except JobError as exc:
        raise DubError(str(exc), 409) from exc
    finally:
        worker.gpu.release()


def run_qc(pid: str, lang: str) -> Job:
    p = store.get(pid)
    if lang not in p["tracks"]:
        raise DubError(f"Generate the {lang_name(lang)} track first", 409)
    return _submit(pid, f"Dub · verify {lang}", lambda ctx: _qc(ctx, pid, lang))


def _qc(ctx: JobContext, pid: str, lang: str) -> None:
    p = store.get(pid)
    d = store.project_dir(pid)
    track = p["tracks"][lang]
    worker.acquire_gpu(ctx)
    try:
        worker.free_vram(5)
        res = worker.call(ctx, "/transcribe", {"path": str(d / track["file"]), "model_path": _asr(p).path,
                                               "language": whisper_lang(lang), "word_timestamps": True},
                          f"Re-recognising the {lang_name(lang)} dub", (0.0, 0.9))
    finally:
        worker.release_stage_models()
        worker.gpu.release()
    by_id = {s["id"]: s for s in p["segments"]}
    lines = [{"id": c["id"], "start": c["start"], "end": c["end"], "text": line_text(p, by_id[c["id"]], lang) or ""}
             for c in track["cues"] if c["id"] in by_id]
    scores = qc.score(lines, res["segments"])
    flagged = sum(1 for v in scores.values() if v["flagged"])

    def apply(proj: dict[str, Any]) -> None:
        for s in proj["segments"]:
            if s["id"] in scores and lang in (s.get("translations") or {}):
                s["translations"][lang]["qc"] = scores[s["id"]]

    store.update(pid, apply)
    ctx.update(progress=1.0, message=f"{flagged} of {len(lines)} line(s) flagged for review")
    events.log("info", "dub", f"QC {pid}/{lang}: {flagged}/{len(lines)} flagged")
