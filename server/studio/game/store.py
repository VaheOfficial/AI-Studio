"""Games in sqlite: one row per game (its current ``GameState`` as JSON) and one per turn (with the state before it, so
the last turn can be undone)."""

from __future__ import annotations

import json
import uuid

from .. import db
from ..schemas_game import CombatRoll, GameState, GameSummary, GameTurn

_SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    model TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS game_turns (
    id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    action TEXT NOT NULL,
    roll INTEGER,
    narration TEXT NOT NULL,
    choices TEXT NOT NULL,
    changes TEXT NOT NULL,
    state_before TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS game_turns_game ON game_turns(game_id, seq);
"""


class NotFound(KeyError):
    pass


# Added by game mode 2.0; saves created before get the columns on start
_TURN_COLUMNS = {"combat": "TEXT", "scene": "TEXT", "mood": "TEXT", "image": "TEXT", "audio": "TEXT"}


def init() -> None:
    for stmt in filter(str.strip, _SCHEMA.split(";")):
        db.execute(stmt)
    for table, columns in (("game_turns", _TURN_COLUMNS), ("games", {"soundtrack": "TEXT"})):
        have = {r["name"] for r in db.query(f"PRAGMA table_info({table})")}
        for name, sql_type in columns.items():
            if name not in have:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def create(title: str, model: str, state: GameState) -> str:
    gid = new_id()
    now = db.now_iso()
    db.execute("INSERT INTO games(id, title, model, state, created_at, updated_at) VALUES(?,?,?,?,?,?)",
               (gid, title, model, state.model_dump_json(), now, now))
    return gid


def get_row(gid: str) -> dict:
    r = db.query_one("SELECT * FROM games WHERE id = ?", (gid,))
    if r is None:
        raise NotFound(gid)
    return dict(r)


def state_of(row: dict) -> GameState:
    return GameState.model_validate_json(row["state"])


def turns(gid: str, limit: int | None = None) -> list[GameTurn]:
    """The game's turns in order (the last ``limit`` when given)."""
    rows = db.query("SELECT * FROM game_turns WHERE game_id = ? ORDER BY seq DESC" + (" LIMIT ?" if limit else ""),
                    (gid, limit) if limit else (gid,))
    return [_turn(r) for r in reversed(rows)]


def _turn(r) -> GameTurn:
    return GameTurn(id=r["id"], seq=r["seq"], action=r["action"], roll=r["roll"], narration=r["narration"],
                    choices=json.loads(r["choices"]), changes=json.loads(r["changes"]),
                    combat=[CombatRoll.model_validate(c) for c in json.loads(r["combat"] or "[]")],
                    scene=r["scene"] or "", mood=r["mood"] or "", image=r["image"], audio=r["audio"],
                    created_at=r["created_at"])


def get_turn(gid: str, turn_id: str) -> GameTurn:
    r = db.query_one("SELECT * FROM game_turns WHERE game_id = ? AND id = ?", (gid, turn_id))
    if r is None:
        raise NotFound(turn_id)
    return _turn(r)


def set_media(turn_id: str, *, image: str | None = None, audio: str | None = None) -> None:
    if image is not None:
        db.execute("UPDATE game_turns SET image = ? WHERE id = ?", (image, turn_id))
    if audio is not None:
        db.execute("UPDATE game_turns SET audio = ? WHERE id = ?", (audio, turn_id))


def soundtrack(row: dict) -> dict[str, str]:
    return json.loads(row.get("soundtrack") or "{}")


def set_music(gid: str, location: str, url: str) -> None:
    """Remember the track composed for a location (kept outside the state, which a running turn rewrites)."""
    tracks = soundtrack(get_row(gid))
    tracks[location] = url
    db.execute("UPDATE games SET soundtrack = ? WHERE id = ?", (json.dumps(tracks), gid))


def add_turn(gid: str, turn: GameTurn, state_before: GameState, state_after: GameState) -> None:
    db.execute(
        """INSERT INTO game_turns(id, game_id, seq, action, roll, narration, choices, changes, combat, scene, mood,
                                  state_before, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (turn.id, gid, turn.seq, turn.action, turn.roll, turn.narration, json.dumps(turn.choices),
         json.dumps([c.model_dump() for c in turn.changes]), json.dumps([c.model_dump() for c in turn.combat]),
         turn.scene, turn.mood, state_before.model_dump_json(), turn.created_at))
    db.execute("UPDATE games SET state = ?, updated_at = ? WHERE id = ?", (state_after.model_dump_json(), db.now_iso(), gid))


def next_seq(gid: str) -> int:
    r = db.query_one("SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM game_turns WHERE game_id = ?", (gid,))
    return int(r["n"]) if r else 1


def undo(gid: str) -> bool:
    """Drop the last turn and restore the state from before it; False when there is nothing to undo."""
    r = db.query_one("SELECT id, state_before FROM game_turns WHERE game_id = ? ORDER BY seq DESC LIMIT 1", (gid,))
    if r is None:
        return False
    db.execute("DELETE FROM game_turns WHERE id = ?", (r["id"],))
    db.execute("UPDATE games SET state = ?, updated_at = ? WHERE id = ?", (r["state_before"], db.now_iso(), gid))
    return True


def update(gid: str, **fields: str) -> None:
    allowed = {k: v for k, v in fields.items() if k in ("title", "model")}
    if allowed:
        cols = ", ".join(f"{k} = ?" for k in allowed)
        db.execute(f"UPDATE games SET {cols}, updated_at = ? WHERE id = ?", (*allowed.values(), db.now_iso(), gid))


def delete(gid: str) -> None:
    db.execute("DELETE FROM game_turns WHERE game_id = ?", (gid,))
    db.execute("DELETE FROM games WHERE id = ?", (gid,))


def summaries() -> list[GameSummary]:
    rows = db.query("""SELECT g.*, (SELECT COUNT(*) FROM game_turns t WHERE t.game_id = g.id) AS n
                       FROM games g ORDER BY g.updated_at DESC""")
    out = []
    for r in rows:
        st = GameState.model_validate_json(r["state"])
        out.append(GameSummary(id=r["id"], title=r["title"], player_name=st.player.name, role=st.player.role,
                               level=st.player.level, status=st.status, turns=r["n"], updated_at=r["updated_at"]))
    return out
