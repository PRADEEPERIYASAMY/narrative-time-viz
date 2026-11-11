"""
Unit tests for the Phase 2 temporal analysis engine (src/temporal/):
tense tagging (incl. word-level construction positions), explicit markers
(phrases, calendar dates, clock times), scene boundaries, scene duration,
flashback/flash-forward detection, and multi-granularity comparison. Uses
the real spaCy model (not a mock) since tense_tagger.py's rules are
verified against its actual tag output.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.temporal import (  # noqa: E402
    flashback_detector, granularity, nlp_setup, scene_boundaries, scene_duration,
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


def test_constructions_carry_char_offsets():
    text = "She had left before he arrived."
    r = _classify(text)
    tenses = [t for t, _ in r.constructions]
    assert tenses == [PP, PS]
    assert text[r.constructions[0][1]:].startswith("had")
    assert text[r.constructions[1][1]:].startswith("arrived")


def test_tense_other_for_fragment():
    r = _classify("Eh!")
    assert r.dominant_tense == tense_tagger.TENSE_OTHER
    assert r.confidence == 0.3


def test_temporal_markers_found():
    # the longer, quantified cue wins over the bare "years later"
    hits = temporal_markers.find_marker_spans("Three years later, she returned to the house.")
    assert [(m.surface, m.category, m.delta_days) for m in hits] == [("three years later", "forward_jump", 1095)]


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
    # regex-matched surfaces classify too, and a tuple of categories works
    assert temporal_markers.phrases_in(["two years later", "formerly", "she remembered"],
                                       ("retrospective", "recollection")) == ["formerly", "she remembered"]


# --- the Ross taxonomy (cue_taxonomy.csv) -------------------------------------

def _cats(text):
    return [(m.surface, m.category) for m in temporal_markers.find_marker_spans(text)]


def test_taxonomy_rows_are_well_formed():
    import csv
    rows = list(csv.DictReader(open(temporal_markers.TAXONOMY_PATH, encoding="utf-8")))
    assert {r["status"] for r in rows} <= {"active", "covered", "excluded"}
    assert {r["match"] for r in rows} <= {"phrase", "phrase_cs", "regex", "regex_cs"}
    for r in rows:
        assert r["category"] in temporal_markers.CATEGORY_TIER, r["pattern"]
        assert 0 < float(r["confidence"]) <= 1, r["pattern"]
        if r["status"] != "active":
            assert r["notes"], f"{r['pattern']} is {r['status']} without a reason"


def test_sequence_words_are_not_jumps():
    # Ross's 'presently', 'afterwards', 'later': succession without a stated gap
    assert _cats("Presently he left; afterwards, sooner or later.") == [
        ("presently", "sequence"), ("afterwards", "sequence"), ("later", "sequence")]


def test_period_forward_jumps():
    assert _cats("On the morrow, ere long, next day.") == [
        ("on the morrow", "forward_jump"), ("ere long", "forward_jump"), ("next day", "forward_jump")]


def test_ambiguous_holiday_words_need_their_holiday_sense():
    # 'lent' the verb, 'advent' = arrival, 'Yule' the surname (New Grub Street)
    assert _cats("She lent him the advent of Mr Yule; and Yule wrote.") == []
    assert _cats("It was Lent, and at Yule, and Lady-day.") == [
        ("lent", "holiday"), ("at yule", "holiday"), ("lady-day", "holiday")]
    assert _cats("They acted Midsummer Night's Dream.") == []


def test_bare_units_seasons_and_tea_need_context():
    assert _cats("A day, a year, the secret spring, the fall, tea-board.") == []
    assert _cats("In the winter, that evening, after tea.") == [
        ("the winter", "seasonal"), ("that evening", "time_of_day"), ("after tea", "meal")]


def test_iterative_cues_carry_multi_unit():
    found = temporal_markers.find_marker_spans(
        "We used to walk every Sunday, and day after day she sat there of an evening.")
    assert [(m.surface, m.duration_modifier) for m in found] == [
        ("used to", "multi-unit"), ("every sunday", "multi-unit"),
        ("day after day", "multi-unit"), ("of an evening", "multi-unit")]
    # 'used to' as 'accustomed to' is not a habit of the story
    assert _cats("I was not used to walking; she had become used to it.") == []


def test_quantities_become_days():
    found = temporal_markers.find_marker_spans(
        "A twelvemonth after, for three long weeks, in a week's time; some days later.")
    assert [(m.category, m.delta_days) for m in found] == [
        ("forward_jump", 365), ("duration", 21), ("duration", 7), ("forward_jump", None)]


def test_spelled_out_dates_and_years():
    refs = temporal_markers.find_time_refs(
        "On the fifteenth of July 17--, and July the fifth, in the year 1756, and in 1773.")
    assert [(r.category, r.month_day, r.year) for r in refs] == [
        ("calendar_date", (7, 15), None), ("year", None, None), ("calendar_date", (7, 5), None),
        ("year", None, 1756), ("year", None, 1773)]


def test_calendar_dates_found_and_normalized():
    refs = temporal_markers.find_time_refs("3 May.-Left Munich on 1st of May; back by June 2nd.")
    assert [(r.category, r.month_day) for r in refs] == [
        ("calendar_date", (5, 3)), ("calendar_date", (5, 1)), ("calendar_date", (6, 2))]


def test_clock_times_found():
    refs = temporal_markers.find_time_refs("Left at 8:35 P. M.; by ten o'clock, or half-past nine.")
    assert [r.surface for r in refs] == ["8:35 p. m.", "ten o'clock", "half-past nine"]
    assert all(r.category == "clock_time" for r in refs)


def test_modal_may_and_years_are_not_dates():
    # "May 1885" is a month and year, not a day of May; bare numbers are not years
    refs = temporal_markers.find_time_refs("She may 3 times try. In May 1885 he left with 1500 men.")
    assert [(r.category, r.year) for r in refs] == [("year", 1885)]


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

def test_duration_label_needs_positive_evidence():
    # no cue at all is "unmarked", never presumed continuous
    assert scene_duration.duration_label(0) == "unmarked"
    assert scene_duration.duration_label(0, anchors=2) == "anchored"
    assert scene_duration.duration_label(0, sequence=1, anchors=2) == "continuous"
    assert scene_duration.duration_label(0, iterative=1, sequence=1) == "iterative"
    assert scene_duration.duration_label(2, iterative=1) == "jump"


def test_advance_days():
    assert scene_duration.advance_days((5, 3), (5, 7)) == 4
    assert scene_duration.advance_days((10, 30), (11, 6)) == 7
    assert scene_duration.advance_days((6, 1), (6, 31)) is None


def test_jumps_per_1k_words():
    assert scene_duration.jumps_per_1k_words(3, 1500) == 2.0
    assert scene_duration.jumps_per_1k_words(1, 0) == 0.0


def test_date_movements():
    # Dracula's diary: 3 May, 4 May, 4 May (same entry), then a look back to 1 May
    assert scene_duration.date_movements([(5, 3), (5, 4), (5, 4), (5, 1)]) == \
        ["first", "advance", "same", "regress"]


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


# --- multi-granularity comparison -------------------------------------------

def _novel_with_one_retrospective_burst(total_words=1000):
    """One past-simple verb every 10 words, except a burst of past-perfect
    verbs packed into words 500-524 -- one sharp, local flashback."""
    cons = [(w, PS) for w in range(0, total_words, 10) if not 500 <= w < 525]
    cons += [(w, PP) for w in range(500, 525, 5)]
    return granularity.Observations(total_words=total_words, constructions=cons)


def test_word_and_passage_units_cover_the_text():
    units = granularity.word_units(60)
    assert [(u["start_word"], u["end_word"]) for u in units] == [(0, 25), (25, 50), (50, 60)]
    passages = granularity.passage_units(list(range(0, 240, 10)), 240)  # 24 sentences
    assert [(p["start_word"], p["end_word"]) for p in passages] == [(0, 100), (100, 200), (200, 240)]


def test_measure_computes_signals_and_zscores():
    obs = _novel_with_one_retrospective_burst()
    units = granularity.measure(granularity.word_units(1000), obs)
    burst = granularity.locate(granularity.index_units(units), 510)
    assert burst["retrospection"] == 1.0
    assert burst["retrospection_z"] > granularity.Z_VISIBLE
    quiet = granularity.locate(granularity.index_units(units), 100)
    assert quiet["retrospection"] == 0.0 and quiet["retrospection_z"] < 0


def test_local_flashback_washes_out_at_coarser_levels():
    # the burst at 500-524 is the sharpest retrospection in the novel, but
    # words 0-199 are retrospective throughout (one past-perfect every 10
    # words). At word level the burst stands out; averaged into 200-word
    # scenes it is diluted below that sustained opening -- washed out.
    obs = _novel_with_one_retrospective_burst()
    obs.constructions += [(w, PP) for w in range(3, 200, 10)]
    scenes = granularity.span_units([(k, k + 200, k) for k in range(0, 1000, 200)])
    indexes = {
        "word": granularity.index_units(granularity.measure(granularity.word_units(1000), obs)),
        "scene": granularity.index_units(granularity.measure(scenes, obs)),
    }
    cmp = granularity.compare("flashback", 510, indexes)
    assert cmp["signal"] == "retrospection"
    assert cmp["visible_at_word"] == 1
    assert cmp["visible_at_scene"] == 0
    assert cmp["word_z"] > cmp["scene_z"]
    assert cmp["visible_at_passage"] is None   # level not supplied: not measurable
    assert cmp["visible_at_page"] is None


def test_too_few_units_is_not_measurable():
    obs = _novel_with_one_retrospective_burst()
    halves = granularity.span_units([(0, 500, 1), (500, 1000, 2)])   # < MIN_UNITS
    index = granularity.index_units(granularity.measure(halves, obs))
    assert granularity.compare("flashback", 510, {"scene": index})["visible_at_scene"] is None


def test_visibility_zero_when_unit_does_not_stand_out():
    obs = _novel_with_one_retrospective_burst()
    word = granularity.index_units(granularity.measure(granularity.word_units(1000), obs))
    assert granularity.compare("flashback", 100, {"word": word})["visible_at_word"] == 0


def test_scene_boundaries_are_structural():
    obs = _novel_with_one_retrospective_burst()
    word = granularity.index_units(granularity.measure(granularity.word_units(1000), obs))
    cmp = granularity.compare("scene_boundary", 300, {"word": word})
    assert cmp["signal"] == "structural" and cmp["visible_at_word"] == 1


# --- the paragraph level (Weeks 9-10) ----------------------------------------

def test_paragraph_blocks_locate_each_paragraph():
    text = "First para here.\n\nSecond one,\nstill second.\n\n\n  Third."
    blocks = granularity.paragraph_blocks(text)
    assert [(text[off:off + 6], words) for off, words in blocks] == [
        ("First ", 3), ("Second", 4), ("Third.", 1)]


def test_flattened_source_has_no_paragraphs():
    # a chapter-sized "paragraph" (Wuthering Heights' source) is not one
    assert not granularity.has_paragraphs(("word " * 3000 + "\n\n") * 3)
    assert granularity.has_paragraphs(("word " * 40 + "\n\n") * 30)


def test_paragraph_level_is_null_where_paragraphs_are_lost():
    obs = _novel_with_one_retrospective_burst()
    word = granularity.index_units(granularity.measure(granularity.word_units(1000), obs))
    cmp = granularity.compare("flashback", 510, {"word": word, "paragraph": None})
    assert cmp["visible_at_word"] == 1 and cmp["visible_at_paragraph"] is None
