# Agent workspace API

The chat's workspace (OpenMuse port): a folder on this machine chosen per chat, PTY terminals, file browsing and
editing, the agent's browser with live view and takeover, durable background tasks. Types:
[`apps/studio/src/api/contracts/workspace.ts`](../../apps/studio/src/api/contracts/workspace.ts) (mirrored by
`server/studio/schemas_workspace.py`).

## REST (`/api/workspace`)
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/sessions/{id}` | | `WorkspaceState` (folder + current plan) |
| PUT | `/sessions/{id}` | `{ root }` absolute folder | `WorkspaceState`; 400 if missing / a drive root |
| GET | `/browse?path=` | | `FolderListing` (empty path = home + drives) — server-side folder picker |
| POST | `/browse/mkdir` | `{ parent, name }` | `FolderListing` of the new folder |
| GET | `/sessions/{id}/fs?path=.` | | `FsListing` (409 when no folder is set) |
| GET | `/sessions/{id}/fs/file?path=` | | `FsFile` (≤1 MB shown; binary files flagged) |
| GET | `/sessions/{id}/fs/download?path=` | | the file as a download (`FileResponse`), e.g. documents the agent made |
| PUT | `/sessions/{id}/fs/file` | `{ path, content }` | `FsFile` (atomic write) |
| POST | `/sessions/{id}/upload` | multipart `files` (≤50 MB each) | `{ paths }` saved under `attachments/` |
| GET | `/sessions/{id}/terminals` | | `TerminalBuffer[]` (scrollback + `seq`) |
| GET | `/sessions/{id}/browser` | | `BrowserSnapshot` (state + console) |
| POST | `/sessions/{id}/browser/navigate` | `{ url }` | `BrowserState` |
| POST | `/sessions/{id}/browser/history` | `{ action: back\|forward\|reload }` | `BrowserState` |
| POST | `/sessions/{id}/browser/takeover` | `{ on }` | `BrowserState` |
| POST | `/sessions/{id}/browser/close` | | `204` |
| GET | `/tasks` | | `AgentTask[]` newest first |
| POST | `/tasks` | `CreateTaskRequest` | `AgentTask` (queued; runs in a new chat with the origin's folder) |
| POST | `/tasks/{id}/cancel` | | `AgentTask` |
| POST | `/tasks/{id}/retry` | | `AgentTask` (failed/cancelled only) |
| DELETE | `/tasks/{id}` | | `204` (stops it first if running) |

Deleting a chat (`DELETE /api/agent/sessions/{id}`) also closes its terminals and browser page, forgets its
folder setting and removes a task that ran in it.

## WebSocket (`/api/ws`)
Client → server (`WorkspaceClientMessage`): `terminal.open {session_id, cols?, rows?}`, `terminal.input {id, data}`,
`terminal.resize {id, cols, rows}`, `terminal.close {id}`, `browser.watch {session_id, watching}`,
`browser.input {session_id, input: BrowserInput}` (only while takeover is on). Problems come back as
`{type: "error", message, ref}`.

Server → client (`WorkspaceServerEvent`): `workspace.update`, `terminal.update`, `terminal.output {id, data, seq}`
(`seq` = offset where `data` starts, so live frames splice onto the REST scrollback), `terminal.exit`,
`terminal.closed`, `fs.change {session_ids, changes}` (watchfiles, debounced), `browser.update`,
`browser.frame` (CDP screencast JPEG, ≤10 fps, only to clients watching that session), `browser.console`,
`task.update`, `task.removed`.

Agent turns additionally stream `tool.progress {call_id, display}` and carry `display: ToolDisplay` on
`ToolCall`/`tool.result` (terminal excerpt, diff, file, file list, browser screenshot, plan, task).

## Agent tools (added to the studio tools, ⚠ = approval unless auto-approved in Settings)
- `list_dir`, `read_file(path, offset?, limit?)`, `find_files(pattern, path?)`, `search_files(pattern, path?, glob?,
  ignore_case?)` — inside the chat's folder only.
- ⚠ `write_file(path, content)`, ⚠ `edit_file(path, old_string, new_string, replace_all?)` — atomic, diff recorded.
- ⚠ `run_command(command, cwd?, timeout_s?)` — PowerShell 7 in a visible PTY; still running after `timeout_s`
  (default 120) → keeps running as a background process. ⚠ `start_process(command, cwd?)`,
  `read_process_output(process_id, wait_s?)`, `stop_process(process_id)`.
- `browser_navigate(url)`, ⚠ `browser_click(selector?|text?|x,y)`, ⚠ `browser_type(text, selector?, submit?)`,
  `browser_read(mode: text|snapshot)`, `browser_screenshot()` — refused while the user has taken control.
- `update_plan(items)`, `memory(action: read|append|replace, content?)` (notes per folder, injected into the
  system prompt), `start_task(prompt, title?)`.

## Runtime notes
- Terminals use ConPTY via `pywinpty`; commands run as `pwsh -NoProfile -EncodedCommand …` (falls back to Windows
  PowerShell). The browser is Playwright driving the installed Edge (then Chrome, then Playwright's Chromium) headless
  with a persistent profile in `data/browser/profile`; screenshots for tool cards are saved under
  `data/workspace/browser/<session>/` and served at `/files/workspace/browser/…`. Playwright needs the Proactor
  event loop: run uvicorn without `--reload` on Windows.
- Background tasks are rows in `workspace_tasks`; at most 2 run at once; on startup tasks left running are
  re-queued with a note to inspect before repeating work.
