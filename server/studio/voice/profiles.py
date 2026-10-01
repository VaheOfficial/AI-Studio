"""Voice profiles: engine presets (Kokoro voices, Chatterbox default), clones (a reference clip plus
its transcript) and designs (design tags plus the rendered sample that pins the voice).

A profile can be *locked* to one of its takes: the take becomes the reference and its seed is fixed, so
the voice renders reproducibly. Reference clips are staged first (normalised to 24 kHz mono, trimmed to
the best ~15 s window by speech content, auto-transcribed with an installed Whisper model), then saved.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import uuid
import wave
from dataclasses import dataclass, replace
from pathlib import Path

from ..osenv import NO_WINDOW
from .. import config, db, generation, openrouter_catalog
from ..models import ModelError
from ..runtimes import WorkerError
from ..schemas import InstalledModel, TranscribeResult
from ..schemas_voice import (
    AUTO_VOICE,
    CloneProfileCreate,
    DesignProfileCreate,
    ProfileUpdate,
    SpeakRequest,
    StagedReference,
    VoiceProfile,
)
from . import languages
from .taxonomy import sanitize_instruct, states_from_instruct

STAGED_DIR = config.VOICES_DIR / "staged"
MIN_REF_S = 3.0
MAX_REF_S = 20.0
WINDOW_S = 15.0
_STAGED_TTL_S = 24 * 3600

# (voice name, display name, gender, language) — English Kokoro v1.0 voices.
_KOKORO_PRESETS: list[tuple[str, str, str, str]] = [
    ("af_heart", "Heart", "female", "en-US"), ("af_bella", "Bella", "female", "en-US"),
    ("af_nicole", "Nicole", "female", "en-US"), ("af_aoede", "Aoede", "female", "en-US"),
    ("af_kore", "Kore", "female", "en-US"), ("af_sarah", "Sarah", "female", "en-US"),
    ("af_nova", "Nova", "female", "en-US"), ("af_sky", "Sky", "female", "en-US"),
    ("af_alloy", "Alloy", "female", "en-US"), ("af_jessica", "Jessica", "female", "en-US"),
    ("af_river", "River", "female", "en-US"),
    ("am_michael", "Michael", "male", "en-US"), ("am_fenrir", "Fenrir", "male", "en-US"),
    ("am_puck", "Puck", "male", "en-US"), ("am_echo", "Echo", "male", "en-US"),
    ("am_eric", "Eric", "male", "en-US"), ("am_liam", "Liam", "male", "en-US"),
    ("am_onyx", "Onyx", "male", "en-US"), ("am_adam", "Adam", "male", "en-US"),
    ("am_santa", "Santa", "male", "en-US"),
    ("bf_emma", "Emma", "female", "en-GB"), ("bf_isabella", "Isabella", "female", "en-GB"),
    ("bf_alice", "Alice", "female", "en-GB"), ("bf_lily", "Lily", "female", "en-GB"),
    ("bm_george", "George", "male", "en-GB"), ("bm_fable", "Fable", "male", "en-GB"),
    ("bm_lewis", "Lewis", "male", "en-GB"), ("bm_daniel", "Daniel", "male", "en-GB"),
]
_KOKORO_FEATURED = {"af_heart", "af_bella", "bf_emma", "am_michael", "bm_george"}


class VoiceError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


# --------------------------------- audio ---------------------------------


def _url(path: Path) -> str:
    return "/files/voices/" + path.relative_to(config.VOICES_DIR).as_posix()


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def _ffmpeg(args: list[str]) -> None:
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise VoiceError("ffmpeg is not on PATH; it is needed to decode and trim reference audio", 500)
    proc = subprocess.run([exe, "-y", "-hide_banner", "-loglevel", "error", *args], capture_output=True, text=True,
                          creationflags=NO_WINDOW)
    if proc.returncode != 0:
        raise VoiceError(f"Could not process the audio: {proc.stderr.strip()[-400:]}")


def _to_wav(src: Path, dst: Path, start: float | None = None, end: float | None = None) -> None:
    """Any upload (webm/ogg/mp3/wav/video) -> 24 kHz mono 16-bit WAV, optionally cut to [start, end]."""
    cut = (["-ss", f"{start:.3f}"] if start is not None else []) + (["-to", f"{end:.3f}"] if end is not None else [])
    _ffmpeg(["-i", str(src), *cut, "-vn", "-ac", "1", "-ar", "24000", "-sample_fmt", "s16", str(dst)])


# ------------------------------ transcription ------------------------------


def stt_model() -> InstalledModel | None:
    """The installed Whisper model to transcribe references with: a loaded one, else the largest."""
    stt = [m for m in db.list_installed() if m.kind == "stt" and m.runtime == "faster-whisper"]
    loaded = [m for m in stt if m.status == "loaded"]
    return (loaded or sorted(stt, key=lambda m: m.size_bytes, reverse=True) or [None])[0]


def transcribe(path: Path, language: str | None = None) -> TranscribeResult | None:
    """Blocking. ``None`` when no Whisper model is installed."""
    m = stt_model()
    if m is None:
        return None
    try:
        return generation.transcribe(m.id, path, language)
    except (ModelError, WorkerError) as exc:
        raise VoiceError(f"Transcription with {m.name} failed: {exc}", 502) from exc


def _best_window(result: TranscribeResult) -> tuple[float, float] | None:
    """The ~15 s span holding the most transcribed speech (whole segments only)."""
    best: tuple[int, float, float] | None = None
    segs = result.segments
    for i, first in enumerate(segs):
        chosen = [s for s in segs[i:] if s.end <= first.start + WINDOW_S]
        if not chosen:
            continue
        score = sum(len(s.text.strip()) for s in chosen)
        if best is None or score > best[0]:
            best = (score, first.start, chosen[-1].end)
    return (best[1], best[2]) if best else None


# ------------------------------ staged references ------------------------------


def staged_path(ref_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", ref_id):
        raise VoiceError(f"Invalid reference id '{ref_id}'")
    path = STAGED_DIR / f"{ref_id}.wav"
    if not path.exists():
        raise VoiceError("The reference clip expired or was already used; upload it again", 404)
    return path


def _clean_staged() -> None:
    cutoff = time.time() - _STAGED_TTL_S
    for f in STAGED_DIR.glob("*.wav"):
        if f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)


def _staged(ref_id: str, path: Path, source_s: float, trimmed: bool, language: str | None) -> StagedReference:
    result = transcribe(path, language)
    text = result.text.strip() if result else ""
    note = None
    if result is None:
        note = "No Whisper model installed — type the transcript yourself or install one from the Models page."
    elif not text:
        note = "No speech was recognised in the clip."
    return StagedReference(id=ref_id, url=_url(path), duration_s=round(wav_duration(path), 2),
                           source_duration_s=round(source_s, 2), trimmed=trimmed, text=text,
                           language=result.language if result else None, transcribed=result is not None, note=note)


def stage_reference(upload: Path, language: str | None = None) -> StagedReference:
    """Blocking: normalise, validate (>= 3 s), trim clips over 20 s to the best 15 s of speech, transcribe."""
    STAGED_DIR.mkdir(parents=True, exist_ok=True)
    _clean_staged()
    ref_id = uuid.uuid4().hex[:12]
    dst = STAGED_DIR / f"{ref_id}.wav"
    src = STAGED_DIR / f"{ref_id}.src.wav"
    try:
        _to_wav(upload, src)
        source_s = wav_duration(src)
        if source_s < MIN_REF_S:
            raise VoiceError(f"The clip is {source_s:.1f} s long; a voice reference needs at least {MIN_REF_S:.0f} s")
        if source_s <= MAX_REF_S:
            src.replace(dst)
            return _staged(ref_id, dst, source_s, False, language)
        result = transcribe(src, language)
        window = _best_window(result) if result else None
        start, end = window if window else (0.0, WINDOW_S)
        _to_wav(src, dst, max(0.0, start - 0.1), min(source_s, end + 0.2))
        return _staged(ref_id, dst, source_s, True, language)
    except (VoiceError, wave.Error, EOFError) as exc:
        dst.unlink(missing_ok=True)
        if isinstance(exc, VoiceError):
            raise
        raise VoiceError(f"The uploaded audio is not readable: {exc}") from exc
    finally:
        src.unlink(missing_ok=True)


def retranscribe(ref_id: str, language: str | None = None) -> StagedReference:
    path = staged_path(ref_id)
    return _staged(ref_id, path, wav_duration(path), False, language)


# --------------------------------- presets ---------------------------------


def presets() -> list[VoiceProfile]:
    out: list[VoiceProfile] = []
    for m in db.list_installed():
        if m.runtime == "kokoro":
            out.extend(
                VoiceProfile(id=f"{m.id}:{name}", name=f"{label} ({'US' if lang == 'en-US' else 'UK'})", kind="preset",
                             model_id=m.id, language="en", gender=gender,
                             tags=["featured"] if name in _KOKORO_FEATURED else [])
                for name, label, gender, lang in _KOKORO_PRESETS)
        elif m.runtime == "chatterbox":
            out.append(VoiceProfile(id=f"{m.id}:default", name="Chatterbox default", kind="preset", model_id=m.id,
                                    language="en", gender="female", tags=["default"]))
        elif m.runtime == "openrouter" and m.kind == "voice":
            out.extend(openrouter_catalog.voices_for(m))
    return out


# ------------------------------ stored profiles ------------------------------


def _file(name: str | None) -> Path | None:
    return config.VOICES_DIR / name if name else None


def _duration(path: Path | None) -> float | None:
    try:
        return round(wav_duration(path), 2) if path and path.exists() else None
    except (wave.Error, EOFError):
        return None


def _to_profile(r: object) -> VoiceProfile:
    ref = _file(r["ref_audio"])  # type: ignore[index]
    locked = _file(r["locked_audio"])  # type: ignore[index]
    return VoiceProfile(
        id=r["id"], name=r["name"], kind=r["kind"], language=r["language"],  # type: ignore[index]
        tags=json.loads(r["tags"]), ref_audio_url=_url(ref) if ref else None,  # type: ignore[index]
        ref_text=r["ref_text"], ref_duration_s=_duration(ref), instruct=r["instruct"],  # type: ignore[index]
        vd_states=json.loads(r["vd_states"]) if r["vd_states"] else None, seed=r["seed"],  # type: ignore[index]
        is_locked=bool(r["is_locked"]), locked_audio_url=_url(locked) if locked else None,  # type: ignore[index]
        locked_text=r["locked_text"], archetype_id=r["archetype_id"],  # type: ignore[index]
        created_at=r["created_at"],  # type: ignore[index]
    )


def _row(profile_id: str) -> object:
    r = db.query_one("SELECT * FROM voice_profiles WHERE id = ?", (profile_id,))
    if r is None:
        raise VoiceError(f"Voice '{profile_id}' not found", 404)
    return r


def list_profiles() -> list[VoiceProfile]:
    stored = [_to_profile(r) for r in db.query("SELECT * FROM voice_profiles ORDER BY created_at DESC")]
    return stored + presets()


def get(profile_id: str) -> VoiceProfile:
    return _to_profile(_row(profile_id))


def find_archetype_profile(archetype_id: str) -> VoiceProfile | None:
    r = db.query_one("SELECT * FROM voice_profiles WHERE archetype_id = ?", (archetype_id,))
    return _to_profile(r) if r else None


def archetype_profile_ids() -> dict[str, str]:
    return {r["archetype_id"]: r["id"] for r in db.query(
        "SELECT id, archetype_id FROM voice_profiles WHERE archetype_id IS NOT NULL")}


def _check_language(language: str | None) -> str | None:
    if language and not languages.is_known(language):
        raise VoiceError(f"Unknown language '{language}'")
    return language or None


def _insert(p: VoiceProfile, ref_audio: str) -> VoiceProfile:
    db.execute(
        """INSERT INTO voice_profiles(id, name, kind, language, tags, ref_audio, ref_text, instruct, vd_states, seed,
                                      archetype_id, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (p.id, p.name, p.kind, p.language, json.dumps(p.tags), ref_audio, p.ref_text, p.instruct,
         json.dumps(p.vd_states) if p.vd_states else None, p.seed, p.archetype_id, p.created_at),
    )
    return get(p.id)


def _new_id() -> str:
    return f"vp-{uuid.uuid4().hex[:10]}"


def create_clone(body: CloneProfileCreate) -> VoiceProfile:
    staged = staged_path(body.ref_id)
    pid = _new_id()
    staged.replace(config.VOICES_DIR / f"{pid}.wav")
    return _insert(VoiceProfile(id=pid, name=body.name.strip(), kind="clone", language=_check_language(body.language),
                                tags=body.tags, ref_text=body.ref_text.strip(),
                                instruct=sanitize_instruct(body.instruct) or None, created_at=db.now_iso()),
                   f"{pid}.wav")


def create_design(name: str, audio: Path, ref_text: str, instruct: str | None, seed: int | None,
                  language: str | None, vd_states: dict[str, str] | None, tags: list[str],
                  archetype_id: str | None = None) -> VoiceProfile:
    """A design profile: its rendered sample (copied) becomes the reference that pins the voice."""
    pid = _new_id()
    shutil.copyfile(audio, config.VOICES_DIR / f"{pid}.wav")
    clean = sanitize_instruct(instruct) or None
    return _insert(VoiceProfile(id=pid, name=name.strip(), kind="design", language=_check_language(language), tags=tags,
                                ref_text=ref_text, instruct=clean, vd_states=vd_states or states_from_instruct(clean),
                                seed=seed, archetype_id=archetype_id, created_at=db.now_iso()),
                   f"{pid}.wav")


def create_design_from_take(body: DesignProfileCreate) -> VoiceProfile:
    from . import takes  # late import: takes depends on this module

    take, audio, spoken = takes.source(body.take_id)
    if take.engine != "omnivoice":
        raise VoiceError("Only OmniVoice takes can become a designed voice")
    return create_design(body.name, audio, spoken, take.instruct, take.seed, take.language, body.vd_states, body.tags)


def update(profile_id: str, body: ProfileUpdate) -> VoiceProfile:
    r = _row(profile_id)
    fields = body.model_fields_set
    sets: dict[str, object] = {}
    if body.name is not None:
        sets["name"] = body.name.strip()
    if body.ref_text is not None:
        sets["ref_text"] = body.ref_text.strip()
    if "instruct" in fields:
        sets["instruct"] = sanitize_instruct(body.instruct) or None
    if "language" in fields:
        sets["language"] = _check_language(body.language)
    if body.tags is not None:
        sets["tags"] = json.dumps(body.tags)
    if body.vd_states is not None:
        sets["vd_states"] = json.dumps(body.vd_states)
    if body.ref_id is not None:
        name = f"{profile_id}.wav"
        staged_path(body.ref_id).replace(config.VOICES_DIR / name)
        old = r["ref_audio"]  # type: ignore[index]
        if old and old != name:
            (config.VOICES_DIR / old).unlink(missing_ok=True)
        sets["ref_audio"] = name
        if body.ref_text is None:
            sets["ref_text"] = None  # the old transcript no longer matches; filled on first use
    if sets:
        cols = ", ".join(f"{k} = ?" for k in sets)
        db.execute(f"UPDATE voice_profiles SET {cols} WHERE id = ?", (*sets.values(), profile_id))
    return get(profile_id)


def delete(profile_id: str) -> None:
    if any(p.id == profile_id for p in presets()):
        raise VoiceError("Preset voices belong to their model and cannot be deleted")
    r = _row(profile_id)
    for name in (r["ref_audio"], r["locked_audio"]):  # type: ignore[index]
        if name:
            (config.VOICES_DIR / name).unlink(missing_ok=True)
    db.execute("DELETE FROM voice_profiles WHERE id = ?", (profile_id,))


def lock(profile_id: str, audio: Path, text: str, seed: int | None) -> VoiceProfile:
    _row(profile_id)
    name = f"{profile_id}.locked.wav"
    shutil.copyfile(audio, config.VOICES_DIR / name)
    db.execute("UPDATE voice_profiles SET is_locked = 1, locked_audio = ?, locked_text = ?, seed = ? WHERE id = ?",
               (name, text, seed, profile_id))
    return get(profile_id)


def unlock(profile_id: str) -> VoiceProfile:
    r = _row(profile_id)
    if r["locked_audio"]:  # type: ignore[index]
        (config.VOICES_DIR / r["locked_audio"]).unlink(missing_ok=True)  # type: ignore[index]
    db.execute("UPDATE voice_profiles SET is_locked = 0, locked_audio = NULL, locked_text = NULL WHERE id = ?",
               (profile_id,))
    return get(profile_id)


# ------------------------------ speech conditioning ------------------------------


@dataclass(frozen=True)
class Conditioning:
    """What a TTS worker needs for one request, resolved from the voice + request overrides."""

    profile_id: str | None = None
    profile_name: str | None = None
    language: str | None = None
    instruct: str | None = None
    seed: int | None = None
    ref_audio: str | None = None  # OmniVoice / Chatterbox reference clip
    ref_text: str | None = None
    kokoro_voice: str | None = None  # Kokoro voice file
    kokoro_lang: str | None = None
    locked: bool = False


def _kokoro(m: InstalledModel, voice_id: str) -> Conditioning:
    prefix = f"{m.id}:"
    if not voice_id.startswith(prefix):
        raise VoiceError(f"'{voice_id}' is not a preset of {m.name}; Kokoro only speaks with its own presets")
    name = voice_id[len(prefix):]
    path = Path(m.path) / "voices" / f"{name}.pt"
    if not path.exists():
        raise VoiceError(f"Kokoro voice file missing: {path}", 404)
    label = next((p.name for p in presets() if p.id == voice_id), name)
    return Conditioning(profile_id=voice_id, profile_name=label, language="en", kokoro_voice=str(path),
                        kokoro_lang=name[0])


def resolve(m: InstalledModel, req: SpeakRequest) -> Conditioning:
    if m.runtime == "kokoro":
        return _kokoro(m, req.voice_id)
    explicit_auto = (req.language or "").lower() == "auto"
    language = None if explicit_auto else _check_language(req.language)
    if req.ref_id:
        cond = Conditioning(ref_audio=str(staged_path(req.ref_id)), ref_text=(req.ref_text or "").strip() or None)
    elif req.voice_id in (AUTO_VOICE, f"{m.id}:default"):
        cond = Conditioning()
    else:
        if any(p.id == req.voice_id for p in presets()):
            raise VoiceError(f"'{req.voice_id}' is a preset of another model; pick one of your voices for {m.name}")
        p = get(req.voice_id)
        audio = p.locked_audio_url if p.is_locked else p.ref_audio_url
        ref_path = config.VOICES_DIR / audio.removeprefix("/files/voices/") if audio else None
        cond = Conditioning(profile_id=p.id, profile_name=p.name, language=p.language, instruct=p.instruct,
                            seed=p.seed, ref_audio=str(ref_path) if ref_path else None,
                            ref_text=p.locked_text if p.is_locked else p.ref_text, locked=p.is_locked)
        if m.runtime == "chatterbox" and not cond.ref_audio:
            raise VoiceError(f"'{p.name}' has no reference clip for Chatterbox to clone")
    overrides: dict[str, object] = {}
    if language or explicit_auto:
        overrides["language"] = language
    if req.instruct is not None:
        overrides["instruct"] = sanitize_instruct(req.instruct) or None
    if req.seed is not None:
        overrides["seed"] = req.seed
    cond = replace(cond, **overrides)  # type: ignore[arg-type]
    if not languages.supports(m.runtime, cond.language):
        raise VoiceError(f"{m.name} cannot speak {languages.name_of(cond.language) or cond.language}")
    return cond


def ensure_ref_text(cond: Conditioning) -> Conditioning:
    """Blocking: transcribe a reference that has no transcript yet (legacy clones, replaced clips) and
    remember it on the profile so it runs once."""
    if not cond.ref_audio or cond.ref_text:
        return cond
    result = transcribe(Path(cond.ref_audio))
    if result is None or not result.text.strip():
        raise VoiceError("This voice's reference clip has no transcript and none could be made. Add the transcript "
                         "in Voices → Library (or install a Whisper model).", 409)
    text = result.text.strip()
    if cond.profile_id:
        column = "locked_text" if cond.locked else "ref_text"
        db.execute(f"UPDATE voice_profiles SET {column} = ? WHERE id = ?", (text, cond.profile_id))
    return replace(cond, ref_text=text)
