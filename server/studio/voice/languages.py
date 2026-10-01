"""Speech languages: OmniVoice's 646 (ISO 639 ids from its lang_map) and what each TTS engine supports."""

from __future__ import annotations

from functools import cache

from ..schemas_voice import Language, LanguageCatalog
from .taxonomy import lang_map

POPULAR = ["en", "zh", "es", "fr", "de", "it", "pt", "ru", "ja", "ko", "arb", "hi", "yue"]

# None = every language OmniVoice knows. Kokoro exposes English voices only (misaki[en]); Chatterbox is English.
ENGINE_LANGUAGES: dict[str, list[str] | None] = {"omnivoice": None, "kokoro": ["en"], "chatterbox": ["en"]}


@cache
def catalog() -> LanguageCatalog:
    names: dict[str, str] = lang_map.LANG_NAME_TO_ID
    languages = sorted((Language(id=code, name=lang_map.lang_display_name(name)) for name, code in names.items()),
                       key=lambda lang: lang.name.casefold())
    return LanguageCatalog(languages=languages, popular=POPULAR, engines=ENGINE_LANGUAGES)


def name_of(language_id: str | None) -> str | None:
    if not language_id:
        return None
    return next((lang.name for lang in catalog().languages if lang.id == language_id), None)


def id_for_name(name: str) -> str:
    """Language id for a display name ("English" -> "en")."""
    return str(lang_map.LANG_NAME_TO_ID[name.lower()])


def is_known(language_id: str) -> bool:
    return language_id in lang_map.LANG_IDS


def supports(runtime: str, language_id: str | None) -> bool:
    allowed = ENGINE_LANGUAGES.get(runtime)
    return not language_id or allowed is None or language_id in allowed
