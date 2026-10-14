"""
Unit tests for the Phase 2 temporal analysis engine (src/temporal/):
tense tagging, explicit markers, scene boundaries, scene duration, and
flashback/flash-forward detection. Granularity comparison is scheduled for
Weeks 7-9. Uses the real spaCy model (not a mock) since tense_tagger.py's
rules are verified against its actual tag output.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.temporal import (  # noqa: E402
    flashback_detector, nlp_setup, scene_boundaries, scene_duration,
    temporal_markers, tense_tagger,
)

PS, PP, PR, FIP = (tense_tagger.TENSE_PAST_SIMPLE, tense_tagger.TENSE_PAST_PERFECT,
                   tense_tagger.TENSE_PRESENT, tense_tagger.TENSE_FUTURE_IN_PAST)


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


def test_temporal_markers_whole_word_only():
    # "by now" must not match inside "standby now"
    assert temporal_markers.find_markers("The standby now waited.") == []


def test_marker_categories():
    assert temporal_markers.category_of("years later") == "forward_jump"
    assert temporal_markers.category_of("long ago") == "retrospective"
    assert temporal_markers.category_of("meanwhile") == "simultaneity"
    assert temporal_markers.category_of("suddenly") == "abruptness"
    assert temporal_markers.phrases_in(["suddenly", "the next day"], "forward_jump") == ["the next day"]


# --- scene boundaries -------------------------------------------------------

def test_scene_break_detected():
    text = "First scene.\n* * * * *\nSecond scene."
    offsets = scene_boundaries.find_scene_breaks(text)
    assert len(offsets) == 1
    assert text[offsets[0]:].startswith("* * *")


def test_scene_break_ignores_inline_asterisks():
    assert scene_boundaries.find_scene_breaks("A *word* and * two * stars.") == []


def test_scenes_split_within_division():
    text = "AAAA\n* * * * *\nBBBB"
    scenes = scene_boundaries.compute_scenes(text, [(1, 0)])
    assert [s["source"] for s in scenes] == ["division", "asterisk_break"]
    assert scenes[0]["start_char"] == 0 and scenes[-1]["end_char"] == len(text)


def test_scenes_one_per_division_without_breaks():
    text = "Chapter one text. Chapter two text."
    scenes = scene_boundaries.compute_scenes(text, [(1, 0), (2, 18)])
    assert [(s["division_id"], s["start_char"], s["end_char"]) for s in scenes] == \
        [(1, 0, 18), (2, 18, len(text))]


def test_scenes_undivided_novel_is_one_scene():
    # 1817.txt / 1835.txt have no divisions at all
    scenes = scene_boundaries.compute_scenes("One undivided narrative.", [])
    assert len(scenes) == 1 and scenes[0]["division_id"] is None


# --- scene duration ---------------------------------------------------------

def test_duration_label():
    assert scene_duration.duration_label(0) == "continuous"
    assert scene_duration.duration_label(2) == "spans 2 explicit jump(s)"


def test_jumps_per_1k_words():
    assert scene_duration.jumps_per_1k_words(3, 1500) == 2.0
    assert scene_duration.jumps_per_1k_words(1, 0) == 0.0


# --- flashback / flash-forward ----------------------------------------------

def _feats(tenses, markers=None):
    markers = markers or [[] for _ in tenses]
    return [{"dominant_tense": t, "marker_phrases": m} for t, m in zip(tenses, markers)]


def _sents(*texts):
    return [{"text": t} for t in texts]


def test_flashback_reversal_plus_cue():
    sents = _sents("She walked in.", "She had left it there years before.", "It was gone.")
    events = flashback_detector.detect(sents, _feats([PS, PP, PS], [[], ["years before"], []]))
    assert len(events) == 1
    ev = events[0]
    assert ev["event_type"] == "flashback"
    assert ev["detail"]["tense_reversal"] and ev["detail"]["cue"]
    assert ev["confidence"] == 0.8


def test_flashback_reversal_plus_sustained():
    sents = _sents("She walked in.", "He had gone.", "He had taken the key.", "She sat down.")
    events = flashback_detector.detect(sents, _feats([PS, PP, PP, PS]))
    assert [e["sentence_index"] for e in events] == [1, 2]
    assert all(e["confidence"] == 0.6 for e in events)


def test_lone_past_perfect_clause_is_not_a_flashback():
    # reversal alone -- ordinary backstory, the case the 2-signal rule exists for
    sents = _sents("She walked in.", "He had already eaten.", "She sat down.")
    assert flashback_detector.detect(sents, _feats([PS, PP, PS])) == []


def test_abruptness_marker_is_not_a_flashback_cue():
    # "suddenly" marks an abrupt event, not a look back -- reversal + it
    # must stay below the 2-signal threshold
    sents = _sents("She walked in.", "Suddenly he had vanished.", "She sat down.")
    assert flashback_detector.detect(sents, _feats([PS, PP, PS], [[], ["suddenly"], []])) == []


def test_flashforward_detected_from_cue_phrase():
    sents = _sents("He packed.", "He would later regret it.", "He left.")
    events = flashback_detector.detect(sents, _feats([PS, FIP, PS]))
    assert len(events) == 1
    assert events[0]["event_type"] == "flashforward"
    assert "would later" in events[0]["detail"]["cue_phrases"]


def test_all_three_signals_score_full_confidence():
    sents = _sents("She walked in.", "She had seen it years before.", "She had kept it.", "She left.")
    events = flashback_detector.detect(sents, _feats([PS, PP, PP, PS], [[], ["years before"], [], []]))
    assert events[0]["confidence"] == 1.0
