# Game API

Game mode is a text RPG with a chat model as game master. Types are in
[`apps/studio/src/api/contracts/game.ts`](../../apps/studio/src/api/contracts/game.ts) (mirrored by
`server/studio/schemas_game.py`).

The game's truth is the structured `GameState` the server keeps: player, inventory, location, quests, current
enemies, facts to remember, and the game's memory — a journal (`chronicle`, one line per turn written from the model's
`event`) plus a `summary` of everything before it. When the journal reaches 30 lines the model is asked to fold the
oldest 15 into the summary; they are dropped once it does. Each turn the model gets the state, summary, journal and
the last four turns (never the whole history) plus the player's action with a d20 roll. The d20 is a shuffle bag kept
in the state (`dice_bag`): rolls are drawn without replacement from 1-20, and the bag refills while 4 are still in
it (like the "New Year" card in Catan's dice deck), so luck evens out without the last draws being predictable. The
turn's saved state is from before the draw, so undo puts the die back. It narrates, then proposes
changes as JSON ops (`hp`, `gold`, `xp`, `item_add`, `enemy_add`, `quest`, `move`, …). The server validates and
applies them in `studio/game/rules.py`: HP is clamped, a level-up comes every 100 × level XP, an enemy at 0 HP is
defeated, a player at 0 HP dies. Malformed ops are skipped; a reply without readable JSON gets one repair request.

## Routes

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/games` | | `GameSummary[]` (newest first) |
| POST | `/api/games` | `NewGameRequest` | `Game` — the opening turn is already being written (`pending`) |
| GET | `/api/games/{id}` | | `Game` with all turns and the turn in progress, if any |
| PATCH | `/api/games/{id}` | `GamePatch` (`title`, `model`) | `Game` |
| POST | `/api/games/{id}/actions` | `{ action }` | `Game` with `pending` set; `409` while a turn is running or after the game ended |
| POST | `/api/games/{id}/combat` | `CombatRequest` (`kind`: attack / defend / flee / item, `target`, `item`) | `Game` with `pending` — the round is already settled by the rules; `400` when not possible (no enemies, unknown target) |
| POST | `/api/games/{id}/turns/{turn}/illustrate` | | `Job` — draws the turn's `scene` with the best local image model |
| POST | `/api/games/{id}/turns/{turn}/narrate` | | `Job` — reads the narration aloud (Kokoro "George" when installed) |
| POST | `/api/games/{id}/music` | | `Job` — a 60 s loop for the current location in the latest turn's `mood` (ACE-Step) |
| POST | `/api/games/{id}/stop` | | `Game` — cancels the running turn |
| POST | `/api/games/{id}/undo` | | `Game` — drops the last turn and restores the state before it (not the opening scene) |
| DELETE | `/api/games/{id}` | | `204` |

## Realtime

- `{ type: "game.delta", game_id, text }` — narration of the running turn as it is written; the UI appends it to
  `pending.narration`. The JSON block after the narration is never streamed.
- `{ type: "game.turn", game_id, turn, state }` — the finished turn and the new state; replaces `pending`.
- `{ type: "game.error", game_id, message }` — the turn failed or was stopped (`message: "Stopped"`); nothing changed.
- `{ type: "game.media", game_id, turn_id?, image?, audio?, location?, music?, error? }` — art or narration for a
  turn, or music for a location, finished (or failed: `error`). Media jobs also appear as ordinary `job.update`s.

## Combat

Enemies have `ac`, `attack`, `damage` and `xp` (the game master may set them; otherwise they scale with hit points).
A combat round is settled by `studio/game/combat.py` before the game master writes anything: the player's attack
(d20 from the dice bag + proficiency + the better of STR/DEX modifiers, against the enemy's AC; damage = weapon power
+ that modifier ± a little), defense (+4 AC this round), flee (d20 + DEX modifier + 2 against 12) or item, then every
enemy's attack from the enemies' own dice bag against the player's AC (10 + DEX modifier + equipped armor). A natural
20 always hits for double damage, a natural 1 always misses. Defeated enemies give their `xp`. The game master is
given the results as final and narrates them; its `hp`, `max_hp`, `xp` and `enemy_remove` ops are ignored that turn.
