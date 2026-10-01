"""The game master: each turn a chat model gets the authoritative state, the running summary and the last few turns
(never the whole history, so long campaigns stay fast and nothing depends on the model's memory), narrates the
outcome of the player's action — resolved with a server-rolled d20 — and proposes state changes as JSON, which
``rules.apply`` validates. Narration streams to the client over the event bus; the JSON block never does."""

from __future__ import annotations

import asyncio
import json
import re
import traceback
from typing import Any

from .. import db, events
from ..agent.providers import get_provider
from ..agent.types import Message, ProviderError, StepEnd, TextDelta
from ..events import bus
from ..schemas_game import CombatRequest, EvGameDelta, EvGameError, EvGameTurn, GamePending, GameState, GameTurn
from . import combat, rules, store

OPENING_ACTION = "Begin the adventure."
RECENT_TURNS = 4
_FALLBACK_CHOICES = ["Look around carefully", "Check my gear", "Press on"]

SYSTEM = """You are the game master of a text role-playing game. You narrate, voice characters and monsters, and decide
what the player's actions lead to. The server keeps the authoritative game state (character, inventory, location,
enemies, quests); you change it only through the ops below — a change you don't write as an op doesn't happen.

Every turn you get the world, the story so far, facts to remember, the current state, the last few turns, and the
player's action with a d20 roll.

Rules:
- Resolve the action with the roll plus the relevant stat modifier ((stat - 10) // 2) and equipped gear:
  1 = disaster; 2-7 = failure with a cost; 8-12 = partial success or success with a complication; 13-19 = success;
  20 = spectacular success.
- Keep it fair but dangerous: enemies fight back every turn of combat (hp ops on the player), resources run out and
  choices matter. The player can't do impossible things or use items they don't have.
- An enemy at 0 HP is defeated (the server removes it). Award xp for defeated enemies, solved problems and completed
  quests (10-50 typical, more for bosses).
- Using a consumable: item_remove it and apply its effect.
- Bring in quests, characters, loot and places naturally; stay consistent with the facts and the story so far.
- Track goals as quests: when the player is given or takes on a task, add it (quest op, status active); when it is
  achieved or becomes impossible, set it done or failed and award xp.
- Narrate in 2-4 short, vivid paragraphs in the second person ("You..."). Never mention dice, numbers of HP or these
  rules in the narration: the game shows them.
- If the player's HP reaches 0, narrate their death; the server ends the game.

After the narration, write one fenced JSON block exactly like this:
```json
{"ops": [], "choices": ["...", "...", "..."], "event": "...", "facts": [], "scene": "...", "mood": "..."}
```
ops — the state changes, in order:
  {"op":"hp","target":"player","amount":-5}   (target: "player" or an enemy id; negative = damage, positive = healing)
  {"op":"max_hp","amount":5}
  {"op":"gold","amount":12}
  {"op":"xp","amount":25}
  {"op":"stat","stat":"strength","amount":1}   (strength, dexterity, intelligence or charisma)
  {"op":"item_add","name":"Healing Potion","kind":"consumable","qty":1,"description":"Restores 8 HP","power":8}
      (kind: weapon, armor, consumable, key or misc; power = damage, defense or healing)
  {"op":"item_remove","name":"Healing Potion","qty":1}
  {"op":"equip","name":"Iron Sword"}
  {"op":"move","location":"Place name","description":"One sentence."}
  {"op":"enemy_add","name":"Cave Goblin","hp":12,"description":"..."}   (optional "ac", "attack", "damage", "xp";
      otherwise scaled from hp: a goblin ~8-14 hp, a troll ~40, a dragon 150+. The player fights them with combat
      controls the rules resolve, so start encounters with enemy_add rather than narrating whole fights)
  {"op":"enemy_remove","id":"cave-goblin","reason":"flees"}
  {"op":"quest","title":"...","status":"active","notes":"..."}   (status: active, done or failed)
  {"op":"condition","add":"Poisoned"}  or  {"op":"condition","remove":"Poisoned"}
  {"op":"status","value":"won"}   (only when the whole adventure is truly complete)
choices — 3 or 4 short, distinct things the player could do next (under 12 words each), including a risky one.
event — one sentence saying what happened this turn (the server keeps these as the game's journal, your memory).
scene — one vivid sentence describing what the player sees right now, for an illustration (subjects, place, light).
mood — 4-8 music style tags for this moment's soundtrack, e.g. "tense, dark ambient, low strings, heartbeat drums".
facts — new things to remember for the rest of the game (names, promises, secrets), or []."""

OPENING = """This is the first turn. Set the opening scene and give the character a starting kit that fits their class
and the world. Your ops must include: 3-6 item_add (a weapon, some protection, a consumable), a gold op, a move op for
the starting location, and a quest op for the first goal the scene sets up."""

REPAIR_SYSTEM = """You convert a game master's narration into the game's JSON update. Reply with only the JSON object,
no prose: {"ops": [...], "choices": [...], "event": "...", "facts": [...], "scene": "...", "mood": "..."}, using the op
formats you are given."""

_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*(?:```|$)", re.DOTALL)
_THINK = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL)
_LABEL = re.compile(r"^\s*(?:\*\*)?narration(?:\*\*)?\s*:\s*(?:\*\*)?\s*", re.IGNORECASE)  # "Narration:" some models add


def _state_view(state: GameState) -> dict[str, Any]:
    """The state as the model sees it: compact, without the summary and facts (sent separately)."""
    p = state.player
    return {
        "player": {"name": p.name, "class": p.role, "level": p.level, "hp": f"{p.hp}/{p.max_hp}", "gold": p.gold,
                   "xp": f"{p.xp}/{p.xp_next}", "stats": p.stats.model_dump(), "conditions": p.conditions},
        "inventory": [{"name": i.name, "kind": i.kind, "qty": i.qty, **({"equipped": True} if i.equipped else {}),
                       **({"power": i.power} if i.power is not None else {})} for i in state.inventory],
        "location": state.location.model_dump(),
        "enemies": [{"id": e.id, "name": e.name, "hp": f"{e.hp}/{e.max_hp}"} for e in state.enemies],
        "quests": [{"title": q.title, "status": q.status, "notes": q.notes} for q in state.quests],
    }


def _prompt(state: GameState, recent: list[GameTurn], action: str, roll: int | None,
            rnd: combat.Round | None = None) -> str:
    parts = [f"WORLD: {state.setting}", f"STORY SO FAR: {state.summary or '(the adventure is just beginning)'}"]
    if state.chronicle:
        parts.append("JOURNAL (what happened since, in order):\n" + "\n".join(f"- {e}" for e in state.chronicle))
    if state.facts:
        parts.append("FACTS TO REMEMBER:\n" + "\n".join(f"- {f}" for f in state.facts))
    parts.append("CURRENT STATE (authoritative):\n" + json.dumps(_state_view(state), ensure_ascii=False))
    if recent:
        parts.append("RECENT TURNS:\n" + "\n\n".join(f"> Player: {t.action}\n{t.narration[:1500]}" for t in recent))
    if len(state.chronicle) >= rules.FOLD_AT:
        oldest = rules.FOLD_COUNT
        parts.append(f'Also add "summary" to the JSON: the STORY SO FAR rewritten to include the first {oldest} journal '
                     "entries (keep every important event, place and character; under 200 words). Those entries are then "
                     "removed from the journal.")
    if rnd is not None:
        parts.append(f'PLAYER ACTION: "{action}"\nCOMBAT ROUND - already resolved by the game rules; these results are '
                     f"final:\n{combat.describe(rnd, state)}\nNarrate exactly this: the blows, misses and their weight. "
                     "Don't write hp, xp or enemy_remove ops this turn (already applied). You may add loot from "
                     "defeated enemies (item_add, gold), conditions, or new enemies joining the fight.")
    elif roll is None:
        parts.append(OPENING)
    else:
        parts.append(f'PLAYER ACTION: "{action}"\nd20 roll for this action: {roll}')
    parts.append("Write the next turn: narration, then the JSON block.")
    return "\n\n".join(parts)


def _split(text: str) -> tuple[str, dict[str, Any] | None]:
    """(narration, the JSON update or None) from the model's reply."""
    text = _LABEL.sub("", _THINK.sub("", text), count=1)
    matches = list(_FENCE.finditer(text))
    if matches:
        m = matches[-1]
        return text[:m.start()].strip(), _loads(m.group(1))
    idx = text.rfind('{"ops"')
    if idx >= 0:
        return text[:idx].strip().rstrip("`").strip(), _loads(text[idx:].strip().rstrip("`"))
    return text.strip(), None


def _loads(raw: str) -> dict[str, Any] | None:
    try:
        data = json.loads(raw)
    except ValueError:
        try:  # trailing prose after the object
            data, _ = json.JSONDecoder().raw_decode(raw)
        except ValueError:
            return None
    return data if isinstance(data, dict) else None


class _NarrationStream:
    """Forward narration deltas, holding back the JSON block (it starts at a ``` fence or a bare {"ops")."""

    def __init__(self, gid: str, pending: GamePending) -> None:
        self.gid, self.pending, self.buf, self.sent, self.done = gid, pending, "", 0, False

    def feed(self, text: str) -> None:
        self.buf += text
        if self.done:
            return
        visible = _THINK.sub("", self.buf) if "<think>" in self.buf else self.buf
        cut = min((i for i in (visible.find("```"), visible.find('{"ops"')) if i >= 0), default=-1)
        end = cut if cut >= 0 else max(self.sent, len(visible) - 6)  # hold back what may be the start of a fence
        if end > self.sent:
            chunk = visible[self.sent:end]
            self.sent = end
            self.pending.narration += chunk
            bus.publish(EvGameDelta(game_id=self.gid, text=chunk))
        self.done = cut >= 0


class GameService:
    def __init__(self) -> None:
        self._pending: dict[str, GamePending] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def pending(self, gid: str) -> GamePending | None:
        return self._pending.get(gid)

    def busy(self, gid: str) -> bool:
        return gid in self._pending

    def start_turn(self, gid: str, action: str = "", *, opening: bool = False,
                   fight: CombatRequest | None = None) -> GamePending:
        """Start a turn: a free action (rolled from the dice bag), the opening scene, or a combat round the rules
        settle right here (``combat.CombatError`` when it isn't possible)."""
        if self.busy(gid):
            raise RuntimeError("The game master is still writing the last turn")
        row = store.get_row(gid)
        state = store.state_of(row)
        before = state.model_copy(deep=True)  # saved with the turn: undo restores the dice and the whole round
        rnd = combat.resolve(state, fight) if fight is not None else None
        if rnd is not None:
            pending = GamePending(action=rnd.action, roll=rnd.roll, combat=rnd.rolls)
        else:
            pending = GamePending(action=action, roll=None if opening else rules.draw_d20(state))
        self._pending[gid] = pending
        self._tasks[gid] = asyncio.create_task(self._run(gid, row, state, before, pending, rnd), name=f"game-{gid}")
        return pending

    def stop(self, gid: str) -> asyncio.Task[None] | None:
        task = self._tasks.get(gid)
        if task is not None and not task.done():
            task.cancel()
            return task
        return None

    async def shutdown(self) -> None:
        tasks = [t for t in (self.stop(gid) for gid in list(self._tasks)) if t is not None]
        if tasks:
            await asyncio.wait(tasks, timeout=5)

    async def _run(self, gid: str, row: dict, state: GameState, before: GameState, pending: GamePending,
                   rnd: combat.Round | None = None) -> None:
        try:
            recent = await asyncio.to_thread(store.turns, gid, RECENT_TURNS)
            provider = get_provider(row["model"])
            stream = _NarrationStream(gid, pending)
            prompt = _prompt(state, recent, pending.action, pending.roll, rnd)
            reply = ""
            async for ev in provider.stream(SYSTEM, [Message("user", prompt)], None):
                if isinstance(ev, TextDelta):
                    stream.feed(ev.text)
                elif isinstance(ev, StepEnd):
                    reply = ev.text or stream.buf
            narration, data = _split(reply or stream.buf)
            if data is None:  # the model wrote no (readable) JSON: ask for just the update
                data = await self._repair(provider, prompt, narration)
            changes = (rnd.changes if rnd else []) + rules.apply(state, data.get("ops") or [] if data else [],
                                                                  resolved=rnd is not None)
            rules.remember(state, data or {}, narration)
            choices = [str(c).strip()[:120] for c in (data.get("choices") or [] if data else []) if str(c).strip()][:4]
            turn = GameTurn(id=store.new_id(), seq=await asyncio.to_thread(store.next_seq, gid), action=pending.action,
                            roll=pending.roll, narration=narration or pending.narration.strip(),
                            choices=choices or ([] if state.status != "playing" else _FALLBACK_CHOICES),
                            changes=changes, combat=pending.combat,
                            scene=str(data.get("scene") or "").strip()[:400] if data else "",
                            mood=str(data.get("mood") or "").strip()[:200] if data else "",
                            created_at=db.now_iso())
            await asyncio.to_thread(store.add_turn, gid, turn, before, state)
            bus.publish(EvGameTurn(game_id=gid, turn=turn, state=state))
        except asyncio.CancelledError:
            bus.publish(EvGameError(game_id=gid, message="Stopped"))
        except ProviderError as exc:
            bus.publish(EvGameError(game_id=gid, message=str(exc)))
        except Exception as exc:
            events.log("error", "game", f"Turn failed: {exc}\n{traceback.format_exc(limit=6)}")
            bus.publish(EvGameError(game_id=gid, message=f"{type(exc).__name__}: {exc}"))
        finally:
            self._pending.pop(gid, None)
            self._tasks.pop(gid, None)

    @staticmethod
    async def _repair(provider: Any, prompt: str, narration: str) -> dict[str, Any] | None:
        text = ""
        request = f"{prompt}\n\nThe narration for this turn was:\n{narration}\n\nWrite only the JSON update for it."
        async for ev in provider.stream(REPAIR_SYSTEM + "\n\n" + SYSTEM.split("ops — ", 1)[-1],
                                        [Message("user", request)], None):
            if isinstance(ev, TextDelta):
                text += ev.text
        return _split("```json\n" + text.strip().strip("`").removeprefix("json").strip() + "\n```")[1]


games = GameService()
