"""Pydantic mirror of ``apps/studio/src/api/contracts/workspace.ts`` (agent workspace: terminal, files,
browser, background tasks, plans and tool displays). Routes: ``docs/api/workspace.md``."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

# ------------------------------ session workspace ------------------------------

PlanStatus = Literal["pending", "in_progress", "done"]


class PlanItem(BaseModel):
    text: str
    status: PlanStatus


class WorkspaceState(BaseModel):
    session_id: str
    root: str | None = None
    plan: list[PlanItem] = Field(default_factory=list)


class SetRootRequest(BaseModel):
    root: str


class FolderEntry(BaseModel):
    name: str
    path: str


class FolderListing(BaseModel):
    path: str
    parent: str | None = None
    dirs: list[FolderEntry]


class MakeFolderRequest(BaseModel):
    parent: str
    name: str


# ----------------------------------- files -----------------------------------


class FsEntry(BaseModel):
    name: str
    path: str
    type: Literal["file", "dir"]
    size: int
    mtime: str


class FsListing(BaseModel):
    path: str
    entries: list[FsEntry]


class FsFile(BaseModel):
    path: str
    content: str
    size: int
    binary: bool
    truncated: bool


class WriteFileRequest(BaseModel):
    path: str
    content: str


class FsChange(BaseModel):
    type: Literal["added", "modified", "deleted"]
    path: str


class UploadResult(BaseModel):
    paths: list[str]


# --------------------------------- terminal ---------------------------------


class TerminalInfo(BaseModel):
    id: str
    session_id: str
    title: str
    cwd: str
    kind: Literal["shell", "command"]
    status: Literal["running", "exited"]
    exit_code: int | None = None
    call_id: str | None = None
    created_at: str


class TerminalBuffer(BaseModel):
    terminal: TerminalInfo
    data: str
    seq: int


# ---------------------------------- browser ----------------------------------


class BrowserState(BaseModel):
    session_id: str
    open: bool
    url: str
    title: str
    takeover: bool
    width: int
    height: int


class ConsoleEntry(BaseModel):
    level: Literal["log", "info", "warning", "error", "debug"]
    text: str
    ts: str


class BrowserSnapshot(BaseModel):
    state: BrowserState
    console: list[ConsoleEntry]


class NavigateRequest(BaseModel):
    url: str


class HistoryRequest(BaseModel):
    action: Literal["back", "forward", "reload"]


class TakeoverRequest(BaseModel):
    on: bool


class MouseInput(BaseModel):
    type: Literal["mouse"]
    action: Literal["down", "up", "move"]
    x: float
    y: float
    button: Literal["left", "right", "middle"] | None = None
    click_count: int | None = None
    modifiers: int | None = None


class WheelInput(BaseModel):
    type: Literal["wheel"]
    x: float
    y: float
    dx: float
    dy: float


class KeyInput(BaseModel):
    type: Literal["key"]
    action: Literal["down", "up"]
    key: str = Field(max_length=40)
    code: str = Field(max_length=40)
    text: str | None = Field(None, max_length=8)
    modifiers: int | None = None


class TextInput(BaseModel):
    type: Literal["text"]
    text: str = Field(max_length=10_000)


BrowserInput = Annotated[Union[MouseInput, WheelInput, KeyInput, TextInput], Field(discriminator="type")]

# ----------------------------------- tasks -----------------------------------

TaskStatus = Literal["queued", "running", "waiting_approval", "succeeded", "failed", "cancelled"]


class AgentTask(BaseModel):
    id: str
    title: str
    prompt: str
    status: TaskStatus
    origin_session_id: str
    session_id: str
    plan: list[PlanItem] = Field(default_factory=list)
    result: str | None = None
    error: str | None = None
    attempts: int
    created_at: str
    updated_at: str
    finished_at: str | None = None


class CreateTaskRequest(BaseModel):
    origin_session_id: str
    prompt: str = Field(min_length=1, max_length=12_000)
    title: str | None = Field(None, max_length=160)


# ------------------------------- tool displays -------------------------------


class TerminalDisplay(BaseModel):
    kind: Literal["terminal"] = "terminal"
    terminal_id: str
    command: str
    cwd: str
    excerpt: str
    status: Literal["running", "exited", "background"]
    exit_code: int | None = None


class DiffDisplay(BaseModel):
    kind: Literal["diff"] = "diff"
    path: str
    diff: str
    added: int
    removed: int
    created: bool


class FileDisplay(BaseModel):
    kind: Literal["file"] = "file"
    path: str
    excerpt: str
    lines: int
    total_lines: int


class FileItem(BaseModel):
    path: str
    line: int | None = None
    text: str | None = None
    dir: bool | None = None


class FilesDisplay(BaseModel):
    kind: Literal["files"] = "files"
    query: str
    items: list[FileItem]
    truncated: bool


class BrowserDisplay(BaseModel):
    kind: Literal["browser"] = "browser"
    action: str
    url: str
    title: str
    screenshot: str | None = None


class PlanDisplay(BaseModel):
    kind: Literal["plan"] = "plan"
    items: list[PlanItem]


class TaskDisplay(BaseModel):
    kind: Literal["task"] = "task"
    task_id: str
    title: str


class SourceItem(BaseModel):
    n: int
    title: str
    url: str
    snippet: str | None = None


class SourcesDisplay(BaseModel):
    """Web search results or the pages a research call read; ``n`` is the number the answer cites as [n]."""

    kind: Literal["sources"] = "sources"
    query: str
    items: list[SourceItem]


class ImageDisplay(BaseModel):
    kind: Literal["image"] = "image"
    url: str
    question: str | None = None


class QuestionDisplay(BaseModel):
    kind: Literal["question"] = "question"
    question: str
    options: list[str]
    answer: str | None = None


class FileArtifact(BaseModel):
    """A file a tool created or changed: ``url`` downloads it (outputs folder or the chat's workspace)."""

    name: str
    path: str  # absolute on this PC
    url: str | None = None
    size: int


class TableData(BaseModel):
    columns: list[str]
    rows: list[list[str]]
    total_rows: int  # rows in the whole table (``rows`` holds the first ones)


class PythonDisplay(BaseModel):
    """``run_python``: the code, what it printed, the value of its last expression, charts, a table and files."""

    kind: Literal["python"] = "python"
    code: str
    output: str = ""
    error: str | None = None
    images: list[str] = Field(default_factory=list)
    table: TableData | None = None
    files: list[FileArtifact] = Field(default_factory=list)


class WeatherDay(BaseModel):
    date: str  # YYYY-MM-DD
    code: int  # WMO weather code
    summary: str
    t_max: float
    t_min: float
    precip_mm: float
    precip_chance: int | None = None


class WeatherDisplay(BaseModel):
    kind: Literal["weather"] = "weather"
    location: str
    timezone: str
    units: Literal["metric", "imperial"]
    temp: float
    feels_like: float
    code: int
    summary: str
    humidity: int
    wind: float
    is_day: bool
    days: list[WeatherDay]
    source: str = "Open-Meteo"


class CalcDisplay(BaseModel):
    kind: Literal["calc"] = "calc"
    expression: str
    result: str


class ConversionDisplay(BaseModel):
    kind: Literal["conversion"] = "conversion"
    value: float
    from_unit: str
    to_unit: str
    result: float
    category: str  # length, mass, currency, ...
    note: str | None = None  # e.g. the exchange rate's date


class ClockItem(BaseModel):
    location: str
    timezone: str


class ClockDisplay(BaseModel):
    """World clocks; the UI keeps them ticking."""

    kind: Literal["clock"] = "clock"
    clocks: list[ClockItem]


class AutomationDisplay(BaseModel):
    kind: Literal["automation"] = "automation"
    automation_id: str
    title: str
    schedule: str  # human-readable
    next_run: str | None = None


ToolDisplay = Annotated[
    Union[TerminalDisplay, DiffDisplay, FileDisplay, FilesDisplay, BrowserDisplay, PlanDisplay, TaskDisplay,
          SourcesDisplay, ImageDisplay, QuestionDisplay, PythonDisplay, WeatherDisplay, CalcDisplay,
          ConversionDisplay, ClockDisplay, AutomationDisplay],
    Field(discriminator="kind"),
]

# ------------------------------ WebSocket frames ------------------------------


class EvWorkspaceUpdate(BaseModel):
    type: Literal["workspace.update"] = "workspace.update"
    state: WorkspaceState


class EvTerminalUpdate(BaseModel):
    type: Literal["terminal.update"] = "terminal.update"
    terminal: TerminalInfo


class EvTerminalOutput(BaseModel):
    type: Literal["terminal.output"] = "terminal.output"
    id: str
    data: str
    seq: int


class EvTerminalExit(BaseModel):
    type: Literal["terminal.exit"] = "terminal.exit"
    id: str
    code: int


class EvTerminalClosed(BaseModel):
    type: Literal["terminal.closed"] = "terminal.closed"
    id: str


class EvFsChange(BaseModel):
    type: Literal["fs.change"] = "fs.change"
    session_ids: list[str]
    changes: list[FsChange]


class EvBrowserUpdate(BaseModel):
    type: Literal["browser.update"] = "browser.update"
    state: BrowserState


class EvBrowserFrame(BaseModel):
    type: Literal["browser.frame"] = "browser.frame"
    session_id: str
    data: str
    width: int
    height: int


class EvBrowserConsole(BaseModel):
    type: Literal["browser.console"] = "browser.console"
    session_id: str
    entry: ConsoleEntry


class EvTaskUpdate(BaseModel):
    type: Literal["task.update"] = "task.update"
    task: AgentTask


class EvTaskRemoved(BaseModel):
    type: Literal["task.removed"] = "task.removed"
    id: str


WORKSPACE_SERVER_EVENTS = (EvWorkspaceUpdate, EvTerminalUpdate, EvTerminalOutput, EvTerminalExit, EvTerminalClosed,
                           EvFsChange, EvBrowserUpdate, EvBrowserFrame, EvBrowserConsole, EvTaskUpdate, EvTaskRemoved)


class TerminalOpenMessage(BaseModel):
    type: Literal["terminal.open"]
    session_id: str
    cols: int | None = Field(None, ge=10, le=500)
    rows: int | None = Field(None, ge=4, le=300)
    ref: str | None = None


class TerminalInputMessage(BaseModel):
    type: Literal["terminal.input"]
    id: str
    data: str = Field(max_length=100_000)
    ref: str | None = None


class TerminalResizeMessage(BaseModel):
    type: Literal["terminal.resize"]
    id: str
    cols: int = Field(ge=10, le=500)
    rows: int = Field(ge=4, le=300)
    ref: str | None = None


class TerminalCloseMessage(BaseModel):
    type: Literal["terminal.close"]
    id: str
    ref: str | None = None


class BrowserWatchMessage(BaseModel):
    type: Literal["browser.watch"]
    session_id: str
    watching: bool
    ref: str | None = None


class BrowserInputMessage(BaseModel):
    type: Literal["browser.input"]
    session_id: str
    input: BrowserInput
    ref: str | None = None


WorkspaceClientMessage = Union[TerminalOpenMessage, TerminalInputMessage, TerminalResizeMessage, TerminalCloseMessage,
                               BrowserWatchMessage, BrowserInputMessage]
WORKSPACE_CLIENT_TYPES = ("terminal.open", "terminal.input", "terminal.resize", "terminal.close", "browser.watch",
                          "browser.input")
