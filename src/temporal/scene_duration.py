"""
Scene "duration" heuristic.

The SOW asks to "approximate how much story-time each segment covers."
There's no reliable way to compute an absolute story-time duration (hours,
days) from text heuristics alone -- that needs real temporal reasoning, not
pattern matching -- so this module doesn't attempt one. It reports two
relative quantities instead:

  - discourse length: how much text the scene takes up (words), i.e. how
    long the *telling* is
  - explicit jumps: how many temporal-marker phrases ("the next day",
    "years later", ...) occur inside the scene, i.e. a rough signal of how
    much *story time* the telling skips across

A long scene with no jumps reads as continuous, slowed-down narration; a
short scene with several jumps reads as summary. That contrast is the
pace signal Phase 3's pace/density plot is meant to show. The limitation
(no absolute duration) should be stated plainly in the methodology write-up.
"""


def duration_label(jump_count: int) -> str:
    if jump_count <= 0:
        return "continuous"
    return f"spans {jump_count} explicit jump(s)"


def jumps_per_1k_words(jump_count: int, word_count: int) -> float:
    """Jump density, comparable across scenes of different lengths."""
    if word_count <= 0:
        return 0.0
    return round(1000 * jump_count / word_count, 2)
