"""The agent turn loop: stream the model, run tools (with approval), feed results back, repeat."""

from __future__ import annotations

import asyncio
import re
import time
import traceback
import uuid
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from .. import db, events, openrouter_usage, settings
from ..events import bus
from ..schemas import (ActiveTurn, AgentMessage, AgentSession, ContextUsage, EvAgent, EvContext, EvDone, EvError,
                       EvMessageStart, EvTextDelta, EvThinkingDelta, EvTitle, EvToolApproval, EvToolCall,
                       EvSpeed, EvToolProgress, EvToolResult, EvTurnStart, EvUsage, ThinkingPart, ToolCall)
from ..schemas_workspace import QuestionDisplay
from ..workspace import state as workspace_state
from . import context, history, images, prompt, textcalls, tools
from .providers import Provider, get_provider
from .types import (Call, Message, ProviderError, StepEnd, TextDelta, ThinkingDelta, ToolContext, ToolOutcome,
                    Usage)

MAX_STEPS = 50
# Completion check (Taskmaster): when the agent stops a tool-using turn, it gets a checklist and must answer with a
# verdict — [[DONE: yes]] ends the turn, [[DONE: no]] means it keeps working. Only the last verdict counts, since small
# models also echo the instructions. Local models often announce the next action ("Proceeding with the plan...") and
# stop without calling a tool; the check sends them back to work.
MAX_CHECKS = 3  # consecutive checks without progress before the turn ends anyway
_VERDICT_RE = re.compile(r"\[\[\s*DONE\s*(?::\s*(yes|no))?\s*\]\]", re.IGNORECASE)
_ANNOUNCES = re.compile(
    r"(\b(proceed(ing)?|let me|let's|i'?ll|i will|i am going to|i'm going to|now i|next,? i|starting|moving on)\b"
    r"[^.!?\n]*[.!:…]*|\.\.\.|…|:)\s*$", re.IGNORECASE)
DENIED = "User denied this action"
DEFAULT_TITLE = "New chat"
_TITLE_SYSTEM = ("Write a 3-6 word title for this conversation. Reply with the title only: no quotes, no "
                 "punctuation at the end.")


class TurnBusy(Exception):
    pass


class Turn:
    """One user message being answered. Runs as a server-side task that does not depend on any
    client connection; every event is broadcast to all WebSocket clients. ``user_message`` and
    ``reply`` are the live state behind ``ActiveTurn`` snapshots — they are always mutated in the
    same synchronous step as the event describing the change is published, so a snapshot plus
    the events published after it reconstruct the turn exactly."""

    def __init__(self, session: AgentSession, user_message: AgentMessage, reply: AgentMessage,
                 listener: Callable[[BaseModel], None] | None = None) -> None:
        self.session = session
        self.user_message = user_message
        self.reply = reply
        self.thinking: list[str] = []
        self.seq = 0  # order of the reply's thinking parts and tool calls
        self.open_thinking: ThinkingPart | None = None  # the part thinking deltas extend (until text or a call)
        self.approvals: dict[str, asyncio.Future[bool]] = {}
        self.answers: dict[str, asyncio.Future[str]] = {}  # ask_user questions waiting for the user
        self.task: asyncio.Task[None] | None = None
        self.finished = False
        self.stopped = False  # ended by agent.stop (user Stop, session deletion or shutdown)
        self.listener = listener  # server-side observer of this turn's events (background tasks)

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq

    def emit(self, event: BaseModel) -> None:
        bus.publish(EvAgent(session_id=self.session.id, event=event))
        if self.listener is not None:
            self.listener(event)

    def snapshot(self) -> ActiveTurn:
        message = self.reply.model_copy(deep=True)
        message.thinking = "".join(self.thinking) or None
        message.tool_calls = message.tool_calls or None
        return ActiveTurn(session_id=self.session.id, user_message=self.user_message.model_copy(deep=True),
                          message=message)

    def cancel(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()


class AgentService:
    def __init__(self) -> None:
        self._turns: dict[str, Turn] = {}

    def start(self, session: AgentSession, content: str, listener: Callable[[BaseModel], None] | None = None,
              pictures: list[str] | None = None) -> Turn:
        """Persist the user message, broadcast ``turn.start`` and run the turn in the background. ``pictures``:
        URLs of images attached to the message (``POST /agent/images``)."""
        existing = self._turns.get(session.id)
        if existing and not existing.finished:
            raise TurnBusy("A reply is already being generated for this session; stop it first")
        for ref in pictures or []:
            images.to_path(ref)  # ToolFailure for anything that isn't an attached image
        first_exchange = not db.list_message_steps(session.id)
        user = AgentMessage(id=_id(), role="user", content=content, images=pictures or None,
                            created_at=db.now_iso())
        db.save_message(session.id, user)
        convo = history.load(session.id)
        reply = AgentMessage(id=_id(), role="assistant", content="", created_at=db.now_iso(), tool_calls=[])
        turn = Turn(session, user, reply, listener)
        self._turns[session.id] = turn
        turn.emit(EvTurnStart(user_message=user))
        turn.emit(EvMessageStart(message_id=reply.id))
        turn.task = asyncio.create_task(self._run(turn, content, convo, first_exchange), name=f"agent-{session.id}")
        # A task cancelled before its first step never runs _run's cleanup; make sure it still ends.
        turn.task.add_done_callback(lambda _t: self._finish(turn))
        return turn

    def answer(self, session_id: str, call_id: str, answer: str) -> bool:
        turn = self._turns.get(session_id)
        fut = turn.answers.get(call_id) if turn else None
        if fut is None or fut.done():
            return False
        fut.set_result(answer.strip())
        return True

    def approve(self, session_id: str, call_id: str, approved: bool) -> bool:
        turn = self._turns.get(session_id)
        fut = turn.approvals.get(call_id) if turn else None
        if fut is None or fut.done():
            return False
        fut.set_result(approved)
        return True

    def stop(self, session_id: str) -> asyncio.Task[None] | None:
        """Cancel the session's running turn; returns its task (None if nothing was running)."""
        turn = self._turns.get(session_id)
        if turn is None or turn.finished:
            return None
        turn.cancel()
        return turn.task

    async def stop_and_wait(self, session_id: str, timeout: float = 15) -> None:
        """Stop the running turn and wait until it has finished writing its final state."""
        task = self.stop(session_id)
        if task is not None:
            await asyncio.wait({task}, timeout=timeout)

    def active_turns(self) -> list[ActiveTurn]:
        return [t.snapshot() for t in self._turns.values() if not t.finished]

    async def shutdown(self) -> None:
        tasks = [t for t in (self.stop(sid) for sid in list(self._turns)) if t is not None]
        if tasks:
            await asyncio.wait(tasks, timeout=10)

    # ------------------------------------------------------------------

    async def _run(self, turn: Turn, content: str, convo: list[Message], first_exchange: bool) -> None:
        session = turn.session
        reply = turn.reply
        thinking = turn.thinking
        steps: list[dict[str, Any]] = []

        def save() -> None:
            reply.thinking = "".join(thinking) or None
            db.save_message(session.id, reply.model_copy(update={"tool_calls": reply.tool_calls or None}), steps)

        cancelled = False
        try:
            save()
            provider = get_provider(session.model)
            provider.context_limit = session.context_size
            info = await provider.info()
            if session.context_size:  # the chat's own window (/context) caps the model's
                info.context = min(session.context_size, info.context or session.context_size)
            # Fixed for the whole turn (stable prefix); reads image-model files from disk on first use
            system = await asyncio.to_thread(prompt.build, session.mode, session.id, info, session.model)
            specs = tools.all_specs() if session.mode == "agent" else None
            budget = context.Budget(info)
            note = await context.compact_history(provider, session.id, system, specs, convo, budget)
            request = convo[-1]  # the user's message: kept verbatim whatever gets summarized
            checks = 0
            checking = False  # the step answers a completion check: its text is a checklist, not for the user
            for _ in range(MAX_STEPS):
                current = next(i for i, m in enumerate(convo) if m is request)
                fitted = await budget.fit(provider, system, specs, convo, current)
                note = "; ".join(n for n in (note, fitted) if n) or None
                estimated = budget.estimate(system, specs, convo)
                try:
                    end = await self._stream_step(turn, provider, system, convo, specs, reply, thinking, checking)
                except ProviderError as exc:
                    # Refused as too large (nothing was generated yet): summarize down to fit and retry once
                    too_big = context.overflow(str(exc))
                    if too_big is None:
                        raise
                    events.log("warn", "agent", f"{session.model}: request too large for the context window, "
                                                "summarizing and retrying")
                    fitted = await budget.recover(provider, system, specs, convo, current, *too_big)
                    note = "; ".join(n for n in (note, fitted) if n) or None
                    estimated = budget.estimate(system, specs, convo)
                    try:
                        end = await self._stream_step(turn, provider, system, convo, specs, reply, thinking, checking)
                    except ProviderError as again:
                        if context.overflow(str(again)) is None:
                            raise
                        raise ProviderError(
                            "This conversation no longer fits the model's context window, even after summarizing. "
                            "Start a new chat, run /compact, or give the model a larger context (Settings).") from again
                budget.observe(end, estimated)
                self._report_context(turn, budget, estimated, note)
                note = None
                if specs and not end.calls:  # tool calls the model printed as text instead of emitting them
                    # reply.content keeps the markup as streamed (the chat view hides it), so tool-call positions
                    # (ToolCall.at) match what the client has; the model's history gets the clean text.
                    clean, recovered = textcalls.extract(end.text, set(tools.BY_NAME))
                    if recovered:
                        end = StepEnd(text=clean, calls=recovered, stop_reason=end.stop_reason)
                step: dict[str, Any] = {"text": end.text, "calls": []}
                steps.append(step)
                convo.append(Message("assistant", end.text, calls=end.calls, raw=end.raw))
                save()
                verdicts = [(m.group(1) or "").lower() for m in _VERDICT_RE.finditer(end.text)]
                if verdicts:  # the model's own history keeps the text without the marker; the chat view hides it
                    step["text"] = _VERDICT_RE.sub("", end.text).strip()
                    convo[-1] = Message("assistant", step["text"], calls=end.calls, raw=end.raw)
                if end.calls:
                    checks = 0  # working again: the next stop gets a fresh check
                    checking = False
                else:
                    verdict = verdicts[-1] if verdicts else None
                    if verdict == "yes":
                        if checking and not reply.content.strip():  # its only words were the check reply: show them
                            reply.content = step["text"]
                            turn.emit(EvTextDelta(text=step["text"]))
                        break
                    check = None
                    if specs:
                        check = (_continue_note() if verdict == "no" else
                                 _completion_check(session.id, end.text, steps, asked=checks > 0))
                    if check is None:
                        break  # a plain answer in a turn that used no tools
                    if checks >= MAX_CHECKS:
                        turn.emit(EvError(message="The agent stopped without finishing: it didn't confirm the work "
                                                  f"was done after {MAX_CHECKS} completion checks. Ask it to continue."))
                        break
                    checks += 1
                    checking = True
                    step["nudge"] = check  # replayed as a user message (history.step_messages)
                    convo.append(Message("user", check))
                    save()
                    continue
                for call in end.calls:
                    await self._run_tool(turn, call, reply, step, convo, save, info.vision)
            else:
                turn.emit(EvError(message=f"Stopped after {MAX_STEPS} tool steps without a final answer"))
            if first_exchange and session.title == DEFAULT_TITLE:
                await self._make_title(turn, provider, content, reply.content)
        except asyncio.CancelledError:
            cancelled = turn.stopped = True
            self._close_open_calls(turn, reply, steps)
        except ProviderError as exc:
            events.log("warn", "agent", f"{session.model}: {exc}")
            turn.emit(EvError(message=str(exc)))
        except Exception as exc:
            events.log("error", "agent", f"Turn failed: {exc}\n{traceback.format_exc(limit=8)}")
            turn.emit(EvError(message=f"{type(exc).__name__}: {exc}"))
        finally:
            try:
                save()
            except Exception as exc:  # the turn must still end cleanly, or the session stays busy forever
                events.log("error", "agent", f"Could not save the reply in session {session.id}: {exc}")
            if cancelled:
                events.log("info", "agent", f"Turn in session {session.id} stopped by user")
            self._finish(turn)

    def _finish(self, turn: Turn) -> None:
        """End of turn: broadcast ``done`` and drop the ActiveTurn (idempotent)."""
        if turn.finished:
            return
        turn.emit(EvDone())
        turn.finished = True
        if self._turns.get(turn.session.id) is turn:
            del self._turns[turn.session.id]

    @staticmethod
    def _report_context(turn: Turn, budget: context.Budget, estimated: int, note: str | None) -> None:
        used = budget.last_used or estimated
        turn.emit(EvContext(usage=ContextUsage(used=used, limit=budget.limit), note=note))
        db.set_context_usage(turn.session.id, used, budget.limit)

    async def _stream_step(self, turn: Turn, provider: Provider, system: str, convo: list[Message],
                           specs: list[tools.ToolSpec] | None, reply: AgentMessage, thinking: list[str],
                           checking: bool = False) -> StepEnd:
        """Stream one model response. ``checking``: it answers a completion check, so its text is shown as a
        collapsed thinking block instead of being added to the reply."""
        end: StepEnd | None = None
        separated = False
        first_token: float | None = None  # when the model started generating (after reading the prompt)
        billed_tokens: int | None = None
        async for ev in provider.stream(system, convo, specs):
            if checking and isinstance(ev, TextDelta):
                ev = ThinkingDelta(ev.text)
            if first_token is None and isinstance(ev, (TextDelta, ThinkingDelta)):
                first_token = time.monotonic()
            if isinstance(ev, TextDelta):
                text = ev.text
                if not separated and reply.content and not reply.content.endswith("\n"):
                    text = "\n\n" + text  # visually separate text written before/after tool calls
                separated = True
                reply.content += text
                turn.open_thinking = None
                turn.emit(EvTextDelta(text=text))
            elif isinstance(ev, ThinkingDelta):
                thinking.append(ev.text)
                part = turn.open_thinking
                if part is None:  # thinking after text or a tool call starts a new block there
                    part = turn.open_thinking = ThinkingPart(at=len(reply.content), seq=turn.next_seq(), text="")
                    reply.thinking_parts = [*(reply.thinking_parts or []), part]
                part.text += ev.text
                turn.emit(EvThinkingDelta(text=ev.text, at=part.at, seq=part.seq))
            elif isinstance(ev, Usage):
                openrouter_usage.record("chat", turn.session.model.partition(":")[2], ev,
                                        session_id=turn.session.id, message_id=reply.id)
                billed_tokens = ev.completion_tokens
                if ev.cost is not None:
                    reply.cost = round((reply.cost or 0) + ev.cost, 8)
                    turn.emit(EvUsage(cost=ev.cost, total=reply.cost))
            elif isinstance(ev, StepEnd):
                end = ev
        if end is None:
            raise ProviderError("The model stream ended without a final message")
        self._add_speed(turn, reply, end.output_tokens or billed_tokens,
                        end.generation_s or (time.monotonic() - first_token if first_token is not None else None))
        return end

    @staticmethod
    def _add_speed(turn: Turn, reply: AgentMessage, tokens: int | None, seconds: float | None) -> None:
        """Count one step toward the reply's generation speed. A step is counted only with both numbers: tokens
        without a time (a tool-call-only step of a provider that doesn't time itself) would inflate tok/s."""
        if not tokens or not seconds or seconds <= 0:
            return
        reply.output_tokens = (reply.output_tokens or 0) + tokens
        reply.generation_s = round((reply.generation_s or 0.0) + seconds, 3)
        turn.emit(EvSpeed(output_tokens=reply.output_tokens, generation_s=reply.generation_s))

    async def _run_tool(self, turn: Turn, call: Call, reply: AgentMessage, step: dict[str, Any],
                        convo: list[Message], save: Any, vision: bool) -> ToolOutcome | None:
        """Run one call (after approval, if it needs it); returns its outcome, None when the user denied it."""
        auto = settings.load().agent_auto_approve
        gated = tools.needs_approval(call.name, auto)
        tc = ToolCall(id=call.id, name=call.name, args=call.args, status="pending_approval" if gated else "running",
                      at=len(reply.content), seq=turn.next_seq())
        turn.open_thinking = None
        assert reply.tool_calls is not None
        reply.tool_calls.append(tc)
        record = {"id": call.id, "name": call.name, "args": call.args, "output": None, "ok": False}
        step["calls"].append(record)
        turn.emit(EvToolCall(call=tc))
        save()

        if gated:
            fut: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
            turn.approvals[call.id] = fut
            turn.emit(EvToolApproval(call_id=call.id))
            approved = await fut
            if not approved:
                tc.status, tc.output = "denied", DENIED
                record.update(output=DENIED, ok=False)
                turn.emit(EvToolResult(call_id=call.id, ok=False, output=DENIED))
                convo.append(Message("tool", DENIED, call_id=call.id, name=call.name, is_error=True))
                save()
                return None
            tc.status = "running"
            turn.emit(EvToolCall(call=tc))  # tell every client the call was approved and is now running
            save()

        def progress(display: BaseModel) -> None:
            tc.display = display  # type: ignore[assignment]
            turn.emit(EvToolProgress(call_id=call.id, display=display))

        async def ask(question: str, options: list[str]) -> str:
            """Show the question on the call's card and wait for the user's answer (agent.answer)."""
            fut: asyncio.Future[str] = asyncio.get_running_loop().create_future()
            turn.answers[call.id] = fut
            display = QuestionDisplay(question=question, options=options)
            tc.status, tc.display = "awaiting_input", display
            turn.emit(EvToolCall(call=tc))
            save()
            try:
                answer = await fut
            finally:
                turn.answers.pop(call.id, None)
            display.answer = answer
            tc.status = "running"
            turn.emit(EvToolCall(call=tc))
            return answer

        try:
            outcome = await tools.execute(call.name, call.args,
                                          ToolContext(turn.session.id, call.id, progress, vision=vision,
                                                      ask=ask if turn.listener is None else None))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # unexpected tool crash: report to the model instead of killing the turn
            events.log("error", "agent", f"Tool {call.name} crashed: {exc}\n{traceback.format_exc(limit=6)}")
            outcome = ToolOutcome(False, f"Error: {type(exc).__name__}: {exc}")
        tc.status = "done" if outcome.ok else "error"
        tc.output = outcome.output
        tc.artifacts = outcome.artifacts or None
        if outcome.display is not None:
            tc.display = outcome.display  # type: ignore[assignment]
        record.update(output=outcome.output, ok=outcome.ok)
        if outcome.images:
            record["images"] = [images.public_url(p) or str(p) for p in outcome.images]
        turn.emit(EvToolResult(call_id=call.id, ok=outcome.ok, output=outcome.output,
                               artifacts=outcome.artifacts or None, display=tc.display))
        convo.append(Message("tool", outcome.output, call_id=call.id, name=call.name, is_error=not outcome.ok,
                             images=list(outcome.images)))
        save()
        return outcome

    @staticmethod
    def _close_open_calls(turn: Turn, reply: AgentMessage, steps: list[dict[str, Any]]) -> None:
        """On stop: a call still awaiting approval counts as denied, a running one as
        cancelled. Both get a final tool.result so the UI and persisted state agree."""
        records = {c["id"]: c for step in steps for c in step["calls"]}
        for tc in reply.tool_calls or []:
            if tc.status == "pending_approval":
                tc.status, tc.output = "denied", DENIED
            elif tc.status in ("running", "awaiting_input"):
                tc.status, tc.output = "error", "Cancelled by user"
            else:
                continue
            if tc.id in records:
                records[tc.id].update(output=tc.output, ok=False)
            turn.emit(EvToolResult(call_id=tc.id, ok=False, output=tc.output))

    async def _make_title(self, turn: Turn, provider: Provider, user: str, answer: str) -> None:
        title = ""
        try:
            convo = f"<conversation>\nUser: {user[:600]}\nAssistant: {answer[:600]}\n</conversation>\n\n"
            raw = await asyncio.wait_for(
                provider.complete(_TITLE_SYSTEM, convo + "Title for this conversation (3-6 words):"), timeout=30)
            title = _clean_title(raw, max_words=8)
        except (ProviderError, TimeoutError) as exc:
            events.log("info", "agent", f"Title generation fell back to heuristic: {exc}")
        if not title:
            title = _clean_title(" ".join(user.split()[:6])) or DEFAULT_TITLE
        db.update_session(turn.session.id, title=title)
        turn.emit(EvTitle(title=title))


def _clean_title(text: str, max_words: int | None = None) -> str:
    """First meaningful line, without quotes/markdown; '' if it doesn't look like a title."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    line = line.strip(" \"'`*#").removeprefix("Title:").strip().strip("\"'").rstrip(".")
    if max_words is not None and len(line.split()) > max_words:
        return ""
    return line[:60].rstrip() + ("…" if len(line) > 60 else "")


def _id() -> str:
    return uuid.uuid4().hex[:16]


agent = AgentService()


_VERDICT_LINES = [
    "End this reply with exactly one verdict line:",
    "[[DONE: yes]] - everything the user asked for is fully done (or you truly need their input to continue).",
    "[[DONE: no]] - work remains: then call the tools for the next step in this same reply.",
]


def _completion_check(session_id: str, text: str, steps: list[dict[str, Any]], asked: bool = False) -> str | None:
    """The checklist (Taskmaster) sent when the agent stops a turn that used tools or ended by announcing an action;
    None for a plain answer to a question. ``asked``: a check already went unanswered (no verdict line)."""
    used_tools = any(s["calls"] for s in steps)
    if not used_tools and not _ANNOUNCES.search(text.strip()):
        return None
    planned = any(c["name"] == "update_plan" for s in steps for c in s["calls"])
    open_items = [p.text for p in workspace_state.get(session_id).plan if p.status != "done"] if planned else []
    failed = [c["name"] for s in steps for c in s["calls"] if not c.get("ok", False)]
    lines = ["(Automatic completion check - not from the user.) You stopped without calling a tool. Before this turn "
             "can end:"]
    if asked:
        lines.append("Your last reply had no verdict line - answer the check and end with a verdict.")
    lines += [
        "1. GOAL: restate the user's request in one line. Is it fully achieved RIGHT NOW? Yes or no - not "
        "'partially', not 'mostly'.",
        "2. REQUESTS: list every thing the user asked for (each kind of output, each step) and whether it is fully "
        "done - not just started.",
        "3. PLAN AND RESULTS: any plan item not done? Any tool call that failed, or a result you haven't checked?",
    ]
    if open_items:
        lines.append("   Plan items not done: " + "; ".join(open_items[:8]) + ".")
    if failed:
        lines.append("   Tool calls that failed this turn: " + ", ".join(dict.fromkeys(failed)) + ".")
    lines += [
        "4. If anything is not done, don't describe what you will do - call the tools for the next step now. "
        "Progress is not completion, and something being hard is not a reason to stop: try another way. Only the "
        "user can tell you to stop early.",
        *_VERDICT_LINES,
    ]
    return "\n".join(lines)


def _continue_note() -> str:
    """After a [[DONE: no]] verdict without a tool call."""
    return "\n".join([
        "(Automatic note - not from the user.) You said the work is not done, so continue: call the tools for the "
        "next unfinished item now. Don't describe it - do it.",
        *_VERDICT_LINES,
    ])
