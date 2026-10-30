> Historical scheduler reference. New team execution is retired. Use the unified [Agents API](agents.md) and import saved teams into sequential missions. Creation, start and other team mutations return 410; reads, stop controls and whole-team deletion remain available.

# Swarm API

Types: [`apps/studio/src/api/contracts/swarm.ts`](../../apps/studio/src/api/contracts/swarm.ts), mirrored by
`server/studio/schemas_swarm.py`. Routes: [`docs/API.md`](../API.md#swarm). Server: `server/studio/swarm/`
(`store.py` the ledger, `briefs.py` what agents are told, `tools.py` their tools and rules, `controller.py` the code
that runs it, `manage.py` the owner's changes).

A swarm is a group of named agents working on one goal by themselves, for as long as it runs. Plain code runs it;
the models plan, work and check.

## Roles

| Role | Does | Tools |
|---|---|---|
| `lead` (the Foundress, exactly one) | Turns the goal into milestones and tasks with acceptance criteria, reads every report and verdict, plans what follows, writes the owner's report. Never does the work. | Reading only (files, web, the browser's read tools), plus `ledger`, `plan_items`, `goal_reached`, `ask_owner`, `note`; with `hiring`, also `find_models`, `hire`, `dismiss` |
| `worker` (one or more) | One task per session, in the swarm's folder; ends with `hand_off` | Files, terminal, Python, the browser, the web, `view_image`, `generate_image`/`edit_image`, `update_plan`, `memory`, connectors, plus `ledger`, `hand_off`, `ask_owner`, `note` |
| `inspector` (any number) | Checks a handed-off task, or a milestone whose tasks were all accepted, against its acceptance criteria in a clean session; ends with `verdict` | Reading, running commands and Python, the browser, plus `ledger`, `verdict`, `ask_owner`, `note` |

### A Foundress that builds the team

With `hiring` on, the roster can be the Foundress alone. It gets three more tools: `find_models` (the chat models
ready here and every tool-capable model in OpenRouter's catalog, pinned or not, with prices and context windows;
batch-only endpoints are left out), `hire` (a worker or an inspector with a name, a model and a purpose) and
`dismiss` (an idle agent). It is told to hire for what the work needs, run several workers when tasks can go in
parallel, and check work with an inspector on another model family. `max_agents` caps the workers and inspectors at
once, `max_price` the input price per million tokens of a model it may hire. Agents the owner adds still join.

A dismissed agent (`state: dismissed`, by the owner or the Foundress) takes no more work and stays on record, so the
history keeps its name; its name is not reused. Idle agents cost nothing.

Each role gets only the tools its work needs (`tools.py`: `READING`, `RUNNING`, `WORKING`): every tool's
description is sent with every request, so the studio's other tools (questions to the user, background tasks,
automations, memory about the user, model management, voices, music, video) are left out.

Every session of an agent gets a short system prompt (`prompt.build_lean`: who and where it is, how to work, its
workspace; none of the studio assistant's map, model list, personality or style) plus a role section
(`briefs.role_section`): the swarm, the roster with what each agent has spent and how its work fared, the agent's own
notes, and what its role does and never does. A Foundress that hires is told to hire the cheapest model that does a
task well and keep premium models for what cheaper ones failed at. Each session starts with a brief written by
code from the ledger (`[Swarm “name”: …]`); agents never pass each other free-form instructions.

## Work items

A milestone holds tasks. Every item has a spec and acceptance criteria written before the work starts.

| Status | Means |
|---|---|
| `open` | Waiting to be picked up, or back for rework after a rejection |
| `running` | A worker is on it |
| `review` | Handed off; waiting for or under an inspector's check (a milestone: all its tasks accepted) |
| `accepted` | Checked and accepted (without inspectors, a handed-off task is accepted as it is) |
| `failed` | Given up: 3 failed attempts, 3 rejections, or 3 checks that gave no verdict. The Foundress is told. |
| `cancelled` | Dropped by the Foundress |

`blocked_by` holds items that must be accepted first; `assign_to` the worker the Foundress asked for (it waits for
them). A rejected task goes back to the same worker with the verdict.

## The controller

Ticks every 15 s and whenever something changes. For each running swarm, in order:

1. A swarm over its `daily_budget` pauses, and resumes the next day by itself.
2. A session with no event for 10 minutes (30 while one of its tools runs) is stopped; its attempt counts as failed.
3. The Foundress gets a planning session when the swarm starts, when something it must react to happened (a milestone
   accepted or rejected, a task given up, the owner wrote, answered or allowed something), when there is nothing left
   to work on or check, or when a worker is idle with no task ready while new reports wait (at most one such session
   every 3 minutes). Reports' follow-ups and concerns are read at the next planning session that happens anyway.
   Three planning sessions in a row that change nothing pause the swarm.
4. Handed-off work goes to an idle inspector, preferring one whose model family differs from the worker's.
5. Open tasks whose `blocked_by` are all accepted go to idle workers, by priority then planning order: to the worker
   asked for, else to a worker nobody asked for.

`max_parallel` caps the sessions a swarm runs at once (the Foundress's included). Models on this machine (Ollama,
llama.cpp, LM Studio) run one session at a time across all swarms.

A worker's session that ends without `hand_off` (or an inspector's without `verdict`) is asked once more in the same
chat; after that the attempt counts as failed. A session is also stopped when it repeats the same tool call with the
same arguments 5 times in a row, is refused 8 times, or spends more than `item_budget` on its task. Pause lets
running sessions finish; Stop ends them and puts their tasks back without counting a failed attempt. A restart puts
tasks that were running back in the queue.

## Rules for tools

Nobody approves actions in a swarm. A tool that would ask the user in a normal chat follows the swarm's rule for it:

- `allow`: it runs.
- `deny`: it is refused, and the agent is told not to try another way.
- `ask`: it is refused the same way, and a permission request goes to the inbox (once while one is open). The agent
  carries on without it. Allowing or refusing it there sets the rule for the swarm.

Defaults (`SwarmDetail.default_rules`): writing and editing files and clicking in the browser are allowed; running
commands, background processes and Python, and typing in the browser, ask. Connector tools ask. Commands and Python
run as the user, without a sandbox.

## The inbox and steering

`ask_owner` files a question; the agent does not wait. Answers, permissions and the owner's messages
(`POST /api/swarms/{id}/message`) reach the Foundress at its next planning session, which they start. Its last
report is `Swarm.report`.

## Sessions and cost

Each planning session, task attempt and check is its own chat session, in the swarm's folder. They are listed on the
swarm's page (agents, item sheets) and not in the chat list, and open like any chat. Every request re-sends its whole
session, so a swarm session's working context is capped at 64K tokens (`SESSION_CONTEXT`): past that, old tool output
is trimmed and then summarized, whatever the model's own window. Cost is what cloud providers report per request
(`EvUsage`), added to the item, the agent and the swarm's day (`spent_today`, `spent_total`, `spent_last_hour`).
