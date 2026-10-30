"""Swarm: named agents with roles (a lead called the Foundress, workers, inspectors) working on one goal for as long
as it runs. The ledger is ``store.py``, what agents are told ``briefs.py``, their tools and rules ``tools.py``, and
the code that runs it all ``controller.py``. Routes: ``routes/swarm.py``; contract: ``schemas_swarm.py``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..agent import profiles
from . import store, tools
from .controller import controller
from .store import SwarmError, owns_session

if TYPE_CHECKING:
    from ..agent.loop import AgentService

__all__ = ["SwarmError", "controller", "init", "owns_session", "shutdown", "start", "store"]


def init() -> None:
    store.init()
    profiles.register(tools.profile, tools.SPECS, tools.IMPL)


def start(agent: AgentService) -> None:
    controller.start(agent)


async def shutdown() -> None:
    await controller.shutdown()
