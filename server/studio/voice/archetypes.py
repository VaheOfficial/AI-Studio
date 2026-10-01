"""Designed-voice archetypes for the gallery, and the personality presets of the Design page.

Ported from VoiceStudio ``backend/core/archetypes.py`` and ``personalities.py``. No real people, no
cloning: each archetype is an ``instruct`` built from the engine's own design vocabulary.

* **Featured** — hand-curated personas across seven use cases, plus neutral narrator / explainer /
  companion roles in nine more languages (the spoken language comes from the preview text; accents are
  English-only and dialects Chinese-only, so those carry gender/age/pitch only).
* **Generated** — gender × age × pitch × {neutral + accents} (English, plus whisper variants) and
  gender × age × pitch × dialect (Chinese), pruned of implausible combinations ("child + very low pitch").
"""

from __future__ import annotations

import hashlib

from ..schemas_voice import Archetype, Personality, UseCase
from . import languages
from .taxonomy import ACCENTS, AGES, CATEGORY_ORDER, DIALECTS, GENDERS, PITCHES, states_from_instruct

USE_CASES = [
    UseCase(id="narration", name="Narration & Story"),
    UseCase(id="conversational", name="Conversational"),
    UseCase(id="characters", name="Characters & Animation"),
    UseCase(id="social", name="Social Media"),
    UseCase(id="entertainment", name="Entertainment & TV"),
    UseCase(id="advertisement", name="Advertisement"),
    UseCase(id="informative", name="Informative & Educational"),
]

_SCRIPTS = {
    "narration": ("The valley had been quiet for a hundred years, and tonight, for the first time, something "
                  "stirred beneath the old stone bridge."),
    "conversational": ("Oh hey, I didn't expect to run into you here! How have you been? We should really catch up "
                       "properly one of these days."),
    "characters": "You think you can stop me? Ha! I have crossed oceans of time and bent whole kingdoms to my will.",
    "social": ("What is up, everyone, welcome back to the channel! Today we are trying something I have honestly "
               "never done before."),
    "entertainment": ("Good evening, and welcome. Tonight's top story is one you will not want to miss, so stay right "
                      "there — we'll be back after this."),
    "advertisement": ("Introducing a whole new way to get more done in less time. Available today. Your best work "
                      "starts right now."),
    "informative": ("Let's break this down simply. There are three things you need to know, and the very first one "
                    "surprises most people."),
}
# Demo text for previewing Chinese-dialect voices.
_ZH_SAMPLE = "大家好，欢迎来到这个声音示范，希望你会喜欢这一段简单的朗读。"

_PRUNE = {"child": {"very low pitch", "low pitch"}, "teenager": {"very low pitch"}, "elderly": {"very high pitch"}}


def _whisper_ok(age: str, pitch: str) -> bool:
    return age in {"young adult", "middle-aged", "elderly"} and pitch in {"low pitch", "moderate pitch"}


def _use_case(age: str, pitch: str, accent: str | None) -> str:
    if age in ("child", "teenager") or pitch == "very high pitch":
        return "characters"
    if pitch in ("very low pitch", "low pitch") and age in ("middle-aged", "elderly"):
        return "narration"
    if pitch == "high pitch" and age == "young adult":
        return "social"
    if accent is None and age == "middle-aged" and pitch == "moderate pitch":
        return "informative"
    return {"young adult": "conversational", "elderly": "entertainment", "middle-aged": "advertisement"}.get(
        age, "conversational")


def _auto_name(gender: str, age: str, pitch: str, accent: str | None, dialect: str | None, whisper: bool) -> str:
    place = accent.replace(" accent", "").title() if accent else (dialect or "Neutral")
    name = " · ".join([place, gender.title(), age.title(), pitch.replace(" pitch", "").title()])
    return f"{name} · Whisper" if whisper else name


def _build(gender: str | None, age: str | None, pitch: str | None, *, accent: str | None = None,
           dialect: str | None = None, whisper: bool = False, use_case: str, name: str, language: str,
           script: str | None = None, fid: str | None = None) -> Archetype:
    tokens = [t for t in (gender, age, pitch, "whisper" if whisper else None, accent, dialect) if t]
    instruct = ", ".join(tokens)
    lang_id = languages.id_for_name(language)
    aid = fid or "a_" + hashlib.sha256(f"{instruct}|{language}".encode()).hexdigest()[:10]
    picks = {"Gender": gender, "Age": age, "Pitch": pitch, "Style": "whisper" if whisper else None,
             "EnglishAccent": accent, "ChineseDialect": dialect}
    return Archetype(
        id=aid, name=name, use_case=use_case, instruct=instruct,
        attrs={c: picks[c] or "Auto" for c in CATEGORY_ORDER},
        gender=gender, age=age, pitch=pitch, accent=accent or dialect, whisper=whisper,
        language=lang_id, language_name=language,
        sample_script=script or (_ZH_SAMPLE if language == "Chinese" else _SCRIPTS[use_case]),
        featured=fid is not None,
    )


# (gender, age, pitch, accent, whisper, use_case, name)
_FEATURED_SPEC: list[tuple[str | None, str, str, str | None, bool, str, str]] = [
    ("female", "middle-aged", "low pitch", "british accent", False, "narration", "The Librarian"),
    ("male", "middle-aged", "low pitch", "american accent", False, "narration", "The Documentarian"),
    ("female", "middle-aged", "low pitch", None, True, "narration", "The Calm Guide"),
    ("male", "elderly", "low pitch", "british accent", False, "narration", "The Storyteller"),
    ("female", "young adult", "moderate pitch", "american accent", False, "conversational", "The Neighbor"),
    ("female", "young adult", "moderate pitch", "indian accent", False, "conversational", "The Helpdesk"),
    ("male", "young adult", "moderate pitch", "australian accent", False, "conversational", "The Mate"),
    ("female", "middle-aged", "moderate pitch", "canadian accent", False, "conversational", "The Companion"),
    ("male", "elderly", "very low pitch", None, False, "characters", "Captain Crusty"),
    (None, "teenager", "high pitch", None, False, "characters", "Junior Quacks"),
    ("male", "young adult", "high pitch", "american accent", False, "characters", "The Champion"),
    ("female", "child", "very high pitch", None, False, "characters", "The Pixie"),
    ("male", "middle-aged", "very low pitch", None, False, "characters", "The Ogre"),
    ("female", "young adult", "high pitch", "australian accent", False, "social", "The Podcaster"),
    ("male", "young adult", "very high pitch", "american accent", False, "social", "The Hype Host"),
    ("female", "young adult", "high pitch", None, False, "social", "The Vlogger"),
    ("male", "middle-aged", "moderate pitch", "american accent", False, "entertainment", "The Anchor"),
    ("male", "middle-aged", "high pitch", "british accent", False, "entertainment", "The Commentator"),
    ("male", "middle-aged", "moderate pitch", None, False, "entertainment", "The Game Host"),
    ("male", "middle-aged", "low pitch", None, False, "advertisement", "The Promo Voice"),
    ("female", "middle-aged", "moderate pitch", "british accent", False, "advertisement", "The Luxe"),
    ("female", "young adult", "high pitch", "american accent", False, "advertisement", "The Upbeat"),
    ("female", "middle-aged", "moderate pitch", "american accent", False, "informative", "The Teacher"),
    ("male", "young adult", "moderate pitch", "british accent", False, "informative", "The Explainer"),
]

_ML_SAMPLES = {
    "Spanish": "Hola y bienvenido a esta breve demostración de voz. Espero que disfrutes escuchando cómo suena.",
    "French": "Bonjour et bienvenue dans cette courte démonstration vocale. J'espère que cette voix vous plaira.",
    "German": "Hallo und willkommen zu dieser kurzen Sprachdemo. Ich hoffe, diese Stimme gefällt dir.",
    "Italian": "Ciao e benvenuto in questa breve dimostrazione vocale. Spero che questa voce ti piaccia.",
    "Portuguese": "Olá e bem-vindo a esta breve demonstração de voz. Espero que goste de ouvir como ela soa.",
    "Russian": ("Здравствуйте и добро пожаловать в эту короткую демонстрацию голоса. Надеюсь, вам понравится, "
                "как он звучит."),
    "Hindi": "नमस्ते और इस छोटे से वॉइस डेमो में आपका स्वागत है। मुझे आशा है कि आपको यह आवाज़ पसंद आएगी।",
    "Japanese": "こんにちは。この短い音声デモへようこそ。この声を気に入っていただけるとうれしいです。",
    "Korean": "안녕하세요. 이 짧은 음성 데모에 오신 것을 환영합니다. 이 목소리가 마음에 드시길 바랍니다.",
}
_ML_ROLES = [
    ("female", "middle-aged", "low pitch", "narration", "Narrator"),
    ("male", "young adult", "moderate pitch", "informative", "Explainer"),
    ("female", "young adult", "moderate pitch", "conversational", "Companion"),
]


def _featured() -> list[Archetype]:
    out = [
        _build(g, a, p, accent=acc, whisper=w, use_case=uc, name=name, language="English",
               fid=f"feat_{i:02d}_{name.lower().replace(' ', '_')}")
        for i, (g, a, p, acc, w, uc, name) in enumerate(_FEATURED_SPEC)
    ]
    for language, script in _ML_SAMPLES.items():
        for g, a, p, uc, role in _ML_ROLES:
            out.append(_build(g, a, p, use_case=uc, name=f"{language} {role}", language=language, script=script,
                              fid=f"ml_{language.lower()}_{role.lower()}"))
    return out


def _generated(seen: set[tuple[str, str]]) -> list[Archetype]:
    out: list[Archetype] = []

    def add(a: Archetype) -> None:
        key = (a.instruct, a.language)
        if key not in seen:
            seen.add(key)
            out.append(a)

    for gender in GENDERS:
        for age in AGES:
            for pitch in PITCHES:
                if pitch in _PRUNE.get(age, ()):
                    continue
                for accent in [None, *ACCENTS]:
                    uc = _use_case(age, pitch, accent)
                    add(_build(gender, age, pitch, accent=accent, use_case=uc, language="English",
                               name=_auto_name(gender, age, pitch, accent, None, False)))
                    if _whisper_ok(age, pitch):
                        add(_build(gender, age, pitch, accent=accent, whisper=True, use_case="narration",
                                   language="English", name=_auto_name(gender, age, pitch, accent, None, True)))
                for dialect in DIALECTS:
                    add(_build(gender, age, pitch, dialect=dialect, use_case=_use_case(age, pitch, None),
                               language="Chinese", name=_auto_name(gender, age, pitch, None, dialect, False)))
    return out


_FEATURED = _featured()
ALL: list[Archetype] = _FEATURED + _generated({(a.instruct, a.language) for a in _FEATURED})
_BY_ID = {a.id: a for a in ALL}


def get(archetype_id: str) -> Archetype | None:
    return _BY_ID.get(archetype_id)


def search(q: str | None = None, use_case: str | None = None, gender: str | None = None, age: str | None = None,
           pitch: str | None = None, accent: str | None = None, whisper: bool | None = None,
           language: str | None = None, featured: bool | None = None) -> list[Archetype]:
    """Filtered view of the catalog; ``q`` matches name or instruct (case-insensitive)."""
    needle = (q or "").strip().lower()
    return [
        a for a in ALL
        if (not needle or needle in a.name.lower() or needle in a.instruct.lower())
        and (use_case is None or a.use_case == use_case) and (gender is None or a.gender == gender)
        and (age is None or a.age == age) and (pitch is None or a.pitch == pitch)
        and (accent is None or a.accent == accent) and (whisper is None or a.whisper is whisper)
        and (language is None or a.language == language) and (featured is None or a.featured is featured)
    ]


# ------------------------- personality presets (Design page) -------------------------

_PERSONALITIES = [
    ("narrator", "Narrator", "middle-aged, low pitch", "Calm, authoritative documentary narrator"),
    ("casual", "Casual", "young adult, moderate pitch", "Relaxed, conversational, like talking to a friend"),
    ("news_anchor", "News anchor", "middle-aged, moderate pitch, american accent",
     "Clear, professional television news presenter"),
    ("storyteller", "Storyteller", "middle-aged, moderate pitch, british accent",
     "Engaging pacing, like reading a bedtime story"),
    ("corporate", "Corporate", "middle-aged, moderate pitch", "Polished tone for business presentations"),
    ("energetic", "Energetic", "young adult, high pitch", "High energy, like a podcast host"),
]
PERSONALITIES = [Personality(id=pid, name=name, instruct=instruct, attrs=states_from_instruct(instruct),
                             description=desc) for pid, name, instruct, desc in _PERSONALITIES]
