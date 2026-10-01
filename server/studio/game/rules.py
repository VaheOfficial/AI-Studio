"""The rules the server enforces: starting characters, and applying the game master's proposed changes to the state
(clamped, validated, with level-ups and death handled here — never left to the model)."""

from __future__ import annotations

import random
import re
from typing import Any

from ..schemas_game import (GameChange, GameEnemy, GameItem, GamePlayer, GameQuest, GameState, GameStats)

# Starting stats and HP per class; anything else gets balanced stats.
ROLES: dict[str, tuple[GameStats, int]] = {
    "warrior": (GameStats(strength=15, dexterity=12, intelligence=8, charisma=10), 32),
    "rogue": (GameStats(strength=10, dexterity=16, intelligence=11, charisma=12), 24),
    "mage": (GameStats(strength=8, dexterity=11, intelligence=16, charisma=12), 20),
    "ranger": (GameStats(strength=12, dexterity=15, intelligence=11, charisma=10), 26),
}
_BALANCED = (GameStats(strength=12, dexterity=12, intelligence=12, charisma=12), 26)
_STATS = ("strength", "dexterity", "intelligence", "charisma")
_KINDS = ("weapon", "armor", "consumable", "key", "misc")
MAX_FACTS = 40
MAX_SUMMARY = 1500
# The journal (one line per turn) is folded into the summary: at FOLD_AT entries the game master rewrites the
# summary to absorb the oldest FOLD_COUNT, which are then dropped.
FOLD_AT = 30
FOLD_COUNT = 15
MAX_CHRONICLE = 60


def new_state(setting: str, name: str, role: str) -> GameState:
    stats, hp = ROLES.get(role.strip().lower(), _BALANCED)
    player = GamePlayer(name=name.strip(), role=role.strip(), hp=hp, max_hp=hp, stats=stats.model_copy())
    return GameState(setting=setting.strip(), player=player)


# The d20 is a shuffle bag (drawn without replacement), not independent rolls: every result from 1 to 20 comes up
# once per bag, so streaks of bad or good luck even out. Like the "New Year" card in Catan's dice deck, the bag is
# refilled while a few tiles are still in it, so the last draws of a bag can't be predicted.
D20_REFILL_AT = 4


def draw_from(bag: list[int]) -> int:
    """Draw a d20 from ``bag`` in place (refilled with 1-20 when only ``D20_REFILL_AT`` tiles are left)."""
    if len(bag) <= D20_REFILL_AT:
        bag[:] = range(1, 21)
    return bag.pop(random.randrange(len(bag)))


def draw_d20(state: GameState) -> int:
    """The player's next d20 (enemies draw from their own bag, ``state.enemy_bag``)."""
    return draw_from(state.dice_bag)


def enemy_defaults(hp: int) -> dict[str, int]:
    """Stats for an enemy the game master only gave hit points: tougher enemies hit harder and are harder to hit."""
    return {"ac": min(18, 10 + hp // 10), "attack": min(9, 1 + hp // 12), "damage": min(18, 2 + hp // 8),
            "xp": max(5, hp * 2)}


def xp_for_next(level: int) -> int:
    return 100 * level


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "x"


def _int(value: Any, default: int = 0, lo: int = -9999, hi: int = 9999) -> int:
    try:
        return max(lo, min(hi, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


def find_item(state: GameState, name: str) -> GameItem | None:
    key = name.strip().lower()
    return next((i for i in state.inventory if i.name.lower() == key or i.id == _slug(name)), None) or next(
        (i for i in state.inventory if key and key in i.name.lower()), None)


def find_enemy(state: GameState, ref: str) -> GameEnemy | None:
    key = str(ref).strip().lower()
    return next((e for e in state.enemies if e.id == key or e.name.lower() == key), None) or next(
        (e for e in state.enemies if key and key in e.name.lower()), None)


# On a combat round the rules already settled hit points, experience and who is still standing
_RESOLVED_OPS = {"hp", "max_hp", "xp", "enemy_remove"}


def apply(state: GameState, ops: list[dict[str, Any]], *, resolved: bool = False) -> list[GameChange]:
    """Apply the game master's ops in place; returns what changed, for the turn's change chips. Unknown or malformed
    ops are skipped — a bad proposal never corrupts the state. ``resolved``: a combat round the rules settled; the
    game master's hp/xp/enemy_remove ops are ignored (it only narrates those)."""
    changes: list[GameChange] = []
    p = state.player

    def change(text: str, tone: str = "neutral") -> None:
        changes.append(GameChange(text=text, tone=tone))  # type: ignore[arg-type]

    for op in ops:
        if not isinstance(op, dict):
            continue
        kind = str(op.get("op", "")).lower()
        if resolved and kind in _RESOLVED_OPS:
            continue
        if kind == "hp":
            amount = _int(op.get("amount"), 0, -999, 999)
            target = str(op.get("target") or "player")
            if not amount:
                continue
            if target.lower() in ("player", "you", p.name.lower()):
                before = p.hp
                p.hp = max(0, min(p.max_hp, p.hp + amount))
                if p.hp != before:
                    change(f"{p.hp - before:+d} HP", "good" if amount > 0 else "bad")
            elif (enemy := find_enemy(state, target)) is not None:
                enemy.hp = max(0, min(enemy.max_hp, enemy.hp + amount))
                if enemy.hp == 0:
                    state.enemies.remove(enemy)
                    change(f"Defeated {enemy.name}", "good")
                else:
                    change(f"{enemy.name} {amount:+d} HP", "good" if amount < 0 else "bad")
        elif kind == "max_hp":
            amount = _int(op.get("amount"), 0, -50, 50)
            if amount:
                p.max_hp = max(1, p.max_hp + amount)
                p.hp = min(p.hp, p.max_hp)
                change(f"{amount:+d} max HP", "good" if amount > 0 else "bad")
        elif kind == "gold":
            amount = _int(op.get("amount"), 0, -100000, 100000)
            amount = max(amount, -p.gold)
            if amount:
                p.gold += amount
                change(f"{amount:+d} gold", "good" if amount > 0 else "bad")
        elif kind == "xp":
            amount = _int(op.get("amount"), 0, 0, 5000)
            if amount:
                p.xp += amount
                change(f"+{amount} XP", "good")
                while p.xp >= p.xp_next:
                    p.xp -= p.xp_next
                    p.level += 1
                    p.xp_next = xp_for_next(p.level)
                    p.max_hp += 6
                    p.hp = p.max_hp
                    change(f"Level up! Level {p.level} (+6 max HP, healed)", "good")
        elif kind == "stat":
            stat = str(op.get("stat", "")).lower()
            stat = next((s for s in _STATS if s.startswith(stat[:3])), "") if stat else ""
            amount = _int(op.get("amount"), 0, -5, 5)
            if stat and amount:
                setattr(p.stats, stat, max(1, min(30, getattr(p.stats, stat) + amount)))
                change(f"{stat.capitalize()} {amount:+d}", "good" if amount > 0 else "bad")
        elif kind == "item_add":
            name = str(op.get("name") or "").strip()[:60]
            if not name:
                continue
            qty = _int(op.get("qty"), 1, 1, 999)
            item = find_item(state, name)
            if item is not None and item.name.lower() == name.lower():
                item.qty += qty
            else:
                item_kind = str(op.get("kind") or "misc").lower()
                power = op.get("power")
                state.inventory.append(GameItem(
                    id=_unique(_slug(name), {i.id for i in state.inventory}), name=name,
                    kind=item_kind if item_kind in _KINDS else "misc", qty=qty,  # type: ignore[arg-type]
                    description=str(op.get("description") or "")[:300],
                    power=_int(power, 0, 0, 999) if power is not None else None))
                added = state.inventory[-1]
                # The first weapon / armor is worn right away (nobody carries a sword in their bag)
                if added.kind in ("weapon", "armor") and not any(
                        i.equipped for i in state.inventory if i.kind == added.kind):
                    added.equipped = True
            change(f"+ {name}" + (f" ×{qty}" if qty > 1 else ""), "good")
        elif kind == "item_remove":
            item = find_item(state, str(op.get("name") or ""))
            if item is None:
                continue
            qty = min(_int(op.get("qty"), 1, 1, 999), item.qty)  # one unless told otherwise
            item.qty -= qty
            if item.qty <= 0:
                state.inventory.remove(item)
            change(f"− {item.name}" + (f" ×{qty}" if qty > 1 else ""), "neutral")
        elif kind == "equip":
            item = find_item(state, str(op.get("name") or ""))
            if item is None or item.kind not in ("weapon", "armor"):
                continue
            for other in state.inventory:
                if other.kind == item.kind and other is not item:
                    other.equipped = False
            item.equipped = bool(op.get("equipped", True))
            change(f"{'Equipped' if item.equipped else 'Unequipped'} {item.name}", "neutral")
        elif kind == "move":
            name = str(op.get("location") or op.get("name") or "").strip()[:80]
            if name and name != state.location.name:
                state.location.name = name
                state.location.description = str(op.get("description") or "")[:500]
                change(f"→ {name}", "neutral")
            elif op.get("description"):
                state.location.description = str(op["description"])[:500]
        elif kind == "enemy_add":
            name = str(op.get("name") or "").strip()[:60]
            if not name or len(state.enemies) >= 8:
                continue
            hp = _int(op.get("hp"), 10, 1, 999)
            stats = enemy_defaults(hp)
            state.enemies.append(GameEnemy(
                id=_unique(_slug(name), {e.id for e in state.enemies}), name=name, hp=hp, max_hp=hp,
                description=str(op.get("description") or "")[:300],
                ac=_int(op.get("ac"), stats["ac"], 5, 25), attack=_int(op.get("attack"), stats["attack"], -2, 15),
                damage=_int(op.get("damage"), stats["damage"], 1, 60), xp=_int(op.get("xp"), stats["xp"], 0, 5000)))
            change(f"⚔ {name} ({hp} HP)", "bad")
        elif kind == "enemy_remove":
            enemy = find_enemy(state, str(op.get("id") or op.get("name") or ""))
            if enemy is not None:
                state.enemies.remove(enemy)
                change(f"{enemy.name} {op.get('reason') or 'is gone'}", "neutral")
        elif kind == "quest":
            title = str(op.get("title") or "").strip()[:100]
            if not title:
                continue
            status = str(op.get("status") or "active").lower()
            status = status if status in ("active", "done", "failed") else "active"
            quest = next((q for q in state.quests if q.title.lower() == title.lower()), None)
            if quest is None:
                state.quests.append(GameQuest(id=_unique(_slug(title), {q.id for q in state.quests}), title=title,
                                              status=status, notes=str(op.get("notes") or "")[:300]))  # type: ignore[arg-type]
                change(f"New quest: {title}", "neutral")
            else:
                if op.get("notes"):
                    quest.notes = str(op["notes"])[:300]
                if status != quest.status:
                    quest.status = status  # type: ignore[assignment]
                    change(f"Quest {'complete' if status == 'done' else 'failed'}: {title}",
                           "good" if status == "done" else "bad")
        elif kind == "condition":
            add, remove = str(op.get("add") or "").strip()[:40], str(op.get("remove") or "").strip()[:40]
            if add and add.lower() not in (c.lower() for c in p.conditions):
                p.conditions.append(add)
                change(add, "bad")
            if remove:
                kept = [c for c in p.conditions if c.lower() != remove.lower()]
                if len(kept) != len(p.conditions):
                    p.conditions = kept
                    change(f"No longer {remove.lower()}", "good")
        elif kind == "status" and op.get("value") == "won":
            state.status = "won"
            change("Victory!", "good")
    if p.hp <= 0 and state.status == "playing":
        state.status = "dead"
        change("You have fallen", "bad")
    return changes


def remember(state: GameState, data: dict[str, Any], narration: str) -> None:
    """The game's memory: this turn's journal entry (the model's one-line ``event``, else the narration's first
    sentence), new facts, and — on a fold turn — the rewritten summary that absorbs the oldest journal entries."""
    event = str(data.get("event") or "").strip()
    if not event:
        event = re.split(r"(?<=[.!?])\s", narration.strip(), maxsplit=1)[0] if narration.strip() else ""
    if event:
        state.chronicle.append(event[:240])
    summary = data.get("summary")
    if isinstance(summary, str) and summary.strip() and len(state.chronicle) > FOLD_AT:
        state.summary = summary.strip()[:MAX_SUMMARY]
        state.chronicle = state.chronicle[FOLD_COUNT:]
    elif len(state.chronicle) > MAX_CHRONICLE:  # the model never folded: keep the newest entries
        state.chronicle = state.chronicle[-MAX_CHRONICLE:]
    facts = data.get("facts")
    if isinstance(facts, list):
        for fact in facts:
            text = str(fact).strip()[:200]
            if text and text not in state.facts:
                state.facts.append(text)
        state.facts = state.facts[-MAX_FACTS:]


def _unique(base: str, taken: set[str]) -> str:
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"
