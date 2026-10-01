"""Combat rounds settled by the rules, not the game master: the player's action (attack, defend, flee or use an
item) and every enemy's attack are rolled from the dice bags and applied to the state; the game master then only
narrates the outcome. d20 + bonus against armor class; a natural 20 always hits for double damage, a natural 1
always misses."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from ..schemas_game import CombatRequest, CombatRoll, GameChange, GameEnemy, GameState
from . import rules

FLEE_DC = 12
DEFEND_AC = 4
UNARMED = 2


class CombatError(ValueError):
    """The requested action isn't possible now (no enemies, unknown target or item); message is user-facing."""


@dataclass
class Round:
    action: str  # the turn's action line, e.g. "Attack the Cave Goblin"
    roll: int | None  # the player's d20, when the action needed one
    rolls: list[CombatRoll] = field(default_factory=list)
    changes: list[GameChange] = field(default_factory=list)


def _mod(score: int) -> int:
    return (score - 10) // 2


def player_ac(state: GameState, defending: bool = False) -> int:
    armor = next((i.power or 0 for i in state.inventory if i.kind == "armor" and i.equipped), 0)
    return 10 + _mod(state.player.stats.dexterity) + armor + (DEFEND_AC if defending else 0)


def attack_bonus(state: GameState) -> int:
    s = state.player.stats
    return 2 + (state.player.level - 1) // 4 + max(_mod(s.strength), _mod(s.dexterity))


def _weapon(state: GameState) -> tuple[str, int]:
    w = next((i for i in state.inventory if i.kind == "weapon" and i.equipped), None)
    return (w.name, w.power or UNARMED) if w else ("bare hands", UNARMED)


def _strike(roll: int, total: int, against: int) -> bool:
    return roll == 20 or (roll != 1 and total >= against)


def _note(roll: int) -> str:
    return "critical" if roll == 20 else "fumble" if roll == 1 else ""


def resolve(state: GameState, req: CombatRequest) -> Round:
    """Settle one round in place (the caller keeps a copy of the state from before, for undo)."""
    if not state.enemies:
        raise CombatError("There is nothing to fight right now")
    p = state.player
    defending = False
    fled = False
    if req.kind == "attack":
        enemy = _target(state, req.target)
        weapon, power = _weapon(state)
        rnd = Round(action=f"Attack the {enemy.name}", roll=rules.draw_d20(state))
        bonus = attack_bonus(state)
        hit = _strike(rnd.roll, rnd.roll + bonus, enemy.ac)
        damage = 0
        if hit:
            stat = max(_mod(p.stats.strength), _mod(p.stats.dexterity))
            damage = max(1, power + stat + random.randint(-1, 2)) * (2 if rnd.roll == 20 else 1)
        rnd.rolls.append(CombatRoll(actor=p.name, target=enemy.name, roll=rnd.roll, bonus=bonus,
                                    total=rnd.roll + bonus, against=enemy.ac, hit=hit, damage=damage,
                                    note=_note(rnd.roll) or (f"with {weapon}" if hit else "")))
        if hit:
            killed = damage >= enemy.hp
            rnd.changes += rules.apply(state, [{"op": "hp", "target": enemy.id, "amount": -damage}])
            if killed and enemy.xp:
                rnd.changes += rules.apply(state, [{"op": "xp", "amount": enemy.xp}])
    elif req.kind == "defend":
        rnd = Round(action="Take a defensive stance", roll=None)
        defending = True
        rnd.changes.append(GameChange(text=f"Defending (+{DEFEND_AC} AC)", tone="good"))
    elif req.kind == "flee":
        rnd = Round(action="Try to flee", roll=rules.draw_d20(state))
        bonus = _mod(p.stats.dexterity) + 2
        fled = _strike(rnd.roll, rnd.roll + bonus, FLEE_DC)
        rnd.rolls.append(CombatRoll(actor=p.name, target="escape", roll=rnd.roll, bonus=bonus, total=rnd.roll + bonus,
                                    against=FLEE_DC, hit=fled, note="escaped" if fled else "cornered"))
        if fled:
            state.enemies = []
            rnd.changes.append(GameChange(text="Escaped", tone="good"))
    else:  # item
        item = rules.find_item(state, req.item or "")
        if item is None or item.kind != "consumable":
            raise CombatError(f"You have no usable “{req.item}”")
        rnd = Round(action=f"Use the {item.name}", roll=None)
        ops = [{"op": "item_remove", "name": item.name, "qty": 1}]
        if item.power:
            ops.append({"op": "hp", "target": "player", "amount": item.power})
        rnd.changes += rules.apply(state, ops)
    if not fled:
        rnd.rolls += _enemies_attack(state, defending, rnd)
    return rnd


def _target(state: GameState, ref: str | None) -> GameEnemy:
    if not ref:
        return state.enemies[0]
    enemy = rules.find_enemy(state, ref)
    if enemy is None:
        raise CombatError(f"There is no “{ref}” to attack")
    return enemy


def _enemies_attack(state: GameState, defending: bool, rnd: Round) -> list[CombatRoll]:
    rolls = []
    ac = player_ac(state, defending)
    for enemy in list(state.enemies):
        if state.player.hp <= 0:
            break
        roll = rules.draw_from(state.enemy_bag)
        hit = _strike(roll, roll + enemy.attack, ac)
        damage = max(1, enemy.damage + random.randint(-1, 1)) * (2 if roll == 20 else 1) if hit else 0
        rolls.append(CombatRoll(actor=enemy.name, target=state.player.name, roll=roll, bonus=enemy.attack,
                                total=roll + enemy.attack, against=ac, hit=hit, damage=damage, note=_note(roll)))
        if hit:
            rnd.changes += rules.apply(state, [{"op": "hp", "target": "player", "amount": -damage}])
    return rolls


def describe(rnd: Round, state: GameState) -> str:
    """The round as the game master reads it: final results to narrate."""
    lines = []
    for r in rnd.rolls:
        if r.target == "escape":
            lines.append(f"- {r.actor} tries to flee: {r.roll}+{r.bonus}={r.total} vs DC {r.against} → "
                         + ("ESCAPES" if r.hit else "FAILS, still cornered"))
        else:
            verdict = f"HIT for {r.damage} damage" if r.hit else "MISS"
            lines.append(f"- {r.actor} attacks {r.target}: {r.roll}+{r.bonus}={r.total} vs AC {r.against} → {verdict}"
                         + (f" ({r.note})" if r.note else ""))
    lines += [f"- {c.text}" for c in rnd.changes if not c.text.endswith("HP") or "Defeated" in c.text]
    left = ", ".join(f"{e.name} {e.hp}/{e.max_hp} HP" for e in state.enemies) or "none — the fight is over"
    lines.append(f"- Enemies left: {left}. {state.player.name}: {state.player.hp}/{state.player.max_hp} HP.")
    return "\n".join(lines)
