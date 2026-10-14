"""
Heuristic flashback / flash-forward detection over sentence sequences.
Not a trained classifier -- three independent signals, combined into a
bounded confidence score:

  (a) tense_reversal: a past_perfect (flashback candidate) or
      future_in_past (flash-forward candidate) sentence sits inside a run
      of narration that is locally past_simple-dominated
  (b) cue: a phrase pointing the same direction as the candidate --
      for a flashback, a "retrospective" temporal marker ("long ago",
      "ever since") or a recall phrase ("had happened", "she remembered");
      for a flash-forward, a "forward_jump" marker ("years later") or a
      prospective phrase ("would later"). Markers in other categories
      ("suddenly", "meanwhile") are not cues -- see temporal_markers.py.
  (c) sustained: an adjacent sentence carries the same tense, so this isn't
      a single isolated clause

A detection fires only when AT LEAST TWO of (a)/(b)/(c) hold. A single
past-perfect clause in past-tense narration satisfies (a) almost by
definition ("She had already eaten when he arrived") -- that's ordinary
backstory, not a flashback -- so (a) alone is deliberately not enough.

confidence = 0.4*a + 0.4*b + 0.2*c, so every recorded detection scores
between 0.6 and 1.0. All firing windows are recorded; threshold filtering
happens at query time, not here.
"""
import re
from collections import Counter

from .confidence import clamp
from .temporal_markers import phrases_in
from .tense_tagger import TENSE_FUTURE_IN_PAST, TENSE_PAST_PERFECT, TENSE_PAST_SIMPLE, TENSE_PRESENT

W_TENSE_REVERSAL = 0.4
W_CUE = 0.4
W_SUSTAINED = 0.2
MIN_SIGNALS = 2

# sentences on each side used to judge "what tense is this passage
# normally narrated in"
BACKGROUND_WINDOW = 5

RETROSPECTIVE_CUES = [
    "had happened", "looking back", "as if looking back", "she remembered",
    "he remembered", "i remembered", "in retrospect", "thinking back", "recalled",
]
PROSPECTIVE_CUES = ["would later", "would one day", "in years to come"]


def _cue_regex(phrases):
    return re.compile(r"\b(?:" + "|".join(re.escape(p) for p in phrases) + r")\b", re.IGNORECASE)


# per candidate tense: (cue-phrase regex, temporal-marker category that counts as a cue)
_CUES = {
    TENSE_PAST_PERFECT: (_cue_regex(RETROSPECTIVE_CUES), "retrospective"),
    TENSE_FUTURE_IN_PAST: (_cue_regex(PROSPECTIVE_CUES), "forward_jump"),
}


def _background_tense(features: list[dict], i: int):
    lo, hi = max(0, i - BACKGROUND_WINDOW), min(len(features), i + BACKGROUND_WINDOW + 1)
    counts = Counter(
        features[j]["dominant_tense"] for j in range(lo, hi)
        if j != i and features[j]["dominant_tense"] in (TENSE_PAST_SIMPLE, TENSE_PRESENT)
    )
    return counts.most_common(1)[0][0] if counts else None


def detect(sentences: list[dict], features: list[dict]) -> list[dict]:
    """sentences/features: parallel lists in reading order for one novel.
    sentences[i] needs "text"; features[i] needs "dominant_tense" and
    "marker_phrases" (list, possibly empty).

    Returns dicts: sentence_index, event_type ('flashback'|'flashforward'),
    confidence, detail.
    """
    events = []
    n = len(sentences)
    for i in range(n):
        tense = features[i]["dominant_tense"]
        if tense not in (TENSE_PAST_PERFECT, TENSE_FUTURE_IN_PAST):
            continue

        background = _background_tense(features, i)
        reversal = background == TENSE_PAST_SIMPLE
        cue_regex, marker_category = _CUES[tense]
        cue_hits = [c.lower() for c in cue_regex.findall(sentences[i]["text"])]
        cue_hits += phrases_in(features[i]["marker_phrases"], marker_category)
        cue = bool(cue_hits)
        sustained = any(0 <= j < n and features[j]["dominant_tense"] == tense for j in (i - 1, i + 1))

        if reversal + cue + sustained < MIN_SIGNALS:
            continue

        events.append({
            "sentence_index": i,
            "event_type": "flashback" if tense == TENSE_PAST_PERFECT else "flashforward",
            "confidence": round(clamp(W_TENSE_REVERSAL * reversal + W_CUE * cue + W_SUSTAINED * sustained), 2),
            "detail": {
                "tense_reversal": reversal,
                "cue": cue,
                "sustained": sustained,
                "background_tense": background,
                "cue_phrases": cue_hits,
            },
        })
    return events
