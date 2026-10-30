"""Swarm: a group of agents with roles working on one goal (``/api/swarms``); mirrored by
``apps/studio/src/api/contracts/swarm.ts``. See ``studio/swarm/`` and ``docs/api/swarm.md``."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# draft: set up, never started · running: the controller dispatches work · paused: running work finishes, nothing new
# starts · stopped: everything was stopped by the owner or a limit · done: the lead judged the goal reached
SwarmStatus = Literal["draft", "running", "paused", "stopped", "done"]
# lead: owns the goal, plans milestones and tasks, never does the work · worker: one task per session, hands off a
# report · inspector: checks a result against its acceptance criteria in a clean session
SwarmRole = Literal["lead", "worker", "inspector"]
SwarmAgentState = Literal["idle", "working", "reviewing", "planning", "paused", "dismissed"]
SwarmItemKind = Literal["milestone", "task"]
# open: waiting to be picked up (or reworked after a rejection) · running: a worker is on it · review: handed off,
# waiting for (or under) an inspector's check · accepted · failed: gave up after repeated failures · cancelled
SwarmItemStatus = Literal["open", "running", "review", "accepted", "failed", "cancelled"]
# What a tool may do in a swarm, where nobody is there to approve it: run, be refused, or be refused with a request
# to the owner filed in the inbox (the agent carries on either way)
ToolRule = Literal["allow", "ask", "deny"]
InboxKind = Literal["question", "permission"]
InboxStatus = Literal["open", "answered", "allowed", "denied", "dismissed"]


class SwarmHandoff(BaseModel):
    """A worker's report on its task, kept as written (the lead reads it verbatim)."""

    summary: str  # what was done
    not_done: str | None = None
    deviations: str | None = None
    concerns: str | None = None
    findings: str | None = None
    follow_ups: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    agent_id: str
    at: str


class SwarmCheck(BaseModel):
    criterion: str
    passed: bool
    evidence: str


class SwarmReview(BaseModel):
    """An inspector's verdict on a task or milestone."""

    accepted: bool
    summary: str
    checks: list[SwarmCheck] = Field(default_factory=list)
    agent_id: str
    at: str


class SwarmItem(BaseModel):
    id: str
    swarm_id: str
    parent_id: str | None = None  # the milestone a task belongs to
    kind: SwarmItemKind
    title: str
    spec: str
    acceptance: list[str]  # what has to be true for it to be accepted, written before the work starts
    status: SwarmItemStatus
    priority: int = 2  # 1 high, 2 normal, 3 low
    blocked_by: list[str] = Field(default_factory=list)  # items that must be accepted first
    assign_to: str | None = None  # an agent id the lead asked for
    owner_agent_id: str | None = None  # who is working on it, or last did
    attempts: int = 0  # sessions started on it (a rejection counts as one)
    rejections: int = 0
    handoff: SwarmHandoff | None = None
    review: SwarmReview | None = None
    session_ids: list[str] = Field(default_factory=list)  # every session that worked on or checked it, oldest first
    cost: float = 0.0  # USD spent on it (cloud models that report cost)
    created_by: str  # agent id, or "owner"
    created_at: str
    updated_at: str


class SwarmAgent(BaseModel):
    id: str
    swarm_id: str
    name: str
    role: SwarmRole
    model: str  # chat model id ("<provider>:<model>")
    purpose: str = ""  # what it is for and good at, in the owner's words; the lead assigns work by it
    state: SwarmAgentState = "idle"
    item_id: str | None = None  # the item it is on
    session_id: str | None = None  # its current session
    accepted: int = 0
    rejected: int = 0
    failed: int = 0
    cost: float = 0.0
    notes: str = ""  # its own notes, carried into every session
    last_active: str | None = None


class SwarmEvent(BaseModel):
    """One line of the swarm's history."""

    seq: int
    swarm_id: str
    at: str
    kind: str  # started, planned, assigned, handed_off, accepted, rejected, failed, stalled, asked, owner, report, …
    text: str
    agent_id: str | None = None
    item_id: str | None = None


class SwarmInboxEntry(BaseModel):
    """Something an agent needs from the owner: an answer, or permission for a tool the swarm's rules hold back."""

    id: str
    swarm_id: str
    kind: InboxKind
    agent_id: str
    item_id: str | None = None
    text: str  # the question, or why the agent wants the tool
    options: list[str] = Field(default_factory=list)
    tool: str | None = None  # permission: the tool and the call that was refused
    args: dict[str, object] | None = None
    status: InboxStatus = "open"
    answer: str | None = None
    created_at: str
    resolved_at: str | None = None


class Swarm(BaseModel):
    id: str
    name: str
    goal: str  # the charter: what to achieve, what counts as reached, what is out of scope
    folder: str  # the workspace every agent works in
    status: SwarmStatus
    status_reason: str | None = None  # why it paused or stopped by itself
    max_parallel: int = 3  # sessions at a time (the lead's included); local models run one at a time regardless
    daily_budget: float | None = None  # USD per day; None = no limit
    item_budget: float | None = None  # USD per work item; None = no limit
    rules: dict[str, ToolRule] = Field(default_factory=dict)  # per tool, overriding the defaults
    # The Foundress builds the team: it hires workers and inspectors (on any model it finds) and dismisses them
    hiring: bool = False
    max_agents: int = 8  # workers and inspectors at once, when the Foundress hires
    max_price: float | None = None  # USD per million input tokens, the most a hired agent's model may cost
    report: str | None = None  # the lead's latest report to the owner
    report_at: str | None = None
    spent_today: float = 0.0
    spent_total: float = 0.0
    spent_last_hour: float = 0.0  # what its sessions cost in the last 60 minutes: the current rate
    created_at: str
    updated_at: str


class SwarmDetail(BaseModel):
    """``GET /api/swarms/{id}``: everything the swarm page shows."""

    swarm: Swarm
    agents: list[SwarmAgent]
    items: list[SwarmItem]
    inbox: list[SwarmInboxEntry]
    events: list[SwarmEvent]  # the most recent, oldest first
    default_rules: dict[str, ToolRule]  # what applies to a tool the swarm has no rule for


class SwarmAgentSpec(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    role: SwarmRole
    model: str = Field(min_length=3)
    purpose: str = Field("", max_length=600)


class SwarmCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    goal: str = Field(min_length=10, max_length=8000)
    folder: str
    agents: list[SwarmAgentSpec] = Field(min_length=1, max_length=100)
    max_parallel: int = Field(3, ge=1, le=100)
    daily_budget: float | None = Field(None, ge=0)
    item_budget: float | None = Field(None, ge=0)
    rules: dict[str, ToolRule] = Field(default_factory=dict)
    hiring: bool = False
    max_agents: int = Field(8, ge=1, le=100)
    max_price: float | None = Field(None, ge=0)


class SwarmUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    goal: str | None = Field(None, min_length=10, max_length=8000)
    max_parallel: int | None = Field(None, ge=1, le=100)
    daily_budget: float | None = Field(None, ge=0)
    item_budget: float | None = Field(None, ge=0)
    rules: dict[str, ToolRule] | None = None
    hiring: bool | None = None
    max_agents: int | None = Field(None, ge=1, le=100)
    max_price: float | None = Field(None, ge=0)
    clear_daily_budget: bool = False  # set daily_budget back to no limit
    clear_item_budget: bool = False
    clear_max_price: bool = False


class SwarmAgentUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=40)
    model: str | None = Field(None, min_length=3)
    purpose: str | None = Field(None, max_length=600)


class SwarmMessage(BaseModel):
    """``POST /api/swarms/{id}/message``: the owner steers; the lead reads it at its next planning."""

    text: str = Field(min_length=1, max_length=4000)


class SwarmInboxReply(BaseModel):
    """Answer a question, or decide a permission request (``allow`` sets the tool's rule to allow for this swarm)."""

    action: Literal["answer", "allow", "deny", "dismiss"]
    answer: str | None = Field(None, max_length=4000)


class EvSwarmUpdate(BaseModel):
    type: Literal["swarm.update"] = "swarm.update"
    swarm: Swarm


class EvSwarmRemoved(BaseModel):
    type: Literal["swarm.removed"] = "swarm.removed"
    id: str


class EvSwarmAgent(BaseModel):
    type: Literal["swarm.agent"] = "swarm.agent"
    agent: SwarmAgent


class EvSwarmItem(BaseModel):
    type: Literal["swarm.item"] = "swarm.item"
    item: SwarmItem


class EvSwarmInbox(BaseModel):
    type: Literal["swarm.inbox"] = "swarm.inbox"
    entry: SwarmInboxEntry


class EvSwarmEvent(BaseModel):
    type: Literal["swarm.event"] = "swarm.event"
    event: SwarmEvent


SWARM_SERVER_EVENTS = (EvSwarmUpdate, EvSwarmRemoved, EvSwarmAgent, EvSwarmItem, EvSwarmInbox, EvSwarmEvent)
