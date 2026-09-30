"""
Unit tests for the Phase 2 temporal analysis engine's foundational layer
(src/temporal/tense_tagger.py, temporal_markers.py) -- the scene-boundary,
flashback-detection, and granularity-comparison pieces are later-phase work
and aren't implemented yet (see reports/ for the phased plan). Uses the
real spaCy model (not a mock) since tense_tagger.py's rules are verified
against its actual tag output, not an idealized version of it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.temporal import nlp_setup, temporal_markers, tense_tagger  # noqa: E402


def _classify(text):
    doc = next(nlp_setup.pipe_sentences([text]))
    return tense_tagger.classify_sentence(doc)


def test_tense_past_simple():
    r = _classify("She walked to the market.")
    assert r.dominant_tense == tense_tagger.TENSE_PAST_SIMPLE
    assert r.confidence == 1.0


def test_tense_past_perfect():
    r = _classify("She had walked to the market before the rain began.")
    assert r.dominant_tense == tense_tagger.TENSE_PAST_PERFECT
    assert r.has_past_perfect
    # ambiguous: also contains a bare past_simple ("began") -> lower confidence
    assert r.confidence == 0.6


def test_tense_present():
    r = _classify("She walks to the market every day.")
    assert r.dominant_tense == tense_tagger.TENSE_PRESENT


def test_tense_present_perfect():
    r = _classify("She has walked to the market already.")
    assert r.dominant_tense == tense_tagger.TENSE_PRESENT_PERFECT


def test_tense_future_in_past():
    r = _classify("She would later walk to the market.")
    assert r.dominant_tense == tense_tagger.TENSE_FUTURE_IN_PAST


def test_tense_other_for_fragment():
    r = _classify("Eh!")
    assert r.dominant_tense == tense_tagger.TENSE_OTHER
    assert r.confidence == 0.3


def test_temporal_markers_found():
    hits = temporal_markers.find_markers("Three years later, she returned to the house.")
    assert "years later" in hits


def test_temporal_markers_none():
    assert temporal_markers.find_markers("She walked to the market.") == []
