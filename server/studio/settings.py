"""User settings persisted in the ``settings`` table."""

from __future__ import annotations

from typing import Any

from . import config, db
from .schemas import Settings, SettingsUpdate

SECRET_FIELDS = (
    "hf_token", "openai_api_key",
    "openrouter_api_key", "openrouter_management_key", "tencent_api_key",
)
MASK = "•••"
_DEFAULTS: dict[str, Any] = {"agent_auto_approve": [], "offload_policy": "auto", "default_models": {}}


def load() -> Settings:
    """Settings with real secret values (server-side use only)."""
    values = {**_DEFAULTS, **db.get_setting_values()}
    values["data_dir"] = str(config.DATA_DIR)
    return Settings.model_validate(values)


def masked(s: Settings | None = None) -> Settings:
    s = s or load()
    return s.model_copy(update={f: MASK for f in SECRET_FIELDS if getattr(s, f)})


class SettingsError(ValueError):
    pass


def update(patch: SettingsUpdate) -> Settings:
    changes = patch.model_dump(exclude_unset=True)
    data_dir = changes.pop("data_dir", None)
    if data_dir and data_dir.rstrip("\\/") != str(config.DATA_DIR).rstrip("\\/"):
        raise SettingsError(
            "data_dir cannot be changed at runtime; set the STUDIO_DATA_DIR environment variable and restart the server"
        )
    for key, value in changes.items():
        if key in SECRET_FIELDS and value == MASK:
            continue  # the UI echoed the mask back: keep the stored secret
        if key == "default_models" and isinstance(value, dict):
            value = {task: mid.strip() for task, mid in value.items() if isinstance(mid, str) and mid.strip()}
        if isinstance(value, str):
            value = value.strip()
            if key == "openai_base_url":
                value = value.rstrip("/")
        if value == "" or value is None:
            db.set_setting_value(key, None)
        else:
            db.set_setting_value(key, value)
    return load()
