"""
Multi-granularity analysis and granularity comparison -- the SOW's
"does the same temporal event show up at word-level but get washed out at
page-level?"

Four temporal signals are measured over four unit sizes for every novel:

  signals                              levels (finest -> coarsest)
  retrospection  past-perfect share    word     fixed 25-word bins
                 of verb constructions passage  10-sentence windows
  prospection    future-in-past share  scene    scene_boundaries.py scenes
  marker_density markers / 1k words    page     original printed pages
  tense_churn    tense shifts / 1k     (reliable-pagination novels only)
                 words

Within each novel and level, every unit's signal is converted to a z-score
against all units of that level. An event is "visible" at a level when the
unit containing it stands out: z >= 1.0 on the signal matching the event
(flashback -> retrospection, flashforward -> prospection, explicit_marker
-> marker_density, tense_shift -> tense_churn). An event that is visible at
word level but not at scene level was "washed out" by aggregation.

Why a 10-sentence passage instead of a paragraph: the SOW's middle tier is
"sentence/paragraph", but paragraph breaks survive in only 64 of the 91
analysis-eligible novels (some source files flattened them -- Wuthering
Heights has 34 blank-line blocks for 34 chapters). A fixed sentence window
means the same thing in every novel.

Visibility is NULL, not 0, when a level can't be measured (no page markers,
or fewer than MIN_UNITS units to compute a z-score against), so "washed
out" and "not measurable" stay distinguishable.
"""
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from statistics import mean, pstdev

from .tense_tagger import TENSE_FUTURE_IN_PAST, TENSE_PAST_PERFECT

LEVELS = ("word", "passage", "scene", "page")
WORD_BIN = 25
PASSAGE_SENTENCES = 10
Z_VISIBLE = 1.0
MIN_UNITS = 5

SIGNALS = ("retrospection", "prospection", "marker_density", "tense_churn")
SIGNAL_FOR_EVENT = {
    "flashback": "retrospection",
    "flashforward": "prospection",
    "explicit_marker": "marker_density",
    "tense_shift": "tense_churn",
}

# real page-by-page pagination (148-550 words per page), per the Phase 1
# report; the other 3 paginated novels carry only sparse editorial page
# citations. 1850.txt is also excluded from analysis (Volume II only).
RELIABLE_PAGE_NOVELS = {"1805.txt", "1807.txt", "1809.txt", "1810.txt", "1849a.txt", "1850.txt"}


@dataclass
class Observations:
    """Word positions (0-based, whole novel) of everything the signals count."""
    total_words: int
    constructions: list = field(default_factory=list)  # (word_pos, tense)
    markers: list = field(default_factory=list)        # word_pos
    shifts: list = field(default_factory=list)         # word_pos


def word_units(total_words: int) -> list[dict]:
    return [{"start_word": s, "end_word": min(s + WORD_BIN, total_words), "ref_id": None}
            for s in range(0, total_words, WORD_BIN)]


def passage_units(sentence_word_starts: list[int], total_words: int) -> list[dict]:
    starts = sentence_word_starts[::PASSAGE_SENTENCES]
    return [{"start_word": s, "end_word": starts[i + 1] if i + 1 < len(starts) else total_words,
             "ref_id": None} for i, s in enumerate(starts)]


def span_units(spans: list[tuple]) -> list[dict]:
    """spans: [(start_word, end_word, ref_id), ...] -- scenes or pages."""
    return [{"start_word": a, "end_word": b, "ref_id": ref} for a, b, ref in spans if b > a]


def _count(sorted_positions: list[int], lo: int, hi: int) -> int:
    return bisect_left(sorted_positions, hi) - bisect_left(sorted_positions, lo)


def measure(units: list[dict], obs: Observations) -> list[dict]:
    """Fill in each unit's four signals (None where undefined), then their
    z-scores across the units of this level."""
    all_verbs = sorted(p for p, _ in obs.constructions)
    pp = sorted(p for p, t in obs.constructions if t == TENSE_PAST_PERFECT)
    fip = sorted(p for p, t in obs.constructions if t == TENSE_FUTURE_IN_PAST)
    markers, shifts = sorted(obs.markers), sorted(obs.shifts)

    for u in units:
        lo, hi = u["start_word"], u["end_word"]
        words = hi - lo
        verbs = _count(all_verbs, lo, hi)
        u["words"], u["verbs"] = words, verbs
        u["retrospection"] = _count(pp, lo, hi) / verbs if verbs else None
        u["prospection"] = _count(fip, lo, hi) / verbs if verbs else None
        u["marker_density"] = 1000 * _count(markers, lo, hi) / words if words else None
        u["tense_churn"] = 1000 * _count(shifts, lo, hi) / words if words else None

    for sig in SIGNALS:
        vals = [u[sig] for u in units if u[sig] is not None]
        sd = pstdev(vals) if len(vals) >= MIN_UNITS else 0.0
        mu = mean(vals) if vals else 0.0
        for u in units:
            u[f"{sig}_z"] = (u[sig] - mu) / sd if sd > 0 and u[sig] is not None else None
    return units


def index_units(units: list[dict]) -> tuple:
    """(sorted unit starts, units) -- build once per level, then locate()."""
    return [u["start_word"] for u in units], units


def locate(index: tuple, word_pos: int):
    """The unit containing word_pos, or None (e.g. text before the first
    page marker)."""
    starts, units = index
    i = bisect_right(starts, word_pos) - 1
    if i >= 0 and word_pos < units[i]["end_word"]:
        return units[i]
    return None


def compare(event_type: str, word_pos: int, indexes: dict) -> dict:
    """Visibility of one event at every level. indexes maps level ->
    index_units(...) output, or None when the level doesn't exist for this
    novel (e.g. no reliable page markers)."""
    out = {"signal": SIGNAL_FOR_EVENT.get(event_type, "structural")}
    for level in LEVELS:
        index = indexes.get(level)
        unit = locate(index, word_pos) if index and index[1] else None
        if unit is None:
            out[f"{level}_z"], out[f"visible_at_{level}"] = None, None
        elif event_type not in SIGNAL_FOR_EVENT:
            # scene boundaries are structural facts, not rates that can be
            # averaged away -- present at every level that contains them
            out[f"{level}_z"], out[f"visible_at_{level}"] = None, 1
        else:
            z = unit[f"{out['signal']}_z"]
            out[f"{level}_z"] = None if z is None else round(z, 3)
            out[f"visible_at_{level}"] = None if z is None else int(z >= Z_VISIBLE)
    return out
