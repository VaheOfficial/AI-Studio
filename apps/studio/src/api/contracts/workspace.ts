/**
 * Agent workspace (OpenMuse port): terminal, files, browser, background tasks, plans and tool displays.
 * Mirrored by server/studio/schemas_workspace.py; routes are listed in docs/api/workspace.md.
 */

/* ------------------------------ session workspace ------------------------------ */

export interface PlanItem {
  text: string
  status: 'pending' | 'in_progress' | 'done'
}

/** Per chat session: the folder the agent works in and its current plan (`update_plan`). */
export interface WorkspaceState {
  session_id: string
  /** Absolute folder chosen by the user; absent until one is picked (file/terminal tools refuse to run). */
  root?: string
  plan: PlanItem[]
}

/** One level of the server-side folder picker. `path` is empty for the list of drives. */
export interface FolderListing {
  path: string
  parent?: string
  dirs: { name: string; path: string }[]
}

/* ----------------------------------- files ----------------------------------- */

export interface FsEntry {
  name: string
  /** Relative to the workspace root, '/'-separated. */
  path: string
  type: 'file' | 'dir'
  size: number
  mtime: string
}

export interface FsListing {
  path: string
  entries: FsEntry[]
}

export interface FsFile {
  path: string
  content: string
  size: number
  /** Not UTF-8 text: `content` is empty. */
  binary: boolean
  /** Larger than the viewer limit: `content` holds the beginning only and the file is read-only. */
  truncated: boolean
}

export interface FsChange {
  type: 'added' | 'modified' | 'deleted'
  /** Relative to the root, '/'-separated. */
  path: string
}

/* --------------------------------- terminal --------------------------------- */

export interface TerminalInfo {
  id: string
  session_id: string
  title: string
  cwd: string
  /** `shell`: an interactive shell the user opened; `command`: a command the agent ran. */
  kind: 'shell' | 'command'
  status: 'running' | 'exited'
  exit_code?: number
  /** The agent tool call that started it. */
  call_id?: string
  created_at: string
}

/** A terminal plus its scrollback; `seq` is the output offset at the end of `data`. */
export interface TerminalBuffer {
  terminal: TerminalInfo
  data: string
  seq: number
}

/* ---------------------------------- browser ---------------------------------- */

export interface BrowserState {
  session_id: string
  open: boolean
  url: string
  title: string
  /** The user controls the page; agent browser tools refuse to act until it is handed back. */
  takeover: boolean
  width: number
  height: number
}

export interface ConsoleEntry {
  level: 'log' | 'info' | 'warning' | 'error' | 'debug'
  text: string
  ts: string
}

export interface BrowserSnapshot {
  state: BrowserState
  console: ConsoleEntry[]
}

/** Takeover input in page (CSS pixel) coordinates. `modifiers`: CDP bit mask (Alt 1, Ctrl 2, Meta 4, Shift 8). */
export type BrowserInput =
  | {
      type: 'mouse'
      action: 'down' | 'up' | 'move'
      x: number
      y: number
      button?: 'left' | 'right' | 'middle'
      click_count?: number
      modifiers?: number
    }
  | { type: 'wheel'; x: number; y: number; dx: number; dy: number }
  | { type: 'key'; action: 'down' | 'up'; key: string; code: string; text?: string; modifiers?: number }
  | { type: 'text'; text: string }

/* ----------------------------------- tasks ----------------------------------- */

export type TaskStatus = 'queued' | 'running' | 'waiting_approval' | 'succeeded' | 'failed' | 'cancelled'

/** A durable background agent run. It runs as a turn in its own chat session (`session_id`). */
export interface AgentTask {
  id: string
  title: string
  prompt: string
  status: TaskStatus
  /** Chat the task was started from (its workspace folder is reused). */
  origin_session_id: string
  session_id: string
  plan: PlanItem[]
  result?: string
  error?: string
  attempts: number
  created_at: string
  updated_at: string
  finished_at?: string
}

export interface CreateTaskRequest {
  origin_session_id: string
  prompt: string
  title?: string
}

/* ------------------------------- tool displays ------------------------------- */

/** Typed render data attached to a tool call (`ToolCall.display`) so the UI can draw a rich card. */
export type ToolDisplay =
  | {
      kind: 'terminal'
      terminal_id: string
      command: string
      cwd: string
      /** Tail of the ANSI-stripped output. */
      excerpt: string
      status: 'running' | 'exited' | 'background'
      exit_code?: number
    }
  | { kind: 'diff'; path: string; diff: string; added: number; removed: number; created: boolean }
  | { kind: 'file'; path: string; excerpt: string; lines: number; total_lines: number }
  | {
      kind: 'files'
      query: string
      items: { path: string; line?: number; text?: string; dir?: boolean }[]
      truncated: boolean
    }
  | { kind: 'browser'; action: string; url: string; title: string; screenshot?: string }
  | { kind: 'plan'; items: PlanItem[] }
  | { kind: 'task'; task_id: string; title: string }
  /** Web search results or the pages a research call read; `n` is the number the answer cites as [n]. */
  | { kind: 'sources'; query: string; items: SourceItem[] }
  /** An image the agent looked at (attachment, screenshot, generated or downloaded picture). */
  | { kind: 'image'; url: string; question?: string }
  /** An `ask_user` question: pick an option or answer in your own words; `answer` once answered. */
  | { kind: 'question'; question: string; options: string[]; answer?: string }
  /** `run_python`: the code, what it printed, its last value, charts (image URLs), a table and files it made. */
  | { kind: 'python'; code: string; output: string; error?: string; images: string[]; table?: TableData; files: FileArtifact[] }
  | WeatherDisplay
  | { kind: 'calc'; expression: string; result: string }
  /** Unit or currency conversion; `note` e.g. the exchange rate's date. */
  | { kind: 'conversion'; value: number; from_unit: string; to_unit: string; result: number; category: string; note?: string }
  /** World clocks (IANA time zones); the UI keeps them ticking. */
  | { kind: 'clock'; clocks: { location: string; timezone: string }[] }
  /** An automation the agent created or changed. */
  | { kind: 'automation'; automation_id: string; title: string; schedule: string; next_run?: string }

/** A file a tool created or changed; `url` downloads it. */
export interface FileArtifact {
  name: string
  /** Absolute on this PC. */
  path: string
  url?: string
  size: number
}

export interface TableData {
  columns: string[]
  rows: string[][]
  /** Rows in the whole table (`rows` holds the first ones). */
  total_rows: number
}

export interface WeatherDisplay {
  kind: 'weather'
  location: string
  timezone: string
  units: 'metric' | 'imperial'
  temp: number
  feels_like: number
  /** WMO weather code. */
  code: number
  summary: string
  humidity: number
  wind: number
  is_day: boolean
  days: { date: string; code: number; summary: string; t_max: number; t_min: number; precip_mm: number; precip_chance?: number }[]
  source: string
}

export interface SourceItem {
  n: number
  title: string
  url: string
  snippet?: string
}

/* ------------------------------ WebSocket frames ------------------------------ */

/** Server → client frames of the workspace (part of `ServerEvent`). */
export type WorkspaceServerEvent =
  | { type: 'workspace.update'; state: WorkspaceState }
  | { type: 'terminal.update'; terminal: TerminalInfo }
  /** `seq` is the output offset where `data` starts. */
  | { type: 'terminal.output'; id: string; data: string; seq: number }
  | { type: 'terminal.exit'; id: string; code: number }
  | { type: 'terminal.closed'; id: string }
  | { type: 'fs.change'; session_ids: string[]; changes: FsChange[] }
  | { type: 'browser.update'; state: BrowserState }
  /** Live view JPEG (base64); only sent to clients watching that session's browser. */
  | { type: 'browser.frame'; session_id: string; data: string; width: number; height: number }
  | { type: 'browser.console'; session_id: string; entry: ConsoleEntry }
  | { type: 'task.update'; task: AgentTask }
  | { type: 'task.removed'; id: string }

/** Client → server frames of the workspace (part of `ClientMessage`). */
export type WorkspaceClientMessage =
  | { type: 'terminal.open'; session_id: string; cols?: number; rows?: number; ref?: string }
  | { type: 'terminal.input'; id: string; data: string; ref?: string }
  | { type: 'terminal.resize'; id: string; cols: number; rows: number; ref?: string }
  | { type: 'terminal.close'; id: string; ref?: string }
  | { type: 'browser.watch'; session_id: string; watching: boolean; ref?: string }
  | { type: 'browser.input'; session_id: string; input: BrowserInput; ref?: string }
