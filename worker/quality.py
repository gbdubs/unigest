from __future__ import annotations

import re
import unicodedata

# Common boilerplate patterns
BOILERPLATE_PATTERNS = [
    r"cookie\s*(policy|notice|consent)",
    r"subscribe\s*(to\s*our)?\s*newsletter",
    r"accept\s*(all\s*)?cookies",
    r"privacy\s*policy",
    r"terms\s*(of\s*|&\s*)?(service|use|conditions)",
    r"sign\s*(up|in)\s*(for|to)",
    r"follow\s*us\s*on",
    r"share\s*(this|on)\s*(facebook|twitter|linkedin)",
    r"all\s*rights\s*reserved",
    r"©\s*\d{4}",
    r"skip\s*to\s*(main\s*)?content",
    r"navigation\s*menu",
    r"search\s*(this\s*site|here)",
    r"powered\s*by",
    r"advertisement",
    r"sponsored\s*content",
]

_boilerplate_re = re.compile("|".join(BOILERPLATE_PATTERNS), re.IGNORECASE)
_sentence_end = re.compile(r"[.!?]\s")


def check_quality(text: str, input_type: str = "url") -> float:
    if not text or not text.strip():
        return 0.0

    scores = []

    # 1. Structural coherence (40%)
    scores.append((_structural_coherence(text), 0.40))

    # 2. Boilerplate ratio (25%)
    scores.append((_boilerplate_score(text), 0.25))

    # 3. Minimum content length (20%)
    scores.append((_length_score(text, input_type), 0.20))

    # 4. Encoding sanity (15%)
    scores.append((_encoding_score(text), 0.15))

    return sum(score * weight for score, weight in scores)


def _structural_coherence(text: str) -> float:
    sentences = _sentence_end.split(text)
    if not sentences:
        return 0.0

    valid = 0
    for s in sentences:
        s = s.strip()
        words = s.split()
        if 3 <= len(words) <= 100:
            valid += 1

    ratio = valid / max(len(sentences), 1)

    # Check paragraph structure
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    para_bonus = min(len(paragraphs) / 3.0, 1.0) * 0.2

    return min(ratio * 0.8 + para_bonus, 1.0)


def _boilerplate_score(text: str) -> float:
    matches = _boilerplate_re.findall(text)
    boilerplate_chars = sum(len(m) for m in matches)
    ratio = boilerplate_chars / max(len(text), 1)
    if ratio > 0.4:
        return 0.0
    return 1.0 - (ratio / 0.4)


def _length_score(text: str, input_type: str) -> float:
    word_count = len(text.split())
    min_words = 100 if input_type == "url" else 20
    if word_count >= min_words:
        return 1.0
    return word_count / min_words


def _encoding_score(text: str) -> float:
    score = 1.0

    # Check for replacement characters
    if "\ufffd" in text:
        count = text.count("\ufffd")
        score -= min(count * 0.1, 0.5)

    # Check for non-printable characters (excluding normal whitespace)
    non_printable = sum(
        1 for c in text
        if unicodedata.category(c).startswith("C") and c not in "\n\r\t"
    )
    if non_printable > 0:
        ratio = non_printable / len(text)
        score -= min(ratio * 10, 0.5)

    return max(score, 0.0)
