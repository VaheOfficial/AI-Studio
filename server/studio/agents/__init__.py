"""Unified agents: identities, capabilities, delegated work and durable outputs."""
from . import store, delegation, wakes, vault, oauth, collections, plugins, devices, services, notifications, policies, model_checks, monitors, channels, git_workspace, recording


def init() -> None:
    store.init()
    vault.init()
    oauth.init()
    collections.init()
    plugins.init()
    devices.init()
    services.init()
    notifications.init()
    delegation.init()
    policies.init()
    model_checks.init()
    wakes.init()
    monitors.init()
    channels.init()
    git_workspace.init()
    recording.init()
