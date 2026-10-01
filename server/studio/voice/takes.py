"""Takes: every speech render, with the settings that produced it. A take's audio is a regular audio
``Output``; ``voice_takes`` adds engine, voice, language, design tags, seed, timing and a star."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .. import db
from ..schemas import Output
from ..schemas_voice import VoiceProfile, VoiceTake
from . import profiles
from .profiles import VoiceError

_TAG_RE = re.compile(r"\[[^\]]*\]")


def record(out: Output, *, engine: str, language: str | None, instruct: str | None, profile_id: str | None,
           profile_name: str | None, seed: int | None, gen_time_s: float, spoken: str) -> None:
    db.execute(
        """INSERT INTO voice_takes(id, engine, language, instruct, profile_id, profile_name, seed, gen_time_s,
                                   spoken_text) VALUES(?,?,?,?,?,?,?,?,?)""",
        (out.id, engine, language, instruct, profile_id, profile_name, seed, round(gen_time_s, 2), spoken),
    )


def _to_take(r: object) -> VoiceTake:
    return VoiceTake(
        id=r["id"], url=r["url"], text=r["prompt"], model_id=r["model_id"], engine=r["engine"],  # type: ignore[index]
        language=r["language"], instruct=r["instruct"], profile_id=r["profile_id"],  # type: ignore[index]
        profile_name=r["profile_name"], seed=r["seed"], params=json.loads(r["params"]),  # type: ignore[index]
        duration_s=r["duration_s"] or 0.0, gen_time_s=r["gen_time_s"], starred=bool(r["starred"]),  # type: ignore[index]
        created_at=r["created_at"],  # type: ignore[index]
    )


_SELECT = "SELECT t.*, o.url, o.prompt, o.model_id, o.params, o.duration_s, o.created_at, o.path " \
          "FROM voice_takes t JOIN outputs o ON o.id = t.id"


def list_takes(limit: int, starred: bool | None = None) -> list[VoiceTake]:
    where = "" if starred is None else f" WHERE t.starred = {int(starred)}"
    return [_to_take(r) for r in db.query(f"{_SELECT}{where} ORDER BY o.created_at DESC LIMIT ?", (limit,))]


def _get_row(take_id: str) -> object:
    r = db.query_one(f"{_SELECT} WHERE t.id = ?", (take_id,))
    if r is None:
        raise VoiceError(f"Take '{take_id}' not found", 404)
    return r


def get(take_id: str) -> VoiceTake:
    return _to_take(_get_row(take_id))


def source(take_id: str) -> tuple[VoiceTake, Path, str]:
    """The take, its audio file and the transcript of that audio (as spoken, markup removed)."""
    r = _get_row(take_id)
    path = Path(r["path"])  # type: ignore[index]
    if not path.exists():
        raise VoiceError("The take's audio file is missing", 404)
    spoken = " ".join(_TAG_RE.sub(" ", r["spoken_text"] or r["prompt"]).split())  # type: ignore[index]
    return _to_take(r), path, spoken


def set_starred(take_id: str, starred: bool) -> VoiceTake:
    _get_row(take_id)
    db.execute("UPDATE voice_takes SET starred = ? WHERE id = ?", (int(starred), take_id))
    return get(take_id)


def delete(take_id: str) -> None:
    r = _get_row(take_id)
    Path(r["path"]).unlink(missing_ok=True)  # type: ignore[index]
    db.delete_output(take_id)  # cascades to voice_takes


def lock(take_id: str, profile_id: str | None) -> VoiceProfile:
    """Pin a profile to this take: the take becomes its reference and the take's seed is fixed."""
    take, audio, spoken = source(take_id)
    target = profile_id or take.profile_id
    if take.engine != "omnivoice":
        raise VoiceError("Only OmniVoice takes can be locked into a voice")
    if not target:
        raise VoiceError("Pick one of your voices to lock this take into")
    return profiles.lock(target, audio, spoken, take.seed)
