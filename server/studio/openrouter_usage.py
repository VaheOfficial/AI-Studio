"""OpenRouter spend tracking: a local ledger of every billed request (per agent message, per
generation) plus the live account summary (``GET /key`` and, with a management key, ``GET /credits``).

After each recorded charge the account is re-read and pushed to every client as an
``openrouter.account`` event, so the balance in the UI follows spending without polling.
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from datetime import datetime, timezone

from . import db, events, openrouter, settings
from .events import bus
from .openrouter import OpenRouterError, Usage
from .schemas import AgentMessage
from .schemas_openrouter import ChargeKind, EvOpenRouterAccount, OpenRouterAccount, OpenRouterCharge

_ACCOUNT_TTL_S = 60.0
_REFRESH_DELAY_S = 2.0  # OpenRouter's usage counters lag the response slightly; also coalesces bursts
_COST_LOOKUP_DELAYS_S = (2, 4, 8, 16)


def init() -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS openrouter_usage (
        id TEXT PRIMARY KEY,
        ts TEXT NOT NULL,
        kind TEXT NOT NULL,
        model TEXT NOT NULL,
        cost REAL,
        prompt_tokens INTEGER,
        completion_tokens INTEGER,
        generation_id TEXT,
        session_id TEXT,
        message_id TEXT,
        ref TEXT
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS openrouter_usage_session ON openrouter_usage(session_id)")
    db.execute("CREATE INDEX IF NOT EXISTS openrouter_usage_ts ON openrouter_usage(ts)")


# -------------------------------- ledger --------------------------------


def record(kind: ChargeKind, model: str, usage: Usage, *, session_id: str | None = None,
           message_id: str | None = None, ref: str | None = None) -> None:
    """Add one billed request to the ledger and push the refreshed account to clients."""
    db.execute(
        """INSERT INTO openrouter_usage(id, ts, kind, model, cost, prompt_tokens, completion_tokens, generation_id,
                                        session_id, message_id, ref) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (uuid.uuid4().hex[:16], db.now_iso(), kind, model, usage.cost, usage.prompt_tokens,
         usage.completion_tokens, usage.generation_id, session_id, message_id, ref),
    )
    if usage.prompt_tokens and usage.cached_tokens:
        events.log("info", "openrouter", f"{model}: {usage.cached_tokens:,} of {usage.prompt_tokens:,} prompt tokens "
                                         "came from the prompt cache")
    _refresh_soon()


def record_when_billed(kind: ChargeKind, model: str, usage: Usage, *, ref: str | None = None) -> None:
    """For endpoints that don't report cost inline (TTS): look the generation up in the background
    and record it once OpenRouter has billed it (or without a cost if it never shows up)."""

    def run() -> None:
        billed = usage
        if usage.generation_id:
            for delay in _COST_LOOKUP_DELAYS_S:
                time.sleep(delay)
                try:
                    stats = openrouter.generation(usage.generation_id)
                except OpenRouterError as exc:
                    events.log("warn", "openrouter", f"Could not read the cost of {usage.generation_id}: {exc}")
                    break
                if stats and isinstance(stats.get("total_cost"), (int, float)):
                    billed = Usage(cost=float(stats["total_cost"]), prompt_tokens=stats.get("tokens_prompt"),
                                   completion_tokens=stats.get("tokens_completion"),
                                   generation_id=usage.generation_id)
                    break
        record(kind, model, billed, ref=ref)

    threading.Thread(target=run, name="openrouter-cost", daemon=True).start()


def with_costs(session_id: str, messages: list[AgentMessage]) -> list[AgentMessage]:
    """Attach the billed cost to each of a session's assistant messages."""
    rows = db.query("SELECT message_id, SUM(cost) AS cost FROM openrouter_usage WHERE session_id = ? "
                    "AND cost IS NOT NULL GROUP BY message_id", (session_id,))
    costs = {r["message_id"]: round(float(r["cost"]), 8) for r in rows}
    return [m.model_copy(update={"cost": costs[m.id]}) if m.id in costs else m for m in messages]


def _recent(limit: int = 12) -> list[OpenRouterCharge]:
    rows = db.query("SELECT * FROM openrouter_usage ORDER BY ts DESC LIMIT ?", (limit,))
    return [OpenRouterCharge(id=r["id"], ts=r["ts"], kind=r["kind"], model=r["model"], cost=r["cost"],
                             session_id=r["session_id"], ref=r["ref"]) for r in rows]


def _studio_today() -> float:
    """Spend recorded by the studio since local midnight."""
    midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    since = midnight.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    row = db.query_one("SELECT COALESCE(SUM(cost), 0) AS total FROM openrouter_usage WHERE ts >= ?", (since,))
    return float(row["total"]) if row else 0.0


# -------------------------------- account --------------------------------

_cache: tuple[tuple[str | None, str | None], float, OpenRouterAccount] | None = None
_refresh_timer: threading.Timer | None = None
_timer_lock = threading.Lock()


def _num(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


async def _fetch(key: str | None, mgmt: str | None) -> OpenRouterAccount:
    info: dict[str, object] = {}
    cred: dict[str, object] = {}
    error: str | None = None
    if key:
        try:
            info = await openrouter.key_info(key)
        except OpenRouterError as exc:
            error = str(exc)
    if mgmt:
        try:
            cred = await openrouter.credits(mgmt)
        except OpenRouterError as exc:
            error = error or f"Management key: {exc}"
    total, used = _num(cred.get("total_credits")), _num(cred.get("total_usage"))
    return OpenRouterAccount(
        configured=bool(key), management_key=bool(mgmt), ok=bool(key or mgmt) and error is None, error=error,
        label=str(info["label"]) if info.get("label") else None,
        balance=round(total - used, 6) if total is not None and used is not None else None,
        total_credits=total, limit=_num(info.get("limit")), limit_remaining=_num(info.get("limit_remaining")),
        limit_reset=str(info["limit_reset"]) if info.get("limit_reset") else None,
        usage_total=_num(info.get("usage")), usage_daily=_num(info.get("usage_daily")),
        usage_weekly=_num(info.get("usage_weekly")), usage_monthly=_num(info.get("usage_monthly")),
        is_free_tier=info.get("is_free_tier") if isinstance(info.get("is_free_tier"), bool) else None,
        studio_today=round(_studio_today(), 6), recent=_recent(), updated_at=db.now_iso(),
    )


async def account(force: bool = False) -> OpenRouterAccount:
    """The account summary; cached for a minute per key pair (a key change refetches immediately)."""
    global _cache
    s = settings.load()
    keys = (s.openrouter_api_key, s.openrouter_management_key)
    cached = _cache
    if not force and cached and cached[0] == keys and time.monotonic() - cached[1] < _ACCOUNT_TTL_S:
        return cached[2].model_copy(update={"studio_today": round(_studio_today(), 6), "recent": _recent()})
    # Runs on the server loop and on the refresh thread's own loop: no asyncio lock (a race only costs a refetch)
    acc = await _fetch(*keys)
    _cache = (keys, time.monotonic(), acc)
    return acc


def _refresh_soon() -> None:
    global _refresh_timer
    with _timer_lock:
        if _refresh_timer is not None:
            return
        _refresh_timer = threading.Timer(_REFRESH_DELAY_S, _refresh_and_publish)
        _refresh_timer.daemon = True
        _refresh_timer.start()


def _refresh_and_publish() -> None:
    global _refresh_timer
    with _timer_lock:
        _refresh_timer = None
    try:
        acc = asyncio.run(account(force=True))
    except Exception as exc:  # never let a background refresh crash silently without a trace
        events.log("warn", "openrouter", f"Could not refresh the account summary: {exc}")
        return
    bus.publish(EvOpenRouterAccount(account=acc))
