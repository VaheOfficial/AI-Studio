"""Language tables for dub translation (ported from VoiceStudio ``api/routers/dub_translate.py`` and
``electron/src/shared/api/dialects.ts``): prompt names, required scripts and regional dialect hints."""

from __future__ import annotations

from ..voice import languages as voice_languages

# Full names for LLM prompts: small models misread bare ISO codes ("hi" reads as a greeting).
LANG_NAMES = {
    "en": "English", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian", "pt": "Portuguese",
    "ru": "Russian", "ja": "Japanese", "ko": "Korean", "zh": "Chinese (Simplified)", "zh-CN": "Chinese (Simplified)",
    "zh-TW": "Chinese (Traditional)", "yue": "Cantonese", "ar": "Arabic", "hi": "Hindi", "tr": "Turkish",
    "pl": "Polish", "nl": "Dutch", "sv": "Swedish", "th": "Thai", "vi": "Vietnamese", "id": "Indonesian",
    "uk": "Ukrainian", "bn": "Bengali", "ta": "Tamil", "te": "Telugu", "ml": "Malayalam", "kn": "Kannada",
    "gu": "Gujarati", "mr": "Marathi", "pa": "Punjabi", "ur": "Urdu", "fa": "Persian", "he": "Hebrew",
    "el": "Greek", "cs": "Czech", "da": "Danish", "fi": "Finnish", "no": "Norwegian", "nb": "Norwegian Bokmål",
    "ro": "Romanian", "hu": "Hungarian", "bg": "Bulgarian", "sk": "Slovak", "sl": "Slovenian", "hr": "Croatian",
    "sr": "Serbian", "lt": "Lithuanian", "lv": "Latvian", "et": "Estonian", "sw": "Swahili", "af": "Afrikaans",
    "ms": "Malay", "tl": "Tagalog", "ca": "Catalan", "eu": "Basque", "gl": "Galician",
}

# Required Unicode block per target: a translation with <50% letters in it is treated as wrong-language output.
LANG_REQUIRED_SCRIPT = {
    "hi": ("Devanagari", (0x0900, 0x097F)),
    "mr": ("Devanagari", (0x0900, 0x097F)),
    "bn": ("Bengali", (0x0980, 0x09FF)),
    "ar": ("Arabic", (0x0600, 0x06FF)),
    "arb": ("Arabic", (0x0600, 0x06FF)),
    "fa": ("Arabic", (0x0600, 0x06FF)),
    "ur": ("Arabic", (0x0600, 0x06FF)),
    "he": ("Hebrew", (0x0590, 0x05FF)),
    "zh": ("CJK", (0x4E00, 0x9FFF)),
    "cmn": ("CJK", (0x4E00, 0x9FFF)),
    "zh-CN": ("CJK", (0x4E00, 0x9FFF)),
    "zh-TW": ("CJK", (0x4E00, 0x9FFF)),
    "yue": ("CJK", (0x4E00, 0x9FFF)),
    "ja": ("Japanese kana/kanji", (0x3040, 0x9FFF)),
    "ko": ("Hangul", (0xAC00, 0xD7AF)),
    "th": ("Thai", (0x0E00, 0x0E7F)),
    "ru": ("Cyrillic", (0x0400, 0x04FF)),
    "uk": ("Cyrillic", (0x0400, 0x04FF)),
    "bg": ("Cyrillic", (0x0400, 0x04FF)),
    "sr": ("Cyrillic", (0x0400, 0x04FF)),
    "el": ("Greek", (0x0370, 0x03FF)),
    "ta": ("Tamil", (0x0B80, 0x0BFF)),
    "te": ("Telugu", (0x0C00, 0x0C7F)),
    "ml": ("Malayalam", (0x0D00, 0x0D7F)),
    "kn": ("Kannada", (0x0C80, 0x0CFF)),
    "gu": ("Gujarati", (0x0A80, 0x0AFF)),
    "pa": ("Gurmukhi", (0x0A00, 0x0A7F)),
}

DIALECT_HINTS = {
    "es-ES": "European Spanish (Spain): use tú/vosotros forms and Peninsular vocabulary.",
    "es-MX": "Mexican Spanish: use tú/ustedes forms and Mexican vocabulary.",
    "es-AR": ("Rioplatense Spanish (Argentina): use voseo — 'vos' with its verb forms (e.g. 'vos sos', 'tenés') "
              "and 'ustedes'; prefer Argentinian vocabulary."),
    "es-CO": "Colombian Spanish: use tú/usted as natural in Colombia and Colombian vocabulary.",
    "es-CL": "Chilean Spanish: use Chilean vocabulary and expressions.",
    "pt-BR": "Brazilian Portuguese: use 'você' forms, Brazilian vocabulary and spelling.",
    "pt-PT": "European Portuguese: use European vocabulary, spelling, and 'tu' where natural.",
    "en-US": "American English: use US spelling and vocabulary.",
    "en-GB": "British English: use UK spelling and vocabulary.",
    "en-AU": "Australian English: use Australian spelling and vocabulary.",
    "en-IN": "Indian English: use Indian English vocabulary and conventions.",
    "fr-FR": "Metropolitan French (France): use standard French vocabulary.",
    "fr-CA": "Canadian French (Québec): use Québécois vocabulary and expressions.",
    "fr-BE": "Belgian French: use Belgian vocabulary (e.g. septante, nonante).",
    "de-DE": "Standard German (Germany): use Federal German vocabulary.",
    "de-AT": "Austrian German: use Austrian vocabulary (e.g. Jänner, Erdapfel).",
    "de-CH": "Swiss Standard German: use Swiss vocabulary and 'ss' instead of 'ß'.",
    "ar-EG": "Egyptian Arabic: use Egyptian colloquial vocabulary where natural for dubbing.",
    "ar-SA": "Gulf/Saudi Arabic flavor: prefer vocabulary natural to the Gulf region.",
    "ar-MA": "Moroccan Arabic (Darija) flavor: prefer vocabulary natural to Morocco.",
    "nl-NL": "Netherlands Dutch: use vocabulary standard in the Netherlands.",
    "nl-BE": "Belgian Dutch (Flemish): use Flemish vocabulary and expressions.",
}


def base(code: str) -> str:
    return (code or "").split("-")[0].lower()


def name(code: str) -> str:
    """Full language name for prompts: curated names first, then the studio's 646-language catalog."""
    return LANG_NAMES.get(code) or voice_languages.name_of(code) or LANG_NAMES.get(base(code)) or code


def script_ratio(text: str, code: str) -> float:
    """Share of letters inside the target's required script (1.0 for Latin-script targets)."""
    info = LANG_REQUIRED_SCRIPT.get(code) or LANG_REQUIRED_SCRIPT.get(base(code))
    if not info:
        return 1.0
    lo, hi = info[1]
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 1.0
    return sum(1 for c in letters if lo <= ord(c) <= hi) / len(letters)


def looks_like_target(text: str, code: str, threshold: float = 0.5) -> bool:
    return script_ratio(text, code) >= threshold


def script_clause(code: str) -> str:
    info = LANG_REQUIRED_SCRIPT.get(code) or LANG_REQUIRED_SCRIPT.get(base(code))
    if not info:
        return ""
    return (f" The output MUST be written in {info[0]} script only — do not use Latin/Roman letters, do not "
            f"transliterate, do not output any other language.")


def dialect_clause(dialect: str | None, target: str) -> str:
    """Prompt fragment for a regional dialect of ``target`` ('' when unset or for another language)."""
    if not dialect or not target.lower().startswith(base(dialect)):  # 'ar-EG' belongs to Arabic ('arb')
        return ""
    hint = DIALECT_HINTS.get(dialect)
    if hint:
        return f" Target dialect — {hint}"
    lang, _, region = dialect.partition("-")
    return (f" Use the vocabulary, grammar, and expressions of {name(lang)} as spoken in the region '{region}'."
            if region else "")


def guess_from_text(texts: list[str]) -> str | None:
    """Best-effort source language by script (only when ASR detection is missing)."""
    text = " ".join(texts[:8])

    def has(lo: int, hi: int) -> bool:
        return any(lo <= ord(c) <= hi for c in text)

    for code, lo, hi in (("ja", 0x3040, 0x30FF), ("ko", 0xAC00, 0xD7A3), ("zh", 0x4E00, 0x9FFF),
                         ("ru", 0x0400, 0x04FF), ("ar", 0x0600, 0x06FF)):
        if has(lo, hi):
            return code
    return None


# ISO 639-1 → 639-2/T for container language tags (MP4 only stores three-letter codes).
_ISO639_2 = {
    "af": "afr", "am": "amh", "ar": "ara", "as": "asm", "az": "aze", "be": "bel", "bg": "bul", "bn": "ben",
    "bo": "bod", "bs": "bos", "ca": "cat", "cs": "ces", "cy": "cym", "da": "dan", "de": "deu", "el": "ell",
    "en": "eng", "eo": "epo", "es": "spa", "et": "est", "eu": "eus", "fa": "fas", "fi": "fin", "fo": "fao",
    "fr": "fra", "ga": "gle", "gl": "glg", "gu": "guj", "ha": "hau", "he": "heb", "hi": "hin", "hr": "hrv",
    "ht": "hat", "hu": "hun", "hy": "hye", "id": "ind", "ig": "ibo", "is": "isl", "it": "ita", "ja": "jpn",
    "jv": "jav", "ka": "kat", "kk": "kaz", "km": "khm", "kn": "kan", "ko": "kor", "ku": "kur", "ky": "kir",
    "la": "lat", "lb": "ltz", "lo": "lao", "lt": "lit", "lv": "lav", "mg": "mlg", "mi": "mri", "mk": "mkd",
    "ml": "mal", "mn": "mon", "mr": "mar", "ms": "msa", "mt": "mlt", "my": "mya", "nb": "nob", "ne": "nep",
    "nl": "nld", "nn": "nno", "no": "nor", "ny": "nya", "or": "ori", "pa": "pan", "pl": "pol", "ps": "pus",
    "pt": "por", "ro": "ron", "ru": "rus", "rw": "kin", "sd": "snd", "si": "sin", "sk": "slk", "sl": "slv",
    "sn": "sna", "so": "som", "sq": "sqi", "sr": "srp", "su": "sun", "sv": "swe", "sw": "swa", "ta": "tam",
    "te": "tel", "tg": "tgk", "th": "tha", "tk": "tuk", "tl": "tgl", "tr": "tur", "tt": "tat", "ug": "uig",
    "uk": "ukr", "ur": "urd", "uz": "uzb", "vi": "vie", "xh": "xho", "yi": "yid", "yo": "yor", "zh": "zho",
    "zu": "zul",
}


def iso639_2(code: str) -> str:
    b = base(code)
    return _ISO639_2.get(b) or (b if len(b) == 3 and b.isalpha() else "und")

