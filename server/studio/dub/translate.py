"""Dub translation: LLM (studio chat providers) or NLLB, then quality passes and pre-synthesis timing plans.

Ported from VoiceStudio ``api/routers/dub_translate.py`` (direct translation prompt + script gate + retry),
``services/translation_quality.py`` (auto-glossary context pass, reflect critique→polish),
``services/translator.py`` (cinematic REFLECT→ADAPT for MT output, divergence guard ``refine_output_ok``),
``services/speech_rate.py`` (chars/sec model, Autofit TRIM/EXPAND loop, measured agent-fit rewrite) and
``services/duration_planner.py`` (calibrated fits/tight/impossible verdicts, opt-in CONDENSE suggestions).
Every refinement is best-effort: a failure keeps the previous text and is reported per row, never raised.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Callable, Iterable
from concurrent.futures import Future, wait
from dataclasses import dataclass
from typing import Any

from . import languages as L
from .fit_planner import MAX_AUDIO_RATE_HARD, FitParams
from .llm import Chat, LLMError, pool

BUDGET_S = 600.0  # wall-clock cap for the refinement phase of one language (VoiceStudio: 180 s cloud default)
GLOSSARY_MAX_CHARS = 12000

# ------------------------------------------------------------------ prompts

_TRANSLATE_PROMPT = ("You are a professional dubbing translator. Translate the user's text from {src} into {tgt}."
                     "{script}{dialect} {brief} Reply ONLY with the translated {tgt} text, do not add quotes, notes, "
                     "headers, explanations, or commentary.")

_CONTEXT_PROMPT = """\
You are a dubbing terminology editor preparing a translation brief. The user
gives you the full source-language transcript of one video. Reply in this
exact plain-text format (no JSON, no code fences, no commentary):

THEME: one or two sentences — what the video is about, its register
(casual / formal / technical) and audience.
TERM: SOURCE || TARGET
TERM: SOURCE || TARGET

TERM lines list proper nouns (people, places, brands, product names) and
recurring domain terms that must be translated identically every time, each
with your preferred {target_name} rendering. At most {max_terms} TERM lines;
fewer is better. Skip one-off words and anything trivially consistent."""

_REVIEW_PROMPT = """\
You are a dubbing script reviewer. The user gives you a source line and its
draft {target_name} translation. In 1-2 short sentences, point out where the
draft is wordy, stiff, or uses a register nobody would use in spoken
dialogue, and whether recurring terms follow the brief. If the draft already
sounds natural, say so. Reply ONLY with the critique — no headers, no lists,
no code fences."""

_POLISH_PROMPT = """\
You are a dubbing script writer. Rewrite the draft translation using the
reviewer's notes so it reads like natural spoken {target_name}. Keep the
meaning faithful to the source line, keep required terminology, and never add
content that is not in the source. Prefer the same length or shorter than the
draft. The output MUST stay in the same language and script as the draft —
never switch language or transliterate. Reply ONLY with the final translation
— no quotes, no notes, no commentary."""

_REFLECT_PROMPT = """\
You are a professional dubbing script editor. The user will give you a source
line and its literal translation. Critique the literal translation in 2-3
crisp sentences, focusing on:
- natural idiom in the target language
- emotional tone (does it match what the speaker would convey?)
- length (will it fit in the same time slot as the source?)
- any proper nouns or recurring terms that should stay consistent
Reply ONLY with the critique — no headers, no bullet points, no code fences."""

_ADAPT_PROMPT = """\
You are a cinematic dubbing writer. Rewrite the literal translation using the
editor's critique so it sounds natural, in-character, and fits the speaker's
time slot. Keep meaning faithful but prefer native idiom over word-for-word
accuracy. Never introduce facts, names, or dialogue that are not present in
the source line. The output MUST be written in the same target language and
script as the literal translation — never switch language or transliterate.
Reply ONLY with the adapted translation — no quotes, no headers, no code
fences, no commentary."""

_TRIM_PROMPT = """\
You are a dubbing writer. The user will give you a translated line + the exact
time slot it must fit. The current line is TOO LONG — trim filler words,
tighten phrasing, or drop less essential clauses while preserving the meaning.
Never change character names or proper nouns.
Reply with ONLY the new line. No quotes, no commentary."""

_EXPAND_PROMPT = """\
You are a dubbing writer. The user will give you a translated line + the exact
time slot it must fit. The current line is TOO SHORT — add natural filler or
gently flesh out the thought while keeping the meaning the same. Aim for a
reading duration that matches the slot. Never invent new information, names,
or dialogue that is not already in the line; do not more than double the line.
Reply with ONLY the new line. No quotes, no commentary."""

_MEASURED_PROMPT = """\
You are a dialogue adaptation agent for precise dubbing. Rewrite the translated
line so the SAME voice can speak it inside the exact target duration. The user
provides the duration measured from a real render, so use the requested length
change as a concrete constraint. Preserve meaning, tone, names, numbers,
technical terms, and the target language. Shorten natural phrasing when long;
gently expand only when short without inventing facts or dialogue.
Reply with ONLY the revised line. No quotes or commentary."""

_CONDENSE_PROMPT = """\
You are a dubbing writer. The user will give you a translated line that is
TOO LONG for its time slot. Rewrite it shorter so it can be read aloud
within the target duration: cut filler words, tighten phrasing, and drop
the least essential clauses — but preserve the meaning. Never change
character names, proper nouns, numbers, or technical terms. Stay in the
same language as the line.
Reply with ONLY the rewritten line. No quotes, no commentary."""

_AUTO_EXTRACT_PROMPT = """\
You are a dubbing terminology editor. The user gives you source-language
segments from a video. Identify proper nouns (character names, places,
brands, organisations) and recurring technical / domain-specific terms that
MUST be translated consistently.

For each term, propose a target-language translation. Omit common nouns,
filler words, and anything that's already trivially consistent. Omit entries
that are identical in both languages UNLESS the source is a proper noun that
should be preserved verbatim.

Reply with ONE entry per line in this exact format (no preamble, no JSON, no
numbering, no quotes):

SOURCE || TARGET || one-line note (or empty)

Keep the list to at most {max_terms} entries. Prefer shorter is better."""

# ------------------------------------------------------------------ speech rate (speech_rate.py)

# Chars/sec at natural pace (codepoints). Indic scripts count vowel marks as separate codepoints.
_RATE_CPS = {
    "en": 15.0, "de": 14.0, "fr": 15.0, "es": 15.5, "it": 15.0, "pt": 15.0, "ja": 10.0, "ko": 10.0, "zh": 6.0,
    "hi": 17.0, "bn": 17.0, "ta": 14.0, "te": 14.0, "mr": 16.0, "gu": 16.0, "kn": 14.0, "ml": 14.0, "pa": 16.0,
    "or": 16.0, "ur": 13.0, "ar": 12.0, "he": 12.0, "fa": 13.0, "th": 10.0, "vi": 16.0, "id": 14.0, "ms": 14.0,
    "ru": 13.0, "pl": 13.0, "uk": 13.0, "cs": 13.0, "tr": 12.0, "el": 14.0, "nl": 14.0, "sv": 14.0, "no": 14.0,
    "da": 14.0, "fi": 13.0,
}
TOL_LOW, TOL_HIGH = 0.92, 1.08
MEASURED_TOL_LOW, MEASURED_TOL_HIGH = 0.9, 1.04
_MIN_EXPANDABLE_RATIO = 0.15
_FIT_ATTEMPTS = 3


def expected_duration(text: str, lang: str) -> float:
    return len(text) / max(1.0, _RATE_CPS.get(L.base(lang), 13.0))


def rate_ratio(text: str, slot: float, lang: str) -> float:
    return expected_duration(text, lang) / slot if slot > 0 else 1.0


# ------------------------------------------------------------------ divergence guard (translator.py)


def _echoes_critique(candidate: str, critique: str) -> bool:
    c, k = " ".join(candidate.lower().split()), " ".join(critique.lower().split())
    if not c or not k:
        return False
    if c == k or k in c or (c in k and len(c) >= 0.6 * len(k)):
        return True
    ct, kt = set(c.split()), set(k.split())
    return bool(ct | kt) and len(ct & kt) / len(ct | kt) > 0.8


def refine_output_ok(reference: str, candidate: str, target: str, *, critique: str | None = None
                     ) -> tuple[bool, str | None]:
    """Reject LLM rewrites that switched script, ran away in length (0.4–2.5×, or +120 chars for short
    references) or echoed the critique back instead of the line."""
    cand, ref = (candidate or "").strip(), (reference or "").strip()
    if not cand:
        return False, "empty"
    if not L.looks_like_target(cand, target):
        return False, f"wrong-script:{target}"
    if ref:
        if len(ref) < 20:
            if len(cand) > len(ref) + 120:
                return False, "length-abs"
        elif not 0.4 <= len(cand) / len(ref) <= 2.5:
            return False, f"length-ratio:{len(cand) / len(ref):.2f}"
    if critique and _echoes_critique(cand, critique):
        return False, "critique-echo"
    return True, None


# ------------------------------------------------------------------ duration planner (duration_planner.py)

GAP_BORROW_MAX_S = 3.0


def calibrate_cps(samples: Iterable[tuple[float, float]]) -> float | None:
    """Median chars/sec of ≥3 already-synthesized segments (≥0.4 s, ≥4 chars) — beats the static table."""
    rates = sorted(c / d for c, d in samples if d >= 0.4 and c >= 4)
    if len(rates) < 3:
        return None
    mid = len(rates) // 2
    return rates[mid] if len(rates) % 2 else (rates[mid - 1] + rates[mid]) / 2


def estimate(text: str, lang: str, cps: float | None) -> float:
    text = (text or "").strip()
    if not text:
        return 0.0
    return len(text) / cps if cps else expected_duration(text, lang)


def classify(segments: list[dict], lang: str, *, cps: float | None, total_s: float,
             params: FitParams | None = None) -> dict[str, dict]:
    """``{id: {status, est_s, available_s, overrun_s, calibrated}}`` — fits ≤1.2×, tight ≤ what the fit caps
    absorb (audio cap × video cap), impossible beyond. ``segments`` are chronological {id,start,end,text}."""
    params = params or FitParams()
    fits_cap = params.max_audio_only_rate
    cap = params.audio_rate_cap * params.video_slow_cap if params.allow_video_retime else MAX_AUDIO_RATE_HARD
    out: dict[str, dict] = {}
    for i, seg in enumerate(segments):
        start, end = float(seg["start"]), float(seg["end"])
        if i + 1 < len(segments):
            gap = max(0.0, float(segments[i + 1]["start"]) - end)
            borrow = min(max(0.0, gap - params.gap_guard_s), GAP_BORROW_MAX_S)
        else:
            borrow = min(max(0.0, total_s - end), GAP_BORROW_MAX_S) if total_s > 0 else 0.0
        available = max(0.0, end - start) + borrow
        est = estimate(seg.get("text") or "", lang, cps)
        if est <= 0:
            status, overrun = "fits", 0.0
        elif available <= 0:
            status, overrun = "impossible", est
        else:
            need = est / available
            status = "fits" if need <= fits_cap + 1e-9 else "tight" if need <= cap + 1e-9 else "impossible"
            overrun = max(0.0, est - available)
        out[str(seg["id"])] = {"status": status, "est_s": round(est, 3), "available_s": round(available, 3),
                               "overrun_s": round(overrun, 3), "calibrated": cps is not None}
    return out


# ------------------------------------------------------------------ options / rows


@dataclass
class Options:
    engine: str  # "llm" | "nllb"
    model: str | None  # chat model id; for NLLB it powers cinematic/autofit/agent/condense
    nllb_repo: str
    quality: str  # fast | cinematic | autofit | agent
    auto_glossary: bool
    reflect: bool
    condense: bool
    dialect: str | None
    instructions: str


@dataclass
class SegIn:
    id: str
    text: str
    start: float
    end: float
    direction: str | None = None


Progress = Callable[[str, float], None]


def style_brief(instructions: str) -> str:
    text = (instructions or "").strip()
    return ("User translation style brief (tone and wording only; preserve meaning, timing and output format): "
            + json.dumps(text, ensure_ascii=False)) if text else ""


def glossary_text(terms: Iterable[dict]) -> str:
    lines = [f"- {t['source']} → {t['target']}" + (f"  (note: {t['note']})" if t.get("note") else "")
             for t in terms if t.get("source") and t.get("target")]
    return ("Terminology — render every occurrence of a source term exactly as its target:\n" + "\n".join(lines)
            if lines else "")


def merge_glossary(user_terms: Iterable[dict], auto_terms: Iterable[dict]) -> list[dict]:
    """User entries always win (case-insensitive source match)."""
    merged, seen = [], set()
    for t in list(user_terms) + list(auto_terms):
        src, tgt = (t.get("source") or "").strip(), (t.get("target") or "").strip()
        if src and tgt and src.lower() not in seen:
            merged.append({"source": src, "target": tgt, "note": t.get("note") or ""})
            seen.add(src.lower())
    return merged


def transcript_fingerprint(texts: Iterable[str]) -> str:
    h = hashlib.sha256()
    for t in texts:
        h.update((t or "").strip().encode("utf-8", errors="replace") + b"\x00")
    return h.hexdigest()[:16]


def extract_context(chat: Chat, texts: list[str], src: str, tgt: str, max_terms: int = 30) -> dict | None:
    """Auto-glossary pass: THEME + TERM lines over the whole transcript (never a hard failure)."""
    body = "\n".join(t.strip() for t in texts if t and t.strip())
    if not body:
        return None
    if len(body) > GLOSSARY_MAX_CHARS:
        body = body[:GLOSSARY_MAX_CHARS] + "\n…[truncated]"
    try:
        reply = chat(_CONTEXT_PROMPT.format(target_name=L.name(tgt), max_terms=max_terms),
                     f"Source language: {L.name(src)}\nTarget language: {L.name(tgt)}\nTranscript:\n{body}")
    except LLMError:
        return None
    theme, terms = "", []
    for line in reply.splitlines():
        line = line.strip()
        if line.upper().startswith("THEME:"):
            theme = line[6:].strip()
            continue
        if line.upper().startswith("TERM:"):
            line = line[5:].strip()
        parts = [p.strip() for p in line.split("||")] if "||" in line else []
        if len(parts) >= 2 and parts[0] and parts[1]:
            terms.append({"source": parts[0], "target": parts[1]})
            if len(terms) >= max_terms:
                break
    return {"theme": theme, "terms": terms} if theme or terms else None


def auto_extract_glossary(chat: Chat, texts: list[str], src: str, tgt: str, max_terms: int = 40) -> list[dict]:
    body = "\n".join(t.strip() for t in texts if t and t.strip())[:GLOSSARY_MAX_CHARS]
    reply = chat(_AUTO_EXTRACT_PROMPT.format(max_terms=max_terms),
                 f"Source language: {L.name(src)}\nTarget language: {L.name(tgt)}\nSegments:\n{body}")
    out = []
    for line in reply.splitlines():
        parts = [p.strip() for p in line.split("||")]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            continue
        if parts[0] == parts[1] and " " in parts[0]:
            continue  # a multi-word identity is not terminology
        out.append({"source": parts[0], "target": parts[1], "note": parts[2] if len(parts) > 2 else ""})
    return out[:max_terms]


# ------------------------------------------------------------------ per-segment passes


def _direct(chat: Chat, seg: SegIn, src: str, tgt: str, system: str) -> dict:
    """Direct LLM translation with the script gate; one emphatic retry on wrong-script output."""
    last = "llm-failed"
    for attempt in range(2):
        sys_prompt = system if attempt == 0 else (
            system + f" Your previous attempt produced output in the wrong language or script. Output ONLY the "
                     f"{L.name(tgt)} translation.")
        try:
            out = chat(sys_prompt, seg.text)
        except LLMError as exc:
            last = str(exc)[:300]
            continue
        if not out:
            last = "empty LLM response"
            continue
        if not L.looks_like_target(out, tgt):
            last = f"wrong script (ratio {L.script_ratio(out, tgt):.2f})"
            continue
        return {"id": seg.id, "text": out}
    return {"id": seg.id, "text": seg.text, "error": last}


def _reflect(chat: Chat, source: str, draft: str, src: str, tgt: str, extra: str) -> str | None:
    def with_extra(base: str) -> str:
        return base + ("\n\n" + extra if extra.strip() else "")

    review_user = f"Source ({src}): {source}\nDraft translation ({tgt}): {draft}"
    try:
        critique = chat(with_extra(_REVIEW_PROMPT.format(target_name=L.name(tgt))), review_user)
        polished = chat(with_extra(_POLISH_PROMPT.format(target_name=L.name(tgt))),
                        review_user + f"\nReviewer's notes: {critique}")
    except LLMError:
        return None
    if not polished or polished == draft:
        return None
    ok, _ = refine_output_ok(draft, polished, tgt, critique=critique)
    return polished if ok else None


def _cinematic(chat: Chat, source: str, literal: str, src: str, tgt: str, extra: str) -> dict:
    """REFLECT → ADAPT over an MT literal; a diverged adaptation keeps the literal (``degraded``)."""
    def with_extra(base: str) -> str:
        return base + ("\n\n" + extra if extra.strip() else "")

    user = f"Source ({src}): {source}\nLiteral translation ({tgt}): {literal}"
    try:
        critique = chat(with_extra(_REFLECT_PROMPT), user)
    except LLMError as exc:
        return {"text": literal, "literal": literal, "degraded": f"reflect: {exc}"[:200]}
    try:
        adapted = chat(with_extra(_ADAPT_PROMPT), user + f"\nEditor's critique: {critique}") or literal
    except LLMError as exc:
        return {"text": literal, "literal": literal, "critique": critique, "degraded": f"adapt: {exc}"[:200]}
    ok, reason = refine_output_ok(literal, adapted, tgt, critique=critique)
    if not ok:
        wrong = (reason or "").startswith("wrong-script")
        return {"text": literal, "literal": literal, "critique": critique,
                "degraded": f"adapt-wrong-script:{tgt}" if wrong else "adapt-diverged"}
    return {"text": adapted, "literal": literal, "critique": critique}


def adjust_for_slot(chat: Chat, text: str, slot: float, tgt: str, source: str | None, strict: bool) -> dict:
    """Autofit: TRIM/EXPAND until the predicted ratio is inside [0.92, 1.08] (strict: [0.92, 1.0])."""
    tol_high = 1.0 if strict else TOL_HIGH
    initial = rate_ratio(text, slot, tgt)
    if TOL_LOW <= initial <= tol_high:
        return {"text": text, "rate_ratio": initial}
    if initial < _MIN_EXPANDABLE_RATIO:
        return {"text": text, "rate_ratio": initial, "error": "fit-skip-short"}
    current, best, diverged = text, (text, initial), False
    for _ in range(_FIT_ATTEMPTS):
        r = rate_ratio(current, slot, tgt)
        if TOL_LOW <= r <= tol_high:
            return {"text": current, "rate_ratio": r}
        lines = [f"Target language: {L.name(tgt)}", f"Slot: {slot:.2f}s", f"Current line: {current}",
                 f"Current reading duration: ~{expected_duration(current, tgt):.2f}s (ratio {r:.2f})"]
        if source:
            lines.append(f"Source line (for meaning): {source}")
        try:
            candidate = chat(_TRIM_PROMPT if r > 1.0 else _EXPAND_PROMPT, "\n".join(lines))
        except LLMError:
            return {"text": best[0], "rate_ratio": best[1], "error": "fit-provider-failed"}
        if not candidate:
            continue
        ok, _ = refine_output_ok(text, candidate, tgt)  # always against the ORIGINAL (no compounding drift)
        if not ok:
            diverged = True
            continue
        current = candidate
        new_r = rate_ratio(current, slot, tgt)
        if abs(new_r - 1.0) < abs(best[1] - 1.0):
            best = (current, new_r)
    out: dict[str, Any] = {"text": best[0], "rate_ratio": best[1]}
    if diverged and best[0] == text:
        out["error"] = "fit-diverged"
    return out


def adjust_for_measured(chat: Chat, text: str, *, slot: float, measured: float, tgt: str, source: str | None,
                        before: str | None, after: str | None, instructions: str) -> dict:
    """Agent mode: one evidence-based rewrite from a real render's measured duration."""
    ratio = measured / slot if slot else 1.0
    base = {"text": text, "changed": False, "measured_ratio": round(ratio, 3)}
    if not text or slot <= 0 or measured <= 0:
        return {**base, "error": "invalid-timing"}
    if MEASURED_TOL_LOW <= ratio <= MEASURED_TOL_HIGH:
        return {**base, "error": "already-fits"}
    if ratio < 0.45:
        return {**base, "error": "fit-skip-short"}
    desired = max(0.2, min(2.0, slot / measured))
    lines = [f"Target language: {L.name(tgt)}", f"Exact target duration: {slot:.2f}s",
             f"Measured duration of this line: {measured:.2f}s", f"Measured ratio: {ratio:.3f} (1.000 is exact)",
             f"Requested text-length factor: about {desired:.3f}x", f"Current translated line: {text}"]
    if source:
        lines.append(f"Source line (meaning authority): {source}")
    if before:
        lines.append(f"Previous source line (context only): {before}")
    if after:
        lines.append(f"Next source line (context only): {after}")
    brief = style_brief(instructions)
    try:
        candidate = chat(_MEASURED_PROMPT + ("\n" + brief if brief else ""), "\n".join(lines))
    except LLMError:
        return {**base, "error": "fit-provider-failed"}
    if not candidate or candidate == text:
        return {**base, "error": "fit-unchanged"}
    ok, _ = refine_output_ok(text, candidate, tgt)
    return {**base, "text": candidate, "changed": True} if ok else {**base, "error": "fit-diverged"}


def condense(chat: Chat, text: str, available: float, tgt: str, source: str | None, cps: float | None
             ) -> str | None:
    """Shorter rewrite for an impossible row — a suggestion only, never auto-applied."""
    base_est = estimate(text, tgt, cps)
    if not text or available <= 0 or base_est <= available:
        return None
    best: tuple[str, float] | None = None
    for attempt in range(2):
        lines = [f"Target language: {L.name(tgt)}", f"Target duration: {available:.2f}s", f"Current line: {text}",
                 f"Current reading duration: ~{base_est:.2f}s"]
        if source:
            lines.append(f"Source line (for meaning): {source}")
        if attempt and best:
            lines.append(f"Your previous rewrite was still ~{best[1]:.2f}s. Cut further.")
        try:
            candidate = chat(_CONDENSE_PROMPT, "\n".join(lines))
        except LLMError:
            break
        if not candidate or not refine_output_ok(text, candidate, tgt)[0]:
            continue
        est = estimate(candidate, tgt, cps)
        if est < base_est and (best is None or est < best[1]):
            best = (candidate, est)
        if est <= available:
            break
    return best[0] if best else None


# ------------------------------------------------------------------ orchestration


def _fan_out(fn: Callable[[Any], Any], items: list[Any], deadline: float, on_done: Callable[[int], None]
             ) -> list[Any | None]:
    """Run ``fn`` over items on the LLM pool; items unfinished at ``deadline`` come back as None."""
    results: list[Any | None] = [None] * len(items)
    if not items:
        return results
    ex = pool()
    futures: dict[Future, int] = {ex.submit(fn, item): i for i, item in enumerate(items)}
    done_count = 0
    pending = set(futures)
    while pending:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        finished, pending = wait(pending, timeout=min(remaining, 1.0), return_when="FIRST_COMPLETED")
        for f in finished:
            results[futures[f]] = f.result()
            done_count += 1
            on_done(done_count)
    ex.shutdown(wait=False, cancel_futures=True)
    return results


def translate(segs: list[SegIn], *, src: str, tgt: str, opts: Options, glossary: list[dict],
              context_cache: dict, cps: float | None, total_s: float,
              mt: Callable[[list[str], str, str], tuple[list[str], dict[int, str]]],
              progress: Progress) -> tuple[list[dict], list[str]]:
    """Translate ``segs`` into ``tgt``. Returns (rows, warnings); rows are
    ``{id, text, literal?, critique?, error?, degraded?, rate_ratio?, rate_error?, plan}``."""
    warnings: list[str] = []
    needs_llm = opts.engine == "llm" or opts.quality in ("cinematic", "autofit", "agent") or opts.condense
    chat: Chat | None = None
    if needs_llm:
        if not opts.model:
            if opts.engine == "llm":
                raise LLMError("Pick a translation model (Settings in the Dub page → Translator).")
            warnings.append("No LLM chosen — Cinematic/Autofit/condense passes were skipped (Fast result).")
        else:
            chat = Chat(opts.model)
    deadline = time.monotonic() + BUDGET_S
    brief = style_brief(opts.instructions)
    dialect = L.dialect_clause(opts.dialect, tgt)
    by_id = {s.id: s for s in segs}

    # ---- base translation
    if opts.engine == "nllb":
        progress(f"Translating to {L.name(tgt)} with NLLB", 0.05)
        texts, errors = mt([s.text for s in segs], src, tgt)
        rows = [{"id": s.id, "text": t} | ({"error": errors[i]} if i in errors else {})
                for i, (s, t) in enumerate(zip(segs, texts))]
        extra = "\n".join(filter(None, [dialect.strip(), brief]))
        if chat and opts.quality == "cinematic":
            progress("Cinematic refinement", 0.3)
            todo = [r for r in rows if not r.get("error") and r["text"].strip()]
            refined = _fan_out(lambda r: _cinematic(chat, by_id[r["id"]].text, r["text"], src, tgt, extra),
                               todo, deadline, lambda n: progress(f"Cinematic refinement {n}/{len(todo)}",
                                                                 0.3 + 0.4 * n / max(1, len(todo))))
            for r, res in zip(todo, refined):
                r.update(res or {"literal": r["text"], "degraded": "cinematic-budget"})
    else:
        assert chat is not None
        context = None
        if opts.auto_glossary:
            fp = transcript_fingerprint(s.text for s in segs)
            cached = context_cache.get(tgt)
            if isinstance(cached, dict) and cached.get("fingerprint") == fp:
                context = cached
            else:
                progress("Building the terminology brief", 0.03)
                context = extract_context(chat, [s.text for s in segs], src, tgt)
                if context:
                    context_cache[tgt] = {**context, "fingerprint": fp}
        terms = merge_glossary(glossary, (context or {}).get("terms") or [])
        ctx_lines = [f"Video context: {context['theme']}"] if context and context.get("theme") else []
        if terms:
            ctx_lines.append(glossary_text(terms))
        ctx_extra = "\n".join(ctx_lines)
        system = _TRANSLATE_PROMPT.format(src=L.name(src), tgt=L.name(tgt), script=L.script_clause(tgt),
                                          dialect=dialect, brief=brief)
        if ctx_extra:
            system += "\n\n" + ctx_extra
        reflect_extra = "\n".join(filter(None, [ctx_extra, brief]))

        def direct(seg: SegIn) -> dict:
            return _direct(chat, seg, src, tgt, system) if seg.text.strip() else {"id": seg.id, "text": seg.text}

        # The direct translation always runs to completion; only the optional refinements are budget-bound.
        results = _fan_out(direct, segs, math.inf, lambda n: progress(
            f"Translating to {L.name(tgt)} {n}/{len(segs)}", 0.05 + 0.45 * n / max(1, len(segs))))
        rows = [r or {"id": s.id, "text": s.text, "error": "translation-failed"} for s, r in zip(segs, results)]
        if opts.reflect:
            todo = [r for r in rows if not r.get("error") and r["text"].strip()]
            polished = _fan_out(lambda r: _reflect(chat, by_id[r["id"]].text, r["text"], src, tgt, reflect_extra),
                                todo, deadline, lambda n: progress(f"Polishing lines {n}/{len(todo)}",
                                                                   0.5 + 0.2 * n / max(1, len(todo))))
            for r, text in zip(todo, polished):
                if text:
                    r["literal"], r["text"] = r["text"], text

    # ---- rate ratio (all modes) + Autofit fit pass
    for r in rows:
        seg = by_id[r["id"]]
        if not r.get("error") and r["text"].strip() and seg.end > seg.start:
            r["rate_ratio"] = round(rate_ratio(r["text"], seg.end - seg.start, tgt), 3)
    if chat and opts.quality in ("cinematic", "autofit", "agent"):
        strict = opts.quality in ("autofit", "agent")
        todo = [r for r in rows if not r.get("error") and r["text"].strip() and by_id[r["id"]].end > by_id[r["id"]].start]
        progress("Fitting lines to their time slots", 0.72)
        fitted = _fan_out(lambda r: adjust_for_slot(chat, r["text"], by_id[r["id"]].end - by_id[r["id"]].start, tgt,
                                                    by_id[r["id"]].text, strict),
                          todo, deadline, lambda n: progress(f"Fitting lines {n}/{len(todo)}",
                                                             0.72 + 0.15 * n / max(1, len(todo))))
        for r, f in zip(todo, fitted):
            if f is None:
                r["rate_error"] = "fit-budget"
                continue
            r["text"] = f["text"]
            r["rate_ratio"] = round(f["rate_ratio"], 3)
            if f.get("error"):
                r["rate_error"] = f["error"]

    # ---- duration plan (final text) + opt-in condense suggestions
    ordered = sorted(segs, key=lambda s: s.start)
    text_by_id = {r["id"]: r["text"] for r in rows}
    verdicts = classify([{"id": s.id, "start": s.start, "end": s.end, "text": text_by_id.get(s.id, "")}
                         for s in ordered], tgt, cps=cps, total_s=total_s)
    for r in rows:
        if not r.get("error") and r["text"].strip():
            r["plan"] = verdicts.get(r["id"])
    if chat and opts.condense:
        todo = [r for r in rows if (r.get("plan") or {}).get("status") == "impossible"]
        if todo:
            progress("Suggesting condensed lines", 0.9)
            suggestions = _fan_out(lambda r: condense(chat, r["text"], r["plan"]["available_s"], tgt,
                                                      by_id[r["id"]].text, cps), todo, deadline, lambda n: None)
            for r, s in zip(todo, suggestions):
                if s:
                    r["plan"]["suggested_text"] = s
    if time.monotonic() > deadline:
        warnings.append("The LLM refinement budget ran out; unfinished lines kept their earlier text.")
    return rows, warnings
