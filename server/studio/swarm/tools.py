"""The swarm's side of the agent: the tools only its agents have (``ledger``, ``plan_items``, ``hand_off``,
``verdict``, ``ask_owner``, ``note``, ``goal_reached``), which of the normal tools each role gets, and the rules for
tools that would wait for the user's approval in a normal chat. ``profile`` builds what the turn loop applies to a
swarm agent's session (see ``agent/profiles.py``)."""

from __future__ import annotations

from typing import Any

from .. import connectors, db, openrouter_catalog
from ..agent import prompt as agent_prompt
from ..agent.profiles import Profile
from ..agent.providers import list_chat_models
from ..openrouter import OpenRouterError
from ..agent.types import ToolContext, ToolFailure, ToolOutcome, ToolSpec
from ..schemas_swarm import (SwarmAgent, SwarmAgentSpec, SwarmCheck, SwarmHandoff, SwarmInboxEntry, SwarmItem,
                             SwarmReview, ToolRule)
from . import briefs, manage, store
from .controller import controller

NOTES_LIMIT = 3000

# What a tool that would ask the user in a normal chat does in a swarm, unless the swarm has its own rule for it.
# Anything that runs code is held back until the owner allows it: there is no sandbox around it yet.
DEFAULT_RULES: dict[str, ToolRule] = {
    "write_file": "allow", "edit_file": "allow",
    "run_command": "ask", "start_process": "ask", "run_python": "ask",
    "browser_click": "allow", "browser_type": "ask",
}
CONNECTOR_RULE: ToolRule = "ask"

# Each role gets only the tools its work needs: every tool's description goes out with every request, so the
# studio's other tools (voices, music, model management, automations) would only add cost. The lead plans and reads;
# it never changes the folder or runs code.
READING = {"list_dir", "read_file", "find_files", "search_files", "fetch_url", "browser_navigate", "browser_read",
           "browser_screenshot", "view_image", "memory", "calculate"}
RUNNING = {"run_command", "start_process", "read_process_output", "stop_process", "run_python", "reset_python",
           "read_skill", "browser_click", "browser_type"}
WORKING = READING | RUNNING | {"write_file", "edit_file", "update_plan", "generate_image", "edit_image"}


def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


_S = {"type": "string"}
_LIST = {"type": "array", "items": {"type": "string"}}

LEDGER = ToolSpec("ledger", "Read the swarm's ledger: 'overview' lists every milestone and task with its id and "
                  "status; 'item' gives one item in full (spec, acceptance criteria, the worker's report, the "
                  "inspector's verdict).",
                  _obj({"view": {"type": "string", "enum": ["overview", "item"]}, "item_id": _S}))
PLAN = ToolSpec("plan_items", "Add or change milestones and tasks. Each entry is a new item, or a change to an "
                "existing one when it has `id` (only items not being worked on; changing a failed item reopens it). "
                "New items can refer to each other in the same call by `ref`. `cancel` lists ids to drop.",
                _obj({"items": {"type": "array", "items": {"type": "object", "properties": {
                    "ref": {"type": "string", "description": "A short name for a new item, so other entries in "
                                                             "this call can use it as milestone or in after"},
                    "id": {"type": "string", "description": "An existing item to change"},
                    "kind": {"type": "string", "enum": ["milestone", "task"]},
                    "title": _S,
                    "spec": {"type": "string", "description": "Everything needed to do it without seeing anything "
                                                              "else"},
                    "acceptance": {**_LIST, "description": "Checkable statements that are true when it is done"},
                    "milestone": {"type": "string", "description": "A task's milestone: id or ref"},
                    "after": {**_LIST, "description": "Items (id or ref) that must be accepted first"},
                    "priority": {"type": "integer", "minimum": 1, "maximum": 3, "description": "1 high, 3 low"},
                    "assign_to": {"type": "string", "description": "The agent (name or id) best suited to it"},
                }}}, "cancel": _LIST}))
GOAL = ToolSpec("goal_reached", "Declare the swarm's goal reached: the swarm stops and tells the owner. Only when "
                "every part of the goal is done and accepted.", _obj({"summary": _S}, ["summary"]))
HAND_OFF = ToolSpec("hand_off", "Finish your task: report what you did. Call it once, at the end. An inspector "
                    "checks the work against the acceptance criteria.",
                    _obj({"summary": {"type": "string", "description": "What you did"},
                          "not_done": {"type": "string", "description": "What is not done, and why"},
                          "deviations": {"type": "string", "description": "Where you departed from the spec"},
                          "concerns": _S, "findings": {"type": "string", "description": "What others should know"},
                          "follow_ups": {**_LIST, "description": "Work you saw that someone should do"},
                          "files": {**_LIST, "description": "Files you created or changed"}}, ["summary"]))
VERDICT = ToolSpec("verdict", "Give your verdict on the work you checked. accepted only if every criterion holds.",
                   _obj({"accepted": {"type": "boolean"}, "summary": _S,
                         "checks": {"type": "array", "items": {"type": "object", "properties": {
                             "criterion": _S, "passed": {"type": "boolean"}, "evidence": _S},
                             "required": ["criterion", "passed", "evidence"]}}},
                        ["accepted", "summary", "checks"]))
ASK = ToolSpec("ask_owner", "Ask the swarm's owner something only they can answer. It goes to their inbox and you "
               "don't wait: carry on with what you can do; the answer reaches the Foundress.",
               _obj({"question": _S, "options": _LIST}, ["question"]))
NOTE = ToolSpec("note", "Keep a short fact for your own later sessions (each starts fresh).",
                _obj({"text": _S}, ["text"]))
FIND_MODELS = ToolSpec("find_models", "Look for models to hire agents on: the ones available here, and OpenRouter's "
                       "catalog (any of its models that can call tools). Shows each model's id, price per million "
                       "tokens (input / output) and context window. Search words match the id, name, maker and "
                       "description.",
                       _obj({"query": {"type": "string", "description": "e.g. 'claude', 'gpt', 'coder', 'qwen'; "
                                                                       "empty lists them all"},
                             "max_price": {"type": "number", "description": "USD per million input tokens"},
                             "sort": {"type": "string", "enum": ["price", "newest"],
                                      "description": "Default price, cheapest first"}}))
HIRE = ToolSpec("hire", "Add an agent to the swarm: a worker (does tasks) or an inspector (checks them), on a model "
                "from find_models. Give it a name and a purpose saying what it is for; you assign tasks by it.",
                _obj({"name": _S, "role": {"type": "string", "enum": ["worker", "inspector"]},
                      "model": {"type": "string", "description": "The model id exactly as find_models shows it"},
                      "purpose": _S}, ["name", "role", "model", "purpose"]))
DISMISS = ToolSpec("dismiss", "Take an idle agent off the team (it stays in the history). Idle agents cost "
                   "nothing; dismiss one to make room under the team limit or to replace a model that isn't "
                   "working out.", _obj({"agent": {"type": "string", "description": "Name or id"}, "reason": _S},
                                        ["agent", "reason"]))
HIRING = [FIND_MODELS, HIRE, DISMISS]

ROLE_TOOLS: dict[str, list[ToolSpec]] = {
    "lead": [LEDGER, PLAN, GOAL, ASK, NOTE],
    "worker": [LEDGER, HAND_OFF, ASK, NOTE],
    "inspector": [LEDGER, VERDICT, ASK, NOTE],
}
SPECS = [LEDGER, PLAN, GOAL, HAND_OFF, VERDICT, ASK, NOTE, *HIRING]


def _allowed(role: str, name: str) -> bool:
    if role == "lead":
        return name in READING
    if role == "inspector":
        return name in READING or name in RUNNING
    return name in WORKING or connectors.SEP in name


def rule_for(rules: dict[str, ToolRule], name: str) -> ToolRule | None:
    """The swarm's rule for a tool: its own, else the default; None for a tool that needs no approval anyway."""
    if name in rules:
        return rules[name]
    if name in DEFAULT_RULES:
        return DEFAULT_RULES[name]
    if connectors.SEP in name:
        return CONNECTOR_RULE
    return None


def profile(session_id: str) -> Profile | None:
    link = store.session_link(session_id)
    if link is None:
        return None
    swarm_id, agent_id, item_id, _purpose = link
    try:
        swarm = store.get_swarm(swarm_id)
        agent = store.get_agent(agent_id)
    except store.SwarmError:
        return None
    agents = store.list_agents(swarm_id)
    own_tools = [*ROLE_TOOLS[agent.role], *(HIRING if agent.role == "lead" and swarm.hiring else [])]
    own = {s.name for s in own_tools}

    def tools(specs: list[ToolSpec]) -> list[ToolSpec]:
        return [*(s for s in specs if _allowed(agent.role, s.name)), *own_tools]

    def gate(name: str, args: dict[str, Any], gated: bool) -> str | None:
        if name in own:
            return None
        if not _allowed(agent.role, name):
            return f"{name} is not available to the {briefs.ROLE_NAMES[agent.role]} in this swarm."
        rule = rule_for(store.get_swarm(swarm_id).rules, name)
        if rule == "allow" or (rule is None and not gated):
            return None
        if rule == "deny":
            return f"The swarm's rules don't allow {name}. Don't retry it; do without it."
        return _ask(name, args)

    def _ask(name: str, args: dict[str, Any]) -> str:
        if store.open_permission(swarm_id, name) is None:
            store.insert_entry(SwarmInboxEntry(
                id=store.new_id(), swarm_id=swarm_id, kind="permission", agent_id=agent_id, item_id=item_id,
                text=f"{agent.name} wants to use {name}.", tool=name, args=args, created_at=db.now_iso()))
            controller.notify_owner(swarm_id, f"{agent.name} needs your permission", f"To use {name}")
            store.add_event(swarm_id, "asked", f"wants permission for {name}", agent_id)
        return (f"Held back: {name} needs the owner's permission in this swarm, and they have been asked. Don't "
                "retry it. Carry on without it, and say in your report what you could not do because of it.")

    def system(info: Any) -> str:
        intro = (f"You are {agent.name}, an agent of a swarm in Grom AI Studio, an app on the owner's computer.")
        return agent_prompt.build_lean(session_id, info, agent.model, intro) + briefs.role_section(swarm, agent, agents)

    return Profile(prompt=system, tools=tools, gate=gate, observe=lambda event: controller.observe(session_id, event))


# ------------------------------ the tools ------------------------------


def _link(ctx: ToolContext) -> tuple[str, SwarmAgent, str | None]:
    link = store.session_link(ctx.session_id)
    if link is None:
        raise ToolFailure("This tool only works in a swarm agent's session")
    swarm_id, agent_id, item_id, _purpose = link
    return swarm_id, store.get_agent(agent_id), item_id


async def _ledger(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    swarm_id, _agent, item_id = _link(ctx)
    items, agents = store.list_items(swarm_id), store.list_agents(swarm_id)
    if a.get("view") == "item" or a.get("item_id"):
        wanted = a.get("item_id") or item_id
        item = next((i for i in items if i.id == wanted), None)
        if item is None:
            raise ToolFailure(f"No item '{wanted}' in this swarm")
        return ToolOutcome(True, briefs.item_detail(item, agents, items))
    return ToolOutcome(True, briefs.ledger_overview(items, agents))


def _resolve_agent(agents: list[SwarmAgent], who: str | None) -> str | None:
    if not who:
        return None
    w = who.strip().lower()
    match = next((x for x in agents if x.id == who or x.name.lower() == w), None)
    if match is None:
        raise ToolFailure(f"No agent '{who}' in this swarm (names: {', '.join(x.name for x in agents)})")
    if match.role != "worker":
        raise ToolFailure(f"{match.name} is not a worker; tasks go to workers")
    return match.id


async def _plan_items(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    swarm_id, agent, _ = _link(ctx)
    items = {i.id: i for i in store.list_items(swarm_id)}
    agents = store.list_agents(swarm_id)
    refs: dict[str, str] = {}
    entries = [e for e in a.get("items") or [] if isinstance(e, dict)]
    for e in entries:  # ids first, so entries can refer to items created later in the same call
        if not e.get("id") and e.get("ref"):
            refs[str(e["ref"])] = store.new_id(8)

    def ref(value: str | None, what: str) -> str | None:
        if not value:
            return None
        if value in refs:
            return refs[value]
        if value in items:
            return value
        raise ToolFailure(f"{what} '{value}' is neither an item id nor a ref in this call")

    # Everything is checked first and written after: a plan with one bad entry changes nothing
    done: list[str] = []
    inserts: list[SwarmItem] = []
    updates: list[tuple[str, dict[str, Any]]] = []
    now = db.now_iso()
    for e in entries:
        after = [x for x in (ref(v, "after") for v in e.get("after") or []) if x]
        if e.get("id"):
            old = items.get(e["id"])
            if old is None:
                raise ToolFailure(f"No item '{e['id']}' to change")
            if old.status in ("running", "review"):
                raise ToolFailure(f"[{old.id}] is being worked on or checked; change it when that is over")
            changes: dict[str, Any] = {}
            for key in ("title", "spec", "acceptance", "priority"):
                if e.get(key) is not None:
                    changes[key] = e[key]
            if e.get("after") is not None:
                changes["blocked_by"] = after
            if e.get("assign_to") is not None:
                changes["assign_to"] = _resolve_agent(agents, e["assign_to"])
            if e.get("milestone") is not None and old.kind == "task":
                changes["parent_id"] = ref(e["milestone"], "milestone")
            if old.status in ("failed", "cancelled", "accepted") and changes:
                changes.update(status="open", attempts=0, rejections=0)
            updates.append((old.id, changes))
            done.append(f"changed [{old.id}] {changes.get('title', old.title)}")
            continue
        kind = e.get("kind") or ("task" if e.get("milestone") else "milestone")
        title = (e.get("title") or "").strip()
        spec = (e.get("spec") or "").strip()
        acceptance = [str(c).strip() for c in e.get("acceptance") or [] if str(c).strip()]
        if not title or not spec or not acceptance:
            raise ToolFailure(f"Every new item needs a title, a spec and acceptance criteria (missing in "
                              f"'{title or e.get('ref') or '?'}')")
        parent = ref(e.get("milestone"), "milestone") if kind == "task" else None
        if kind == "task" and parent is None:
            raise ToolFailure(f"Task '{title}' needs its milestone (id or ref)")
        item = SwarmItem(id=refs.get(str(e.get("ref"))) or store.new_id(8), swarm_id=swarm_id, parent_id=parent,
                         kind=kind, title=title[:200], spec=spec, acceptance=acceptance, status="open",
                         priority=int(e.get("priority") or 2), blocked_by=after,
                         assign_to=_resolve_agent(agents, e.get("assign_to")), created_by=agent.id, created_at=now,
                         updated_at=now)
        inserts.append(item)
        done.append(f"added {kind} [{item.id}] {title}")
    cancel = [str(x) for x in a.get("cancel") or []]
    for item_id in cancel:
        if item_id not in items:
            raise ToolFailure(f"No item '{item_id}' to cancel")
    if not done and not cancel:
        raise ToolFailure("Nothing to do: give items to add or change, or ids to cancel")
    for item in inserts:
        store.insert_item(item)
    for item_id, changes in updates:
        store.update_item(item_id, **changes)
    for item_id in cancel:
        await controller.cancel_item(items[item_id])
        done.append(f"cancelled [{item_id}] {items[item_id].title}")
    store.add_event(swarm_id, "planned", "; ".join(done)[:1500], agent.id)
    controller.poke()
    return ToolOutcome(True, "\n".join(done))


async def _goal_reached(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    swarm_id, agent, _ = _link(ctx)
    controller.finish(swarm_id, agent.id, a["summary"])
    return ToolOutcome(True, "The swarm stops when this session ends. Write your final report to the owner.")


async def _hand_off(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    swarm_id, agent, item_id = _link(ctx)
    if item_id is None:
        raise ToolFailure("This session has no task to hand off")
    item = store.get_item(item_id)
    if item.status != "running" or item.owner_agent_id != agent.id:
        raise ToolFailure("Already handed off" if item.status == "review" else
                          f"Your task is no longer yours to hand off (it is {item.status})")
    handoff = SwarmHandoff(summary=a["summary"], not_done=a.get("not_done") or None,
                           deviations=a.get("deviations") or None, concerns=a.get("concerns") or None,
                           findings=a.get("findings") or None, follow_ups=list(a.get("follow_ups") or []),
                           files=list(a.get("files") or []), agent_id=agent.id, at=db.now_iso())
    controller.handed_off(item, agent, handoff)
    return ToolOutcome(True, "Handed off. Your task is done: stop now (one short closing line at most).")


async def _verdict(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    swarm_id, agent, item_id = _link(ctx)
    if item_id is None:
        raise ToolFailure("This session has nothing to check")
    item = store.get_item(item_id)
    if item.status != "review":
        raise ToolFailure(f"[{item.id}] is not waiting for a verdict (it is {item.status})")
    checks = [SwarmCheck(criterion=str(c.get("criterion", "")), passed=bool(c.get("passed")),
                         evidence=str(c.get("evidence", ""))) for c in a.get("checks") or [] if isinstance(c, dict)]
    accepted = bool(a["accepted"]) and all(c.passed for c in checks)
    review = SwarmReview(accepted=accepted, summary=a["summary"], checks=checks, agent_id=agent.id, at=db.now_iso())
    controller.reviewed(item, agent, review)
    return ToolOutcome(True, f"Verdict recorded: {'accepted' if accepted else 'rejected'}. Stop now.")


async def _ask_owner(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    swarm_id, agent, item_id = _link(ctx)
    store.insert_entry(SwarmInboxEntry(id=store.new_id(), swarm_id=swarm_id, kind="question", agent_id=agent.id,
                                       item_id=item_id, text=a["question"][:2000],
                                       options=[str(o) for o in a.get("options") or []][:8], created_at=db.now_iso()))
    store.add_event(swarm_id, "asked", f"asked the owner: {a['question'][:300]}", agent.id, item_id)
    controller.notify_owner(swarm_id, f"{agent.name} has a question", a["question"][:200])
    return ToolOutcome(True, "Sent to the owner's inbox. Don't wait for it: carry on with what you can do.")


async def _note(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    _swarm_id, agent, _ = _link(ctx)
    notes = (agent.notes + "\n- " + a["text"].strip()).strip()
    if len(notes) > NOTES_LIMIT:  # the oldest go first
        notes = notes[-NOTES_LIMIT:].split("\n", 1)[-1]
    store.update_agent(agent.id, notes=notes)
    return ToolOutcome(True, "Noted.")


def _price(m: Any, unit: str) -> float:
    return next((p.usd for p in m.prices if p.unit == unit), 0.0)


async def _find_models(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    swarm_id, _agent, _ = _link(ctx)
    swarm = store.get_swarm(swarm_id)
    words = (a.get("query") or "").lower().split()
    limits = [x for x in (a.get("max_price"), swarm.max_price) if x is not None]
    ceiling = min(limits) if limits else None
    lines = []
    here = [o for o in await list_chat_models() if o.available and o.tools and o.provider != "openrouter"]
    for o in here:
        if all(w in f"{o.id} {o.name}".lower() for w in words):
            lines.append(f"- {o.id} — {o.name} — on this machine or your own endpoint, no per-token cost"
                         + (f" — {o.context_length // 1000}K context" if o.context_length else ""))
    try:
        page = await openrouter_catalog.search(output="text", q=" ".join(words), tools=True,
                                               max_input_price=ceiling, sort=a.get("sort") or "price", limit=40)
        for m in page.models:
            if m.id.endswith(":batch"):  # answers hours later: no use to an agent working live
                continue
            context = f" — {m.context_length // 1000}K context" if m.context_length else ""
            lines.append(f"- openrouter:{m.id} — {m.name} — ${_price(m, 'input_mtok'):g} in / "
                         f"${_price(m, 'output_mtok'):g} out per million{context}")
        more = page.total - len(page.models)
        if more > 0:
            lines.append(f"({more} more match; narrow the search)")
    except OpenRouterError as exc:
        lines.append(f"(OpenRouter's catalog is unavailable: {exc})")
    if not lines:
        raise ToolFailure("No model matches" + (f" under ${ceiling:g} per million input tokens" if ceiling else ""))
    head = f"Models you can hire on (at most ${ceiling:g} per million input tokens):" if ceiling else "Models:"
    return ToolOutcome(True, head + "\n" + "\n".join(lines))


async def _hire(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    swarm_id, agent, _ = _link(ctx)
    spec = SwarmAgentSpec(name=a["name"].strip()[:40] or "Agent", role=a["role"], model=a["model"].strip(),
                          purpose=(a.get("purpose") or "").strip()[:600])
    try:
        hired = await manage.hire(swarm_id, spec, agent.id)
    except store.SwarmError as exc:
        raise ToolFailure(str(exc)) from exc
    controller.poke()
    return ToolOutcome(True, f"Hired {hired.name} [{hired.id}] as {hired.role} on {hired.model}. Assign it work "
                             "with plan_items (assign_to).")


async def _dismiss(a: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    swarm_id, agent, _ = _link(ctx)
    if not store.get_swarm(swarm_id).hiring:
        raise ToolFailure("The owner builds this swarm's team; you can't dismiss agents")
    who = a["agent"].strip().lower()
    target = next((x for x in store.list_agents(swarm_id) if x.id == a["agent"] or x.name.lower() == who), None)
    if target is None:
        raise ToolFailure(f"No agent '{a['agent']}' on the team")
    try:
        manage.remove_agent(swarm_id, target.id, by=agent.id, reason=a.get("reason"))
    except store.SwarmError as exc:
        raise ToolFailure(str(exc)) from exc
    return ToolOutcome(True, f"Dismissed {target.name}.")


IMPL = {"ledger": _ledger, "plan_items": _plan_items, "goal_reached": _goal_reached, "hand_off": _hand_off,
        "verdict": _verdict, "ask_owner": _ask_owner, "note": _note, "find_models": _find_models, "hire": _hire,
        "dismiss": _dismiss}
