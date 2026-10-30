"""What the owner does to a swarm outside its sessions: create it, change it, its agents, and answer its inbox."""

from __future__ import annotations

from pathlib import Path

from .. import db, openrouter_catalog
from ..agent.providers import list_chat_models
from ..schemas_swarm import (Swarm, SwarmAgent, SwarmAgentSpec, SwarmAgentUpdate, SwarmCreate, SwarmDetail,
                             SwarmInboxEntry, SwarmInboxReply, SwarmUpdate)
from . import store, tools
from .controller import controller
from .store import SwarmError


def _folder(path: str) -> str:
    p = Path(path).expanduser()
    if not p.is_absolute():
        raise SwarmError("Choose an absolute folder path")
    p = p.resolve()
    if not p.is_dir():
        raise SwarmError(f"Folder does not exist: {p}")
    if p == Path(p.anchor):
        raise SwarmError("Choose a folder, not the root of a drive")
    return str(p)


def _check_roster(specs: list[SwarmAgentSpec], hiring: bool) -> None:
    leads = sum(1 for a in specs if a.role == "lead")
    if leads != 1:
        raise SwarmError("A swarm has exactly one lead (the Foundress)")
    if not hiring and not any(a.role == "worker" for a in specs):
        raise SwarmError("A swarm needs at least one worker, unless the Foundress builds the team")
    names = [a.name.strip().lower() for a in specs]
    if len(set(names)) != len(names):
        raise SwarmError("Every agent needs its own name")
    for a in specs:
        if ":" not in a.model:
            raise SwarmError(f"{a.name}: the model must be '<provider>:<model>'")


def _agent(swarm_id: str, spec: SwarmAgentSpec) -> SwarmAgent:
    return SwarmAgent(id=store.new_id(8), swarm_id=swarm_id, name=spec.name.strip(), role=spec.role,
                      model=spec.model, purpose=spec.purpose.strip())


def detail(swarm_id: str) -> SwarmDetail:
    return SwarmDetail(swarm=store.get_swarm(swarm_id), agents=store.list_agents(swarm_id, with_dismissed=True),
                       items=store.list_items(swarm_id), inbox=store.list_inbox(swarm_id),
                       events=store.recent_events(swarm_id), default_rules=tools.DEFAULT_RULES)


def create(req: SwarmCreate) -> SwarmDetail:
    _check_roster(req.agents, req.hiring)
    now = db.now_iso()
    s = Swarm(id=store.new_id(), name=req.name.strip(), goal=req.goal.strip(), folder=_folder(req.folder),
              status="draft", max_parallel=req.max_parallel, daily_budget=req.daily_budget,
              item_budget=req.item_budget, rules=req.rules, hiring=req.hiring, max_agents=req.max_agents,
              max_price=req.max_price, created_at=now, updated_at=now)
    store.insert_swarm(s)
    for spec in req.agents:
        store.insert_agent(_agent(s.id, spec))
    store.add_event(s.id, "created", f"created with {len(req.agents)} agents")
    return detail(s.id)


def update(swarm_id: str, req: SwarmUpdate) -> Swarm:
    store.get_swarm(swarm_id)
    changes = req.model_dump(exclude_unset=True, exclude={"clear_daily_budget", "clear_item_budget",
                                                          "clear_max_price"})
    changes = {k: v for k, v in changes.items() if v is not None}
    if req.clear_daily_budget:
        changes["daily_budget"] = None
    if req.clear_item_budget:
        changes["item_budget"] = None
    if req.clear_max_price:
        changes["max_price"] = None
    if changes.get("hiring") is False and not any(a.role == "worker" for a in store.list_agents(swarm_id)):
        raise SwarmError("Add a worker before taking hiring away from the Foundress")
    s = store.update_swarm(swarm_id, **changes) if changes else store.get_swarm(swarm_id)
    if "goal" in changes:
        store.add_event(swarm_id, "owner", "The owner changed the goal")
        store.add_wake(swarm_id, "The owner changed the goal: re-read it and adjust the plan.")
    controller.poke()
    return s


def add_agent(swarm_id: str, spec: SwarmAgentSpec, by: str | None = None) -> SwarmAgent:
    """Add an agent; ``by``: the agent who hired it (the Foundress), None when the owner adds it."""
    current = store.list_agents(swarm_id, with_dismissed=True)
    roster = [SwarmAgentSpec(name=a.name, role=a.role, model=a.model, purpose=a.purpose) for a in current
              if a.state != "dismissed"]
    if spec.name.strip().lower() in {a.name.lower() for a in current}:
        raise SwarmError(f"There is already an agent called {spec.name.strip()} in this swarm")
    _check_roster([*roster, spec], True)
    agent = store.insert_agent(_agent(swarm_id, spec))
    if by is None:
        store.add_event(swarm_id, "roster", f"The owner added {agent.name} as {spec.role}", agent.id)
        store.add_wake(swarm_id, f"The owner added {agent.name} to the team as a {spec.role}.")
    controller.poke()
    return agent


def update_agent(swarm_id: str, agent_id: str, req: SwarmAgentUpdate) -> SwarmAgent:
    agent = store.get_agent(agent_id)
    if agent.swarm_id != swarm_id:
        raise SwarmError(f"No agent '{agent_id}' in this swarm")
    changes = {k: v for k, v in req.model_dump(exclude_unset=True).items() if v is not None}
    if "model" in changes and ":" not in changes["model"]:
        raise SwarmError("The model must be '<provider>:<model>'")
    if "name" in changes and any(a.name.lower() == changes["name"].strip().lower() and a.id != agent_id
                                 for a in store.list_agents(swarm_id, with_dismissed=True)):
        raise SwarmError("Every agent needs its own name")
    return store.update_agent(agent_id, **changes) if changes else agent


def remove_agent(swarm_id: str, agent_id: str, by: str | None = None, reason: str | None = None) -> SwarmAgent:
    """Dismiss an agent: it takes no more work, and stays on record so the history keeps its name. ``by``: the
    agent who decided (the Foundress), None for the owner."""
    agent = store.get_agent(agent_id)
    if agent.swarm_id != swarm_id or agent.state == "dismissed":
        raise SwarmError(f"No agent '{agent_id}' in this swarm")
    if agent.role == "lead":
        raise SwarmError("The lead can't be dismissed; change its model instead")
    if agent.state != "idle":
        raise SwarmError(f"{agent.name} is busy; dismiss it when its session is over")
    swarm = store.get_swarm(swarm_id)
    if (agent.role == "worker" and not swarm.hiring
            and sum(1 for a in store.list_agents(swarm_id) if a.role == "worker") == 1):
        raise SwarmError("A swarm needs at least one worker")
    store.update_agent(agent_id, state="dismissed", item_id=None)
    who = "The Foundress" if by else "The owner"
    store.add_event(swarm_id, "roster", f"{who} dismissed {agent.name}" + (f": {reason}" if reason else ""), by)
    controller.poke()
    return store.get_agent(agent_id)


async def check_model(model: str, max_price: float | None = None) -> str:
    """A model an agent can run on: one that exists, takes tools, and (for a hire) costs no more than allowed.
    Returns a short description; raises SwarmError otherwise."""
    provider, _, name = model.partition(":")
    if provider == "openrouter":
        m = await openrouter_catalog.find(name)
        if m is None:
            raise SwarmError(f"OpenRouter has no model '{name}'")
        if name.endswith(":batch"):
            raise SwarmError(f"{m.name} is a batch endpoint that answers hours later; use the model without :batch")
        if not m.tools:
            raise SwarmError(f"{m.name} can't call tools, so it can't work in a swarm")
        price = next((p.usd for p in m.prices if p.unit == "input_mtok"), 0.0)
        if max_price is not None and price > max_price:
            raise SwarmError(f"{m.name} costs ${price:g} per million input tokens; this swarm allows at most "
                             f"${max_price:g}")
        return f"{m.name} (${price:g} in per million tokens)"
    option = next((o for o in await list_chat_models() if o.id == model), None)
    if option is None or not option.available:
        raise SwarmError(f"'{model}' is not a chat model that is available here")
    if not option.tools:
        raise SwarmError(f"{option.name} can't call tools, so it can't work in a swarm")
    return option.name


async def hire(swarm_id: str, spec: SwarmAgentSpec, by: str) -> SwarmAgent:
    """The Foundress adds a worker or an inspector, within the swarm's limits."""
    swarm = store.get_swarm(swarm_id)
    if not swarm.hiring:
        raise SwarmError("The owner builds this swarm's team; you can't hire")
    if spec.role == "lead":
        raise SwarmError("There is one Foundress: hire workers or inspectors")
    team = [a for a in store.list_agents(swarm_id) if a.role != "lead"]
    if len(team) >= swarm.max_agents:
        raise SwarmError(f"The team is full ({swarm.max_agents} agents, the owner's limit). Dismiss an idle agent "
                         "first, or ask the owner for a larger team.")
    described = await check_model(spec.model, swarm.max_price)
    agent = add_agent(swarm_id, spec, by)
    store.add_event(swarm_id, "roster", f"The Foundress hired {agent.name} as {spec.role} on {described}"
                    + (f": {spec.purpose}" if spec.purpose else ""), by)
    return agent


def reply(swarm_id: str, entry_id: str, req: SwarmInboxReply) -> SwarmInboxEntry:
    entry = store.get_entry(entry_id)
    if entry.swarm_id != swarm_id:
        raise SwarmError(f"No inbox entry '{entry_id}' in this swarm")
    if entry.status != "open":
        raise SwarmError("That was already dealt with")
    if req.action == "answer":
        if entry.kind != "question" or not (req.answer or "").strip():
            raise SwarmError("Write an answer to the question")
        done = store.resolve_entry(entry_id, "answered", req.answer.strip() if req.answer else None)
        store.add_event(swarm_id, "owner", f"The owner answered “{entry.text[:200]}”: {done.answer}")
        store.add_wake(swarm_id, f"The owner answered a question: “{entry.text[:300]}” → {done.answer}")
    elif req.action in ("allow", "deny"):
        if entry.kind != "permission" or not entry.tool:
            raise SwarmError("Only a permission request can be allowed or denied")
        rules = {**store.get_swarm(swarm_id).rules, entry.tool: req.action}
        store.update_swarm(swarm_id, rules=rules)
        done = store.resolve_entry(entry_id, "allowed" if req.action == "allow" else "denied", None)
        verb = "allowed" if req.action == "allow" else "refused"
        store.add_event(swarm_id, "owner", f"The owner {verb} {entry.tool} for the swarm")
        store.add_wake(swarm_id, f"The owner {verb} {entry.tool} for the swarm"
                       + (": work that needed it can be planned again." if req.action == "allow" else "."))
    else:
        done = store.resolve_entry(entry_id, "dismissed", None)
    controller.poke()
    return done
