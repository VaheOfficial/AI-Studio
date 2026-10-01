"""Dub exports as Jobs (ported from VoiceStudio ``api/routers/dub_export.py`` + ``services/dub_background.py``):
mp4 with one audio stream per language (optional original, per-segment video retime, burned line/dual/karaoke
subtitles), wav/mp3, SRT/VTT/ASS, stems zip and per-line clips zip. Finished files are listed on the project."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from .. import db, media
from ..jobs import JobContext, JobError
from ..schemas import Job
from ..schemas_dub import DubExportRequest
from . import karaoke_ass, retime, store, subtitles, worker
from . import languages as L
from .pipeline import DubError, _submit, lang_name, line_text

RATE = 48000


def run(pid: str, req: DubExportRequest) -> Job:
    p = store.get(pid)
    langs = [lang for lang in req.langs if lang]
    if req.format in ("mp4", "wav", "mp3", "stems", "clips"):
        missing = [lang for lang in langs if lang not in p["tracks"]]
        if missing:
            raise DubError(f"Generate the {', '.join(lang_name(x) for x in missing)} track first", 409)
        if not langs and not (req.format == "mp4" and req.include_original):
            raise DubError("Choose at least one dubbed track to export")
    if req.format == "mp4" and p["source"]["input_type"] != "video":
        raise DubError("This project is audio-only — export WAV or MP3 instead")
    if req.format in ("srt", "vtt", "ass") and not langs:
        raise DubError("Choose the subtitle language")
    parts = (["original"] if req.format == "mp4" and req.include_original else []) + langs
    label = f"{req.format.upper()} · {', '.join(parts) or 'original'}"
    return _submit(pid, f"Dub · export {label}", lambda ctx: _export(ctx, pid, req, langs, label))


def _safe(name: str) -> str:
    return re.sub(r"[^\w\- ]+", "", name).strip().replace(" ", "_") or "dub"


def _export(ctx: JobContext, pid: str, req: DubExportRequest, langs: list[str], label: str) -> None:
    p = store.get(pid)
    d = store.project_dir(pid)
    out_dir = d / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = db.now_iso().replace(":", "").replace("-", "").replace(".", "")[:15]
    base = f"{_safe(p['name'])}_{'-'.join(langs) or 'original'}_{stamp}"
    fmt = req.format
    if fmt in ("srt", "vtt", "ass"):
        out = out_dir / f"{base}.{fmt}"
        cues = _cues(p, langs[0])
        if fmt == "srt":
            out.write_text(subtitles.to_srt(cues, dual=req.dual), encoding="utf-8")
        elif fmt == "vtt":
            out.write_text(subtitles.to_vtt(cues, dual=req.dual), encoding="utf-8")
        else:
            out.write_text(karaoke_ass.build_ass(cues), encoding="utf-8")
    elif fmt in ("wav", "mp3"):
        out = out_dir / f"{base}.{fmt}"
        _audio(ctx, p, langs[0], out, req)
    elif fmt == "mp4":
        out = out_dir / f"{base}.mp4"
        _mp4(ctx, p, langs, out, req, out_dir)
    elif fmt == "stems":
        out = out_dir / f"{base}_stems.zip"
        bed = _bed(ctx, p, langs[0])
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(d / p["tracks"][langs[0]]["file"], f"vocals_dubbed_{langs[0]}.wav")
            zf.write(bed, "background_original.wav")
    else:
        out = out_dir / f"{base}_clips.zip"
        seg_dir = d / "segs" / langs[0]
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, s in enumerate(sorted(p["segments"], key=lambda x: x["start"])):
                wav = seg_dir / f"{s['id']}.wav"
                if wav.is_file():
                    zf.write(wav, f"{i + 1:03d}_{s['start']:.2f}-{s['end']:.2f}_{s['speaker'].replace(' ', '')}.wav")
    entry = {"id": store.new_id(), "format": fmt, "label": label, "url": store.url(pid, f"exports/{out.name}"),
             "filename": out.name, "size": out.stat().st_size, "created_at": db.now_iso()}
    store.update(pid, lambda proj: proj.setdefault("exports", []).insert(0, entry))
    ctx.update(progress=1.0, message=f"Exported {out.name}")


def _cues(p: dict[str, Any], lang: str) -> list[dict]:
    """Subtitle cues at the actual dub placement (track cues) — or source timings before generation."""
    by_id = {s["id"]: s for s in p["segments"]}
    track = p["tracks"].get(lang)
    if track:
        spans = [(c["id"], c["start"], c["end"]) for c in track["cues"] if c["id"] in by_id]
    else:
        spans = [(s["id"], s["start"], s["end"]) for s in sorted(p["segments"], key=lambda x: x["start"])]
    cues = []
    for sid, start, end in spans:
        s = by_id[sid]
        text = line_text(p, s, lang)
        if text:
            cues.append({"start": start, "end": end, "text": text, "original": s["text"]})
    return cues


def _bed(ctx: JobContext, p: dict[str, Any], lang: str) -> Path:
    """Original audio outside dialogue, separated background inside it — retimed like the video when the
    track stretched it. Cached per (inputs, intervals, plan)."""
    d = store.project_dir(p["id"])
    if not p.get("separation"):
        raise JobError("Keeping the background needs vocal separation, which is not available for this project. "
                       "Export with Background off.")
    intervals: list[list[float]] = []
    for a, b in sorted((s["start"], s["end"]) for s in p["segments"]):
        if intervals and a <= intervals[-1][1]:
            intervals[-1][1] = max(b, intervals[-1][1])
        else:
            intervals.append([a, b])
    track = p["tracks"][lang]
    plan = track.get("plan") or []
    src, sep = d / "audio_hq.wav", d / p["separation"]["background"]
    key = hashlib.sha256(json.dumps([1, [str(src.stat().st_mtime_ns), str(sep.stat().st_mtime_ns)], intervals, plan,
                                     track.get("orig_duration")], sort_keys=True).encode()).hexdigest()[:20]
    cache = d / "exports" / "cache"
    target = cache / f"bed_{key}.wav"
    if target.is_file():
        return target
    cache.mkdir(parents=True, exist_ok=True)
    ff = media.ffmpeg()
    with tempfile.TemporaryDirectory(dir=cache) as tmp:
        original, bed, spliced = (Path(tmp) / n for n in ("source.wav", "bed.wav", "spliced.wav"))
        ctx.update(message="Preparing the background bed…")
        for inp, out in ((src, original), (sep, bed)):
            media.run([ff, "-y", "-i", str(inp), "-vn", "-ar", str(RATE), "-ac", "2", "-c:a", "pcm_f32le", str(out)],
                      ctx, what="background decode")
        worker.call(ctx, "/splice_bed", {"original": str(original), "separated": str(bed), "output": str(spliced),
                                         "intervals": intervals}, "Splicing the background")
        if plan:
            retimed = Path(tmp) / "retimed.wav"
            retime.retime_audio(ctx, spliced, plan, float(track.get("orig_duration") or 0.0), retimed)
            spliced = retimed
        shutil.move(str(spliced), target)
    return target


def _audio(ctx: JobContext, p: dict[str, Any], lang: str, out: Path, req: DubExportRequest) -> None:
    d = store.project_dir(p["id"])
    ff = media.ffmpeg()
    cmd = [ff, "-y", "-i", str(d / p["tracks"][lang]["file"])]
    if req.preserve_bg:
        cmd += ["-i", str(_bed(ctx, p, lang)), "-filter_complex", media.bed_mix_filter("1:a", "0:a"),
                "-map", "[aout]"]
    cmd += ["-c:a", "pcm_s16le"] if out.suffix == ".wav" else ["-c:a", "libmp3lame", "-b:a", f"{req.bitrate}k"]
    ctx.update(message="Encoding audio…")
    media.run(cmd + [str(out)], ctx, what="audio export")


def _mp4(ctx: JobContext, p: dict[str, Any], langs: list[str], out: Path, req: DubExportRequest, out_dir: Path
         ) -> None:
    d = store.project_dir(p["id"])
    ff = media.ffmpeg()
    video = d / p["source"]["original"]
    default = req.default_lang if req.default_lang in langs or req.default_lang == "original" else (
        langs[0] if langs else "original")
    track = p["tracks"].get(default) if default != "original" else None
    plan = (track or {}).get("plan")
    stretch = bool(plan) and (track or {}).get("timing") == "stretch_video"
    burn = req.burn_subs and default != "original"
    decision = None
    work = out_dir / f"retimed_{out.stem}.mp4"
    try:
        if plan:
            ctx.update(message="Planning the video retime…")
            decision = retime.prepare(ctx, video, plan, float(track["orig_duration"]), float(track["duration"]), work)
        cmd = [ff, "-y", "-i", str(video)]
        idx = 1
        retimed_idx = None
        if decision and decision.mode == "file":
            cmd += ["-i", decision.file_path]
            retimed_idx, idx = idx, idx + 1
        inputs = []
        for lang in langs:
            bed_idx = None
            if req.preserve_bg:
                cmd += ["-i", str(_bed(ctx, p, lang))]
                bed_idx, idx = idx, idx + 1
            cmd += ["-i", str(d / p["tracks"][lang]["file"])]
            inputs.append({"lang": lang, "idx": idx, "bed": bed_idx})
            idx += 1
        filters: list[str] = []
        vmap, reencode = "0:v:0", False
        if decision and decision.mode == "filter":
            filters.append(decision.graph)
            vmap, reencode = decision.label, True
        elif decision:
            vmap = f"{retimed_idx}:v:0"
        sub_path = None
        if burn:
            cues = _cues(p, default)
            if req.karaoke and not req.dual:
                sub_path = out_dir / f"burn_{out.stem}.ass"
                sub_path.write_text(karaoke_ass.build_ass(cues), encoding="utf-8")
            else:
                sub_path = out_dir / f"burn_{out.stem}.srt"
                sub_path.write_text(subtitles.to_srt(cues, dual=req.dual), encoding="utf-8")
            src_label = vmap if vmap.startswith("[") else f"[{vmap.rsplit(':', 1)[0]}]"
            kind = "ass" if sub_path.suffix == ".ass" else "subtitles"
            filters.append(f"{src_label}{kind}='{media.filter_escape(sub_path)}'[vsub]")
            vmap, reencode = "[vsub]", True
        apad = decision.video_dur if decision and decision.video_dur - float(track["duration"]) > 0.05 else 0.0
        amaps = []
        for i, t in enumerate(inputs):
            tail = f",apad=whole_dur={apad:.4f}" if apad else ""
            if t["bed"] is not None:
                filters.append(media.bed_mix_filter(f"{t['bed']}:a", f"{t['idx']}:a", out=f"aout{i}", tail=tail,
                                                    uniq=str(i)))
                amaps.append(f"[aout{i}]")
            elif apad:
                filters.append(f"[{t['idx']}:a]apad=whole_dur={apad:.4f}[aout{i}]")
                amaps.append(f"[aout{i}]")
            else:
                amaps.append(f"{t['idx']}:a:0")
        cmd += ["-map", vmap]
        if req.include_original:
            cmd += ["-map", "0:a:0"]
        for a in amaps:
            cmd += ["-map", a]
        if filters:
            cmd += ["-filter_complex", ";".join(filters)]
        cmd += (retime.VIDEO_ENC_ARGS if reencode else ["-c:v", "copy"]) + ["-c:a", "aac", "-b:a", "192k"]
        streams = (["original"] if req.include_original else []) + langs
        for i, name in enumerate(streams):
            if name == "original":
                label, code = "Original", L.iso639_2(p.get("source_lang") or "und")
            else:
                label, code = lang_name(name), L.iso639_2(name)
            meta = [f"language={code}", f"title={label}", f"handler_name={label}"]
            for m in meta:
                cmd += [f"-metadata:s:a:{i}", m]
            cmd += [f"-disposition:a:{i}", "default" if name == default else "0"]
        if not decision and not stretch:
            cmd += ["-shortest"]
        cmd += ["-movflags", "+faststart", str(out)]
        ctx.update(message="Muxing the video…")
        media.run(cmd, ctx, what="mp4 export", timeout=7200)
    finally:
        work.unlink(missing_ok=True)
        for leftover in out_dir.glob(f"burn_{out.stem}.*"):
            leftover.unlink(missing_ok=True)
