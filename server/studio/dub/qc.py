"""Second-pass ASR quality control (ported from VoiceStudio ``services/dub_qc.py``): re-recognise the dubbed track
and score each line's drift (token edit distance) against the text we asked the TTS to say. The generated
text stays authoritative — QC only measures and flags."""

from __future__ import annotations

import re

# Scripts written without spaces between words: CJK ideographs, kana, Thai,
# Lao, Myanmar and Khmer. ``\w+`` takes a whole clause of these as one token,
# so a single wrong character would score as total drift; each codepoint is
# a token there instead (a character error rate, as ASR is scored for them).
# Letters and marks only: the punctuation of these scripts (the katakana middle
# dot U+30FB, the ideographic full stop U+3002, the Thai fongman U+0E4F) is
# stripped like any other, and their digits stay word tokens.
_NO_SPACE_SCRIPT = (
    "\u3041-\u3096\u3099-\u309f"  # hiragana, its sound and iteration marks
    "\u30a1-\u30fa\u30fc-\u30ff"  # katakana, prolonged sound, iteration marks
    "\u3400-\u4dbf"  # CJK ideographs, extension A
    "\u4e00-\u9fff"  # CJK unified ideographs
    "\uf900-\ufaff"  # CJK compatibility ideographs
    "\uff66-\uff9f"  # halfwidth katakana
    "\U00020000-\U000323af"  # CJK ideographs, extensions B to I, compatibility supplement
    "\u0e01-\u0e3a\u0e40-\u0e4e"  # Thai letters, vowels, tone marks
    "\u0e81-\u0ece\u0edc-\u0edf"  # Lao letters, vowels, tone marks
    "\u1000-\u103f\u1050-\u108f\u109a-\u109d"  # Myanmar letters and marks
    "\u1780-\u17d3\u17d7\u17dc\u17dd"  # Khmer letters and marks
)
_TOKEN_RE = re.compile(rf"[{_NO_SPACE_SCRIPT}]|[^\W{_NO_SPACE_SCRIPT}]+")


def _tokens(text: str) -> list[str]:
    """Lowercase word tokens, punctuation stripped — the unit drift is scored
    in. Script-agnostic: for no-space scripts each codepoint is a token, which
    still gives a sensible edit-distance ratio."""
    text = (text or "").lower().strip()
    if not text:
        return []
    words = _TOKEN_RE.findall(text)
    return words or list(text.replace(" ", ""))


def _edit_distance(a: list[str], b: list[str]) -> int:
    """Levenshtein distance between two token lists (iterative, O(len(a)*len(b))
    time, O(len(b)) space)."""
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ta in enumerate(a, 1):
        cur = [i]
        for j, tb in enumerate(b, 1):
            cost = 0 if ta == tb else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[-1]


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Normalized token edit distance in [0.0, 1.0+].

    0.0 = the ASR heard exactly the target text. ~1.0 = entirely different.
    Can exceed 1.0 when the hypothesis is much longer than the reference
    (insertions); callers clamp/threshold as needed. An empty reference with a
    non-empty hypothesis scores 1.0 (everything is an insertion)."""
    ref = _tokens(reference)
    hyp = _tokens(hypothesis)
    if not ref and not hyp:
        return 0.0
    if not ref:
        return 1.0
    return _edit_distance(ref, hyp) / len(ref)


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def score(lines: list[dict], recognized: list[dict], threshold: float = 0.5) -> dict[str, dict]:
    """``lines``: {id, start, end, text} on the dub timeline; ``recognized``: ASR segments of the dubbed track.
    Returns ``{id: {drift, flagged, recognized}}``. With word timestamps each recognised word is attributed to
    the line its midpoint falls in (a recognised sentence spanning two lines no longer counts for both);
    without them, overlapping segments are concatenated (VoiceStudio behaviour)."""
    words = [w for r in recognized for w in r.get("words") or []]
    out: dict[str, dict] = {}
    for line in lines:
        s0, s1 = float(line["start"]), float(line["end"])
        if words:
            heard = " ".join(w["word"] for w in words if s0 <= (float(w["start"]) + float(w["end"])) / 2 <= s1)
        else:
            hits = [r for r in recognized if _overlap(s0, s1, float(r["start"]), float(r["end"])) > 0]
            heard = " ".join((r.get("text") or "").strip() for r in hits)
        heard = heard.strip()
        drift = round(word_error_rate(line.get("text") or "", heard), 3)
        out[str(line["id"])] = {"drift": drift, "flagged": drift >= threshold, "recognized": heard}
    return out
