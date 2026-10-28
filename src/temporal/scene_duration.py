"""
Scene "duration" heuristic.

The SOW asks to "approximate how much story-time each segment covers."
There's no reliable way to compute an absolute story-time duration (hours,
days) from text heuristics alone -- that needs real temporal reasoning, not
pattern matching -- so this module doesn't attempt one. It reports two
relative quantities instead:

  - discourse length: how much text the scene takes up (words), i.e. how
    long the *telling* is
  - explicit jumps: how many forward_jump phrases ("the next day", "years
    later", ...) occur inside the scene, plus (from Weeks 7-8) how many
    times a calendar date moves forward ("3 May" ... "4 May") -- a rough
    signal of how much *story time* the telling skips across. Date
    movement matters most for diary and letter novels like Dracula, whose
    dated entries were invisible to the phrase list alone.

A long scene with no jumps reads as continuous, slowed-down narration; a
short scene with several jumps reads as summary. That contrast is the
pace signal Phase 3's pace/density plot is meant to show. The limitation
(no absolute duration) should be stated plainly in the methodology write-up.

Weeks 9-10, on Shawna Ross's warning against letting the system "default
everything to continuous": a scene with no jump is no longer presumed
continuous. The label now needs positive evidence, in this order:

  jump        at least one forward jump or date advance
  iterative   habitual / repeated-event cues ("every Sunday", "used to"):
              the story time the telling covers is unknown but likely more
              than one occasion (duration_modifier "multi-unit")
  continuous  sequence cues ("presently", "afterwards") with no stated gap
  anchored    placed in time (an hour, a meal, a season, a holiday) but no
              movement stated
  unmarked    no temporal cue at all -- the text says nothing either way

And where cues state a quantity ("two years later", "the next day", a diary
date moving from 3 May to 7 May) the scene records the story time they add
up to: a lower bound, since unstated time can only add to it.
"""
from datetime import date

DURATION_LABELS = ("jump", "iterative", "continuous", "anchored", "unmarked")


def duration_label(jumps: int, iterative: int = 0, sequence: int = 0, anchors: int = 0) -> str:
    if jumps > 0:
        return "jump"
    if iterative > 0:
        return "iterative"
    if sequence > 0:
        return "continuous"
    if anchors > 0:
        return "anchored"
    return "unmarked"


def jumps_per_1k_words(jump_count: int, word_count: int) -> float:
    """Jump density, comparable across scenes of different lengths."""
    if word_count <= 0:
        return 0.0
    return round(1000 * jump_count / word_count, 2)


def date_movements(month_days: list[tuple]) -> list[str]:
    """Classify each calendar date (in reading order) against the previous
    one: "first", "same", "advance", or "regress". The year is never stated
    in these references, so a later (month, day) is read as story time
    moving forward and an earlier one as a step back (a retrospective
    reference, or a new year)."""
    out, prev = [], None
    for md in month_days:
        if prev is None:
            out.append("first")
        elif md == prev:
            out.append("same")
        else:
            out.append("advance" if md > prev else "regress")
        prev = md
    return out


def advance_days(prev_md: tuple, md: tuple) -> int | None:
    """Days from one (month, day) to a later one in the same (non-leap)
    year; None for an impossible date such as 31 June."""
    try:
        return (date(2001, *md) - date(2001, *prev_md)).days
    except ValueError:
        return None
