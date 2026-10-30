# Arena

Games contains the 1v1 Arena and existing Adventures. `/game` links redirect to `/games/adventures`.

| Method | Route | Result |
|---|---|---|
| GET | `/api/arena` | Saved matches |
| POST | `/api/arena` | Create an `ArenaCreate`; no generation starts yet |
| GET | `/api/arena/{id}` | Current `ArenaMatch`, including live messages |
| POST | `/api/arena/{id}/control` | `start`, `pause`, `stop`, `step` with side, or `vote` with winner |
| POST | `/api/arena/{id}/interject` | `{text}` adds a host message |

`arena.update` pushes complete revisioned snapshots over the existing WebSocket. Reconnect fetches persisted/current state. Active matches become paused after server restart. JSON exports include settings, self-authored personas, messages and user verdicts.

Argument mode uses two independent provider streams with a bounded recent transcript. Free pacing permits simultaneous writing and reactions to unfinished rival text. Alternating pacing is optional. Paused argument matches support one selected reply. Limits are 1–20 replies per side and 15–1800 active seconds. Debate requests cap provider output at 2048 tokens; visible replies and prompts are additionally bounded. Runtime capacity may serialize local model requests.

Task mode creates two separate normal tool-using sessions. Existing discovery, capabilities and approvals apply; the arena links to each chat for tool results and approvals. Pausing cancels the active turns; resuming uses their persisted histories. Task interjections are match notes. The user chooses a winner; no automatic grading is claimed. Configured cloud models incur their normal usage, with completed OpenRouter debate requests recorded in the existing ledger.

When both contenders select the same built-in llama.cpp model, `inference:auto` tries two generation slots sharing one copy of the weights. Argument context requests 8192 tokens per slot; task context requests up to 32768, capped by the configured context setting. The launch uses continuous batching and a total context allocation of slots × context per slot. Single-slot MTP speculation is omitted for a two-slot launch. `/props` and `/slots` verify actual capacity after startup; the match displays its slot count, actual context and any fallback reason.

`inference:one` gates Arena generation sequentially. `inference:two` requires two slots and reports startup failure rather than falling back. Auto falls back to one after a failed two-slot startup, or uses the existing available capacity while another chat is active. Active chats are not restarted. Different built-in llama.cpp models run sequentially, because that runtime hosts one model at a time. Other providers manage their own native concurrency. Persistent ordinary-chat settings are unchanged. An idle Arena-owned load is released when the last match finishes or pauses; a later normal chat loads its ordinary configuration again. Active chats and unrelated model loads are preserved.

When native startup logs report that a two-slot fit moved model layers to CPU, Auto retries one slot. Explicit Two permits the runtime's CPU offload, while still requiring two verified slots. This uses reported layer offload rather than an unverified parameter-count or free-memory estimate; automatic fit may also reduce the requested context, which the UI reports.
