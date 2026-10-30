"""Agent+ is a sequential agent with persistent missions and bounded tool research."""
from ..agent import profiles
from . import store, tools
from .controller import controller
from .store import owns_session


def init() -> None:
    store.init()
    store.recover()
    if tools.profile not in profiles._resolvers:
        profiles.register(tools.profile, tools.SPECS, tools.IMPL)
