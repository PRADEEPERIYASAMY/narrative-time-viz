"""
Explicit temporal-marker phrase detection -- literal (case-insensitive,
whole-word) phrase matching, not a trained classifier.

Each phrase is assigned a category describing what it signals about story
time, because different detectors need different subsets:

  forward_jump   story time skips ahead ("years later", "the next day")
  retrospective  points back to an earlier time ("long ago", "ever since")
  simultaneity   a parallel strand at the same time ("meanwhile")
  time_of_day    a time-of-day anchor ("at dawn")
  anchor         a reference point, no direction ("by now", "that same day")
  abruptness     a sudden onset within continuous time ("suddenly")

The categories were introduced in Weeks 5-6, after this module first ran
against real text: 104 of 229 hits across the 5-novel test slice were
"suddenly", which marks an abrupt event, not a skip in story time. Counting
it as a jump overstated scene duration (one Dracula chapter showed 11
"jumps") and fed noise into the flashback cue signal. scene_duration.py now
counts only forward_jump phrases; flashback_detector.py reads only
retrospective (flashback) or forward_jump (flash-forward) phrases as cues.
"""
import re

MARKER_CATEGORY = {
    # validated against the full corpus in Phase 1 (reports/weeks-01-02.md)
    "years later": "forward_jump",
    "months later": "forward_jump",
    "days later": "forward_jump",
    "weeks later": "forward_jump",
    "the following day": "forward_jump",
    "the next day": "forward_jump",
    "years before": "retrospective",
    "long ago": "retrospective",
    "years ago": "retrospective",
    "in the meantime": "simultaneity",
    "meanwhile": "simultaneity",
    "at dawn": "time_of_day",
    "at dusk": "time_of_day",
    # added in Weeks 3-4; first run against real text in Weeks 5-6
    "some time later": "forward_jump",
    "not long after": "forward_jump",
    "before long": "forward_jump",
    "from then on": "forward_jump",
    "ever since": "retrospective",
    "in those days": "retrospective",
    "until now": "retrospective",
    "that same day": "anchor",
    "by now": "anchor",
    "it was not until": "anchor",
    "suddenly": "abruptness",
    "all at once": "abruptness",
}

MARKER_PHRASES = list(MARKER_CATEGORY)

_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(p) for p in sorted(MARKER_PHRASES, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def find_markers(text: str) -> list[str]:
    """Every matched phrase (lowercased), in order of appearance. A
    sentence can match more than once."""
    return [m.group(0).lower() for m in _PATTERN.finditer(text)]


def category_of(phrase: str) -> str:
    return MARKER_CATEGORY[phrase.lower()]


def phrases_in(phrases: list[str], category: str) -> list[str]:
    """The subset of already-matched phrases belonging to one category."""
    return [p for p in phrases if MARKER_CATEGORY.get(p) == category]
