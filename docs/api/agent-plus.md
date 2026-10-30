# Sequential missions

Missions now live in the unified [Agents section](agents.md) at `/agents/missions`. Existing Agent+ records and `/api/agent-plus` routes remain compatible; the canonical route prefix is `/api/agents`. Each mission has one main sequential agent and can request bounded independent subagents or await research to construct a missing Python tool. Conversations can enter this engine through `start_mission` without creating another chat.

## Routes

| Method | Path | Result |
| --- | --- | --- |
| GET | `/api/agent-plus/missions` | Mission list |
| POST | `/api/agent-plus/missions` | Create a ready mission; does not start inference |
| GET | `/api/agent-plus/missions/{session_id}` | Mission, tool revisions, action receipts, recent events |
| PATCH | `/api/agent-plus/missions/{session_id}` | Amend objective, criteria and resources using current `version`; pause first |
| POST | `/api/agent-plus/missions/{session_id}/resume` | Start/continue sequential work |
| POST | `/api/agent-plus/missions/{session_id}/pause` | Stop current turn and delegated research |
| POST | `/api/agent-plus/missions/{session_id}/cancel` | Cancel; preserve history and tools |

Chat sends, questions, approvals and Stop use existing `/api/ws` agent messages. `agentplus.update` invalidates REST data. WebSocket hello and REST refresh reconstruct the display on reconnect. Completed/cancelled missions need an amendment before another task. Missions require agent mode; their sessions appear in Agents and are excluded from the ordinary recent-chat list.

Contracts: `apps/studio/src/api/contracts/agentPlus.ts`, exported from `types.ts`, mirrored in `server/studio/schemas_agent_plus.py`.

## Execution and persistence

SQLite stores separate mission projections, immutable capability revisions, action receipts and append-only events. Related mission changes, capability validation results, work snapshots and action receipts use synchronous database transactions. Original requests and specification versions remain available. Amendments preserve tools and criterion identifiers for identical text. Changing the objective invalidates criterion evidence; artifacts and receipts remain available for checking again.

Every main-agent tool dispatch records an intent before execution and a receipt afterward. Interruption leaves an uncertain receipt. Startup pauses previously running missions and marks unfinished actions uncertain. Recovery requires inspection and reconciliation before another effect. Failed operations that may have effects are also uncertain. This does not promise exactly-once behavior in external applications.

Malformed research requests rejected by preflight are failed rather than uncertain: delegation and generated execution have not started. A researcher reporting an acceptance conflict before submitting code also produces a failed receipt without an uncertain effect. Failures after generated execution remain conservative.

The main agent continues across turns until criteria have successful task/observation receipts, the user pauses/cancels, a provider fails, or the request budget is exhausted. Four turns without new action results, evidence or learning request an alternative; continued stagnation blocks the mission. `propose_alternative` uses fresh reasoning context with the objective and actual receipts to produce a changed assumption, mechanism, distinguishing test and next action. These remain hypotheses. `plan_work`, `select_work` and `finish_work` manage a persistent dependency graph for delivery, learning, alternatives and validation. References and cycles are checked; only one item runs, after its dependencies finish. Changed work invalidates dependent evidence. `supersede_work` preserves an old branch and its replacement reason, reopens affected criterion evidence and permits an independent replacement. Validated research receipts can finish capability-building work, while mission acceptance still requires real task or observation receipts.

Action results include their receipt IDs. `mission_status` returns a compact progress view and omits previous status responses. `mission_context` retrieves exact receipts, tool source, work or matching events with explicit response limits. The prompt contains active/eligible work and recent source-linked evidence; raw records remain in storage independently of context summaries. Manual compaction also consumes the mission's request budget. Rewind and ordinary chat fork are rejected for Agent+ because they would disconnect the mission from its execution records.

Completion refuses missing evidence and unresolved actions. File evidence includes SHA-256 metadata; completion checks files again and invalidates changed evidence. Receipt presence establishes provenance; the model evaluates whether evidence satisfies a semantic requirement.

## Missing tools

`research_tool` receives a task, input/output schemas and concrete acceptance cases from the main agent before delegation. The researcher has separate context and a restricted source-reading tool set. It cannot modify fixed acceptance cases. `submit_candidate` supplies Python `execute(args)`, distinct extra cases, sources and limitations. Duplicate extra cases are removed. The runtime executes both sets of cases and records the case inputs, provenance, outputs/errors. Failure feedback reports bounded field differences with case indexes; full fixtures and results remain stored for inspection. Limits are six revisions, sixteen research responses and a fifteen-minute deadline. Mission request limits cover research, alternatives and compaction.

The request allows 1–20 fixed cases. The researcher receives the authoritative mission as well as the delegated task. `report_acceptance_conflict` can return a concrete contradictory oracle, its case index and a proposed complete expected result to the main agent. It does not edit or promote a revision. The main agent must review the contract and submit a new request. This provides a route to challenge mistaken tests; detecting every semantic contradiction still depends on model reasoning.

The final three research requests offer only candidate submission and conflict reporting. Source tools are unavailable during that construction phase, so repeated searches cannot consume the entire allocation. A source-only attempt that exhausts its limit without executing generated code records a failed receipt; an attempt that executed code remains uncertain on failure.

Validated revisions are callable through `invoke_chat_tool` only in the originating chat. Failed/candidate revisions cannot run. Runtime failure degrades that revision; older validated revisions remain available. Tools are not promoted globally. Passing these cases establishes bounded validation, not correctness for all inputs. Researcher-authored edge cases supplement fixed checks.

The runner uses a fresh Python process: 15 seconds per validation case, 30 seconds per invocation, bounded output and a monitored 1 GiB process-tree memory limit. It uses the server Python environment and does not install packages. Validation runs in cache storage. Invocation-created files in `outputs/agentplus/{session_id}` are downloadable through content-addressed snapshots, so later calls do not overwrite an earlier download. CUDA devices are hidden from generated-tool processes; selected local model inference retains its normal runtime. The schema checker implements primitive types, properties, required keys, enums, length/item limits and numeric bounds; it is not a complete JSON Schema implementation.

This is process isolation, **not an OS security sandbox**. Generated code runs with the user's OS privileges. Research and invocation follow the existing `run_python` approval preference. Approving research authorizes bounded construction/testing; source and check results remain inspectable. No hosted orchestrator or separate database service is required.

## Budgets

Default: 80 model requests and zero remote-model spending. Ollama, llama.cpp, LM Studio and loopback OpenAI-compatible providers run at zero monetary budget. Remote requests reserve $0.25 before dispatch and settle reported usage afterward; missing reports retain the estimate. Actual billing may exceed that estimate for one request. Further dispatch stops when the budget is reached. The operator can amend request and spending limits. Amendments authorize another request allocation but retain lifetime spending.

## Verification

From `server`, run `.venv/Scripts/python.exe -m unittest discover -s tests -p test_agent_plus.py -v`. Temporary databases/files and scripted providers exercise failure/repair, fixed and edge cases, reuse, immutable downloads, report creation, evidence, completion, denied execution, chat isolation, immutable revisions, restart recovery, timeouts, degradation, amendments, resource accounting, context retrieval, alternative proposals, branch replacement and transaction rollback. This does not measure live-model research quality.

`tests/run_agent_plus_local.py` exercises real local Qwen 27B inference with thinking disabled and a 60-request allocation. It constructs an invoice normalizer, checks two batches independently, requires same-tool reuse and verifies the saved report and mission completion. It uses temporary mission storage, retains run records under the ignored `data/agentplus-verification` directory and stops its native model server afterward. It does not call a paid provider. `tests/preview_agent_plus.py` serves an isolated UI acceptance fixture without starting Swarm or automation runners.

The 2026-10-05 run `e23ede9160374b97` completed in 30 requests. Revision 1 passed 9/10 checks; revision 2 passed 10/10 distinct checks. The implementation hash stayed unchanged: the researcher corrected an extra rounding expectation to Decimal's default rounding, while fixed main-agent acceptance cases stayed unchanged. The same validated revision processed both batches. An independent checker matched every normalized row/date, currency total and final saved report. Earlier live tests exposed context recursion, ambiguous receipt references and unhelpful repair feedback. Retained run `8f188a64a1a7429e` demonstrates a code repair and correct batch outputs but exhausted its request budget before completing bookkeeping; `12d4aee07fba4e3b` records an unsuccessful validation/recovery attempt. This is evidence for this workload, not general task competence. The integration suite subsequently passed 28 tests, including research preflight, acceptance-conflict reporting, reserved construction requests, repeated-learning detection and compact field-level failure feedback. TypeScript checking, lint and the production frontend build passed during the initial implementation.

`tests/run_agent_plus_media.py` runs a supervised one-hour local Qwen workload over 1,964 synthetic CSV rows. It requires ingestion, reconciliation, an offline dashboard and independent exact output checks. A second release is revealed only after baseline completion and verification. Resumes retain the original deadline; run records identify supervisor feedback and interrupted attempts. `tests/preview_agent_plus_live.py --run <run-directory> --port 8878` serves a read-only localhost snapshot view without starting model inference or modifying mission storage.

The supervised media run `900cb862bde94178` stopped blocked after 3,530 seconds and 187 lifetime model requests, with zero recorded remote cost. The same validated ingestion revision processed four batches: every one of the 1,940 normalized rows and 24 quarantine entries matched an independent source-row oracle. Reconciliation produced no production canonical, quarantine or audit files; no dashboard was delivered and release 2 did not start. The run exposed incorrect model-authored oracles, repeated source gathering, malformed submissions, guessed filenames and repeated complaints about truncated failure feedback. Supervisor fixtures, corrections, reviewed recoveries and restarts were needed. Compact field-difference feedback was added and covered by a regression test afterward; the final live process still used the earlier format. Records are in `data/agentplus-verification/media-audit-20261005-062746/test-report.json`. This run does not demonstrate autonomous end-to-end completion.

This release uses the existing local SQLite and single-process agent runtime. Restart recovery pauses for review; it does not automatically replay external effects. Distributed worker leases, automatic cross-chat capability promotion, learned scheduling and device gateways are not implemented.
