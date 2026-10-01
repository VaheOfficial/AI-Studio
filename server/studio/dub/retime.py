"""Per-segment video retime for Smart Fit / Stretch video (ported from VoiceStudio ``services/video_retime.py``)
and the matching background-bed retime (``services/dub_background.py``).

Up to 48 chunks render as one ``split → trim → setpts → concat`` graph inlined into the mux; longer plans render
in batches of 40 to intermediate slices joined with the concat demuxer. VFR sources are normalised with ``fps=``
before trimming by timestamp."""

from __future__ import annotations

import math
import shutil
from dataclasses import dataclass
from pathlib import Path

from .. import media
from ..jobs import JobContext

SINGLE_PASS_MAX_CHUNKS = 48
BATCH_SIZE = 40
DRIFT_TOLERANCE_S = 0.05
VIDEO_ENC_ARGS = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p"]


@dataclass
class Decision:
    mode: str  # "filter" | "file"
    graph: str = ""
    label: str = ""
    file_path: str = ""
    video_dur: float = 0.0


def expand_chunks(plan: list[dict], orig_dur: float) -> list[tuple[float, float, float]]:
    """Plan entries → contiguous (start, end, ratio) chunks; gaps, pre-roll and tail at 1.0×."""
    chunks: list[tuple[float, float, float]] = []
    cursor = 0.0
    for entry in plan:
        a, b = float(entry["orig_start"]), float(entry["orig_end"])
        if a > cursor + 1e-3:
            chunks.append((cursor, a, 1.0))
        if b > a:
            chunks.append((a, b, float(entry["stretch_ratio"])))
        cursor = max(cursor, b)
    if orig_dur > cursor + 1e-3:
        chunks.append((cursor, orig_dur, 1.0))
    return [c for c in chunks if c[1] > c[0]]


def chunk_graph(chunks: list[tuple[float, float, float]], in_label: str, *, fps_norm: str | None = None,
                tail_pad_s: float = 0.0, out_fps: str | None = None) -> tuple[str, str]:
    src = in_label
    parts: list[str] = []
    if fps_norm:
        parts.append(f"{src}fps={fps_norm}[vcfr]")
        src = "[vcfr]"
    splits = [f"[vsplit{i}]" for i in range(len(chunks))]
    parts.append(f"{src}split={len(chunks)}{''.join(splits)}")
    labels = []
    for i, ((a, b, ratio), lbl) in enumerate(zip(chunks, splits)):
        labels.append(f"[vstr{i}]")
        parts.append(f"{lbl}trim=start={a:.4f}:end={b:.4f},setpts=PTS-STARTPTS,setpts={ratio:.6f}*PTS[vstr{i}]")
    terminal = "".join(labels) + f"concat=n={len(chunks)}:v=1:a=0"
    post = ([f"fps={out_fps}"] if out_fps else []) + (
        [f"tpad=stop_mode=clone:stop_duration={tail_pad_s:.4f}"] if tail_pad_s > 0 else [])
    if post:
        parts += [terminal + "[vcat]", "[vcat]" + ",".join(post) + "[vstretched]"]
    else:
        parts.append(terminal + "[vstretched]")
    return ";".join(parts), "[vstretched]"


def _rate(value: str | None) -> float | None:
    try:
        if not value:
            return None
        num, _, den = value.partition("/")
        v = float(num) / float(den) if den else float(num)
        return v if v > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def prepare(ctx: JobContext, video: Path, plan: list[dict], orig_dur: float, track_dur: float, work: Path
            ) -> Decision | None:
    """Decide (and for long plans, render) the retimed video. None when nothing is slowed."""
    chunks = expand_chunks(plan, orig_dur)
    if not chunks or not any(r > 1.0 + 1e-6 for _, _, r in chunks):
        return None
    rates = media.frame_rates(video)
    out_fps = fps_norm = None
    if rates:
        out_fps = rates[1] if _rate(rates[1]) else rates[0] if _rate(rates[0]) else None
        r, avg = _rate(rates[0]), _rate(rates[1])
        if r and avg and abs(r - avg) / avg > 1e-3:
            fps_norm = out_fps  # VFR: trim-by-timestamp lands on unpredictable frames otherwise
    expected = sum((b - a) * r for a, b, r in chunks)
    tail = track_dur - expected if track_dur - expected > DRIFT_TOLERANCE_S else 0.0
    if len(chunks) <= SINGLE_PASS_MAX_CHUNKS:
        graph, label = chunk_graph(chunks, "[0:v]", fps_norm=fps_norm, tail_pad_s=tail,
                                   out_fps=out_fps if tail > 0 else None)
        return Decision("filter", graph=graph, label=label, video_dur=expected + tail)
    ff = media.ffmpeg()
    slices_dir = work.with_suffix(".slices")
    slices_dir.mkdir(parents=True, exist_ok=True)
    try:
        slices = []
        batches = [chunks[i:i + BATCH_SIZE] for i in range(0, len(chunks), BATCH_SIZE)]
        for bi, batch in enumerate(batches):
            ctx.check_cancelled()
            ctx.update(message=f"Retiming video {bi + 1}/{len(batches)}")
            win_start, win_dur = batch[0][0], batch[-1][1] - batch[0][0]
            shifted = [(max(0.0, a - win_start), b - win_start, r) for a, b, r in batch]
            graph, label = chunk_graph(shifted, "[0:v]", fps_norm=fps_norm, out_fps=out_fps,
                                       tail_pad_s=tail if bi == len(batches) - 1 else 0.0)
            out = slices_dir / f"slice_{bi:04d}.mp4"
            seek = ["-ss", f"{win_start:.4f}"] if win_start > 1e-4 else []
            media.run([ff, "-hide_banner", "-y", *seek, "-t", f"{win_dur + 0.5:.4f}", "-i", str(video),
                       "-filter_complex", graph, "-map", label, "-an", *VIDEO_ENC_ARGS, "-force_key_frames", "0",
                       str(out)], ctx, what="video retime")
            slices.append(out)
        listing = slices_dir / "concat.txt"
        listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in slices), encoding="utf-8")
        media.run([ff, "-hide_banner", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy",
                   str(work)], ctx, what="video retime join")
    finally:
        shutil.rmtree(slices_dir, ignore_errors=True)
    return Decision("file", file_path=str(work), video_dur=media.duration(work) or expected + tail)


def retime_audio(ctx: JobContext, src: Path, plan: list[dict], duration: float, out: Path) -> None:
    """Retime a (spliced) background bed with atempo per chunk so it follows the retimed video."""
    ff = media.ffmpeg()
    chunks = expand_chunks(plan, duration)
    parts_dir = out.with_suffix(".parts")
    parts_dir.mkdir(parents=True, exist_ok=True)
    try:
        names = []
        for bi in range(0, len(chunks), 16):
            batch = chunks[bi:bi + 16]
            origin = batch[0][0]
            filters = []
            for i, (a, b, ratio) in enumerate(batch):
                if not math.isfinite(ratio) or ratio <= 0:
                    raise ValueError("Invalid retime ratio")
                filters.append(f"[0:a]atrim=start={a - origin:.9f}:end={b - origin:.9f},asetpts=PTS-STARTPTS,"
                               f"{media.atempo_chain(1 / ratio)},apad,atrim=duration={(b - a) * ratio:.9f}[c{i}]")
            filters.append("".join(f"[c{i}]" for i in range(len(batch))) + f"concat=n={len(batch)}:v=0:a=1[out]")
            name = parts_dir / f"batch{bi}.wav"
            media.run([ff, "-y", "-ss", str(origin), "-t", str(batch[-1][1] - origin), "-i", str(src),
                       "-filter_complex", ";".join(filters), "-map", "[out]", "-c:a", "pcm_f32le", str(name)], ctx,
                      what="background retime")
            names.append(name)
        listing = parts_dir / "concat.txt"
        listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in names), encoding="utf-8")
        media.run([ff, "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c:a", "copy", str(out)], ctx,
                  what="background retime join")
    finally:
        shutil.rmtree(parts_dir, ignore_errors=True)
