"""
Rule-based dominant-tense classification per sentence, from spaCy
POS/tag/morph output only. spaCy's tagger is a pretrained general-purpose
tagger; nothing here is trained to predict tense -- these are fixed rules
over its tag output, consistent with the SOW's "heuristics, not ML" framing.

Verified directly against spaCy 3.8 / en_core_web_sm output before writing
these rules (see the Phase 2 brief's verification step):
    "walked"              -> VBD                        => past_simple
    "had walked"          -> VBD(had) + VBN(walked)      => past_perfect
    "walks"               -> VBZ                         => present
    "has walked"          -> VBZ(has) + VBN(walked)      => present_perfect
    "would walk"          -> MD(would) + VB(walk)        => future_in_past
"""
from dataclasses import dataclass, field

TENSE_PAST_SIMPLE = "past_simple"
TENSE_PAST_PERFECT = "past_perfect"
TENSE_PRESENT = "present"
TENSE_PRESENT_PERFECT = "present_perfect"
TENSE_FUTURE_IN_PAST = "future_in_past"
TENSE_OTHER = "other"

# Priority order used when a sentence contains more than one verb phrase
# pattern. past_perfect/future_in_past are distinctive multi-word
# constructions that are rarer and more narratively specific (often the
# flashback/flash-forward cue itself) than an ordinary past_simple or
# present verb elsewhere in the same sentence, so they win ties.
_PRIORITY = [
    TENSE_PAST_PERFECT, TENSE_FUTURE_IN_PAST, TENSE_PRESENT_PERFECT,
    TENSE_PAST_SIMPLE, TENSE_PRESENT,
]


@dataclass
class TenseResult:
    dominant_tense: str
    confidence: float
    has_past_perfect: bool
    matched_tenses: set = field(default_factory=set)


# how many tokens ahead of an aux ("had"/"has"/"would") to look for its
# target verb form. Needed because the parser is disabled (see
# nlp_setup.py), so there's no dependency head to follow directly -- an
# adverb between the two ("would LATER walk") is common enough that
# strict adjacency misses real constructions.
_LOOKAHEAD = 3
_VERB_TAGS = ("VBD", "VBZ", "VBP", "VBN", "VB", "MD")


def _target_ahead(toks: list, start_idx: int, target_tags: tuple) -> bool:
    """Look up to _LOOKAHEAD tokens past start_idx for a token tagged as
    one of target_tags, stopping early if a different verb/aux is hit
    first (so we don't reach across into an unrelated clause)."""
    for j in range(start_idx + 1, min(start_idx + 1 + _LOOKAHEAD, len(toks))):
        tag = toks[j].tag_
        if tag in target_tags:
            return True
        if tag in _VERB_TAGS:
            return False
    return False


def _verb_patterns(doc) -> set:
    """Scan tokens for the constructions each tense rule depends on. Each
    token contributes to at most one pattern (elif chain) so an aux
    "had"/"has"/"would" that's part of a perfect/future-in-past
    construction isn't ALSO double-counted as its own bare-verb tense."""
    found = set()
    toks = list(doc)
    for i, tok in enumerate(toks):
        low = tok.text.lower()
        if low == "had" and _target_ahead(toks, i, ("VBN",)):
            found.add(TENSE_PAST_PERFECT)
        elif low in ("has", "have") and _target_ahead(toks, i, ("VBN",)):
            found.add(TENSE_PRESENT_PERFECT)
        elif low == "would" and _target_ahead(toks, i, ("VB",)):
            found.add(TENSE_FUTURE_IN_PAST)
        elif tok.tag_ == "VBD":
            # includes a standalone "had" used as a full verb ("she had a
            # book"), not just as part of a perfect construction -- that
            # case falls through to here since it didn't match the first
            # branch (no VBN found ahead of it).
            found.add(TENSE_PAST_SIMPLE)
        elif tok.tag_ in ("VBP", "VBZ"):
            found.add(TENSE_PRESENT)
    return found


def classify_sentence(doc) -> TenseResult:
    """doc: a spaCy Doc for one sentence (from nlp_setup.pipe_sentences)."""
    found = _verb_patterns(doc)
    if not found:
        # no verb found at all -- a fragment or bare dialogue tag ("Eh!")
        return TenseResult(TENSE_OTHER, 0.3, False, found)
    dominant = next((t for t in _PRIORITY if t in found), TENSE_OTHER)
    confidence = 1.0 if len(found) == 1 else 0.6
    return TenseResult(dominant, confidence, TENSE_PAST_PERFECT in found, found)
