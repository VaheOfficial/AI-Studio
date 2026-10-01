"""OmniVoice vocabularies loaded by file path from the vendored worker package.

``voice_design.py`` (design tags) and ``lang_map.py`` (646 languages) are stdlib-only, so the server
reads the exact files the worker validates against — one source of truth, no torch import.
"""

from __future__ import annotations

import importlib.util
from types import ModuleType

from .. import config


def _load(name: str) -> ModuleType:
    path = config.WORKERS_DIR / "omnivoice" / "utils" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_omnivoice_{name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


voice_design = _load("voice_design")
lang_map = _load("lang_map")

# [gender, age, pitch, style, accents, dialects] — insertion-ordered dicts/sets from the engine.
CATEGORIES = voice_design._INSTRUCT_CATEGORIES
ZH_RE = voice_design._ZH_RE
EN_TO_ZH: dict[str, str] = voice_design._INSTRUCT_EN_TO_ZH
ZH_TO_EN: dict[str, str] = voice_design._INSTRUCT_ZH_TO_EN
VALID_TAGS: set[str] = voice_design._INSTRUCT_ALL_VALID
sanitize_instruct = voice_design.sanitize_instruct

# Category ids match the design picker's vd_states keys.
CATEGORY_ORDER = ("Gender", "Age", "Pitch", "Style", "EnglishAccent", "ChineseDialect")
CATEGORY_LABELS = {"Gender": "Gender", "Age": "Age", "Pitch": "Pitch", "Style": "Style",
                   "EnglishAccent": "English accent", "ChineseDialect": "Chinese dialect"}


def _english(tokens: object) -> list[str]:
    return [t for t in tokens if not ZH_RE.search(t)]  # type: ignore[attr-defined]


GENDERS = _english(CATEGORIES[0])
AGES = _english(CATEGORIES[1])
PITCHES = _english(CATEGORIES[2])
STYLES = _english(CATEGORIES[3])
ACCENTS = sorted(CATEGORIES[4])
DIALECTS = sorted(CATEGORIES[5])

CATEGORY_OPTIONS: dict[str, list[str]] = {
    "Gender": GENDERS, "Age": AGES, "Pitch": PITCHES, "Style": STYLES,
    "EnglishAccent": ACCENTS, "ChineseDialect": DIALECTS,
}

# Non-verbal tags the model renders as sounds when inlined in the text.
REACTION_TAGS = [
    "[laughter]", "[sigh]", "[confirmation-en]", "[question-en]", "[question-ah]", "[question-oh]",
    "[question-ei]", "[question-yi]", "[surprise-ah]", "[surprise-oh]", "[surprise-wa]", "[surprise-yo]",
    "[dissatisfaction-hnn]",
]


def instruct_from_states(states: dict[str, str] | None) -> str:
    """Validator-safe instruct from picker states (one tag per category, accent/dialect exclusive)."""
    if not states:
        return ""
    picks = [states.get(c, "Auto") for c in CATEGORY_ORDER]
    if states.get("ChineseDialect", "Auto") != "Auto":
        picks[CATEGORY_ORDER.index("EnglishAccent")] = "Auto"
    return str(voice_design._valid_instruct_from_items(p for p in picks if p != "Auto"))


def states_from_instruct(instruct: str | None) -> dict[str, str]:
    """Project a validator-token instruct onto the complete picker state (``Auto`` where unset)."""
    states = {c: "Auto" for c in CATEGORY_ORDER}
    cleaned = sanitize_instruct(instruct)
    if not cleaned:
        return states
    for token in cleaned.split(", "):
        index = voice_design._instruct_category_index(token)
        if 0 <= index < len(CATEGORY_ORDER):
            states[CATEGORY_ORDER[index]] = ZH_TO_EN.get(token, token)
    return states
