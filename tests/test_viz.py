"""
Unit tests for the Phase 3 visualization layer (src/viz/): the data the
timeline reads from corpus.db, the story-time reading, and the figure.
Builds a tiny database with the real schema (src/db.py) -- one two-scene
novel -- so nothing depends on the full corpus.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db  # noqa: E402
from src.viz import data, flashback_map, pace, timeline  # noqa: E402


def _tiny_db(tmp_path):
    path = tmp_path / "tiny.db"
    conn = db.get_connection(path)
    conn.execute("""INSERT INTO novels (id, filename, title, author, year, word_count, analysis_eligible)
                    VALUES (1, 't.txt', 'A Test Novel', 'Anon', 1850, 1000, 1)""")
    conn.execute("INSERT INTO divisions (id, novel_id, title, start_char) VALUES (10, 1, 'CHAPTER I', 0)")
    conn.execute("INSERT INTO divisions (id, novel_id, title, start_char) VALUES (11, 1, 'CHAPTER II', 900)")
    conn.execute("INSERT INTO sentences (id, novel_id, text) VALUES (100, 1, 'She had seen it years before.')")
    conn.execute("INSERT INTO sentences (id, novel_id, text) VALUES (101, 1, '3 May. Left. 7 May. Back.')")
    conn.execute("INSERT INTO sentences (id, novel_id, text) VALUES (102, 1, 'He had gone.')")
    units = [("word", k, 25 * k, 25 * k + 25, None) for k in range(40)]
    units += [("scene", 0, 0, 400, 10), ("scene", 1, 400, 1000, 11)]
    units += [("passage", k, 200 * k, 200 * k + 200, None) for k in range(5)]
    conn.executemany("""INSERT INTO granularity_units (novel_id, level, unit_index, start_word, end_word, ref_id)
                        VALUES (1, ?, ?, ?, ?, ?)""", units)
    conn.execute("UPDATE granularity_units SET words = end_word - start_word, marker_density = 5.0")

    def event(eid, etype, word, conf, detail, sentence=None, subtype=None, modifier=None, scene_visible=None):
        conn.execute("""INSERT INTO temporal_events (id, novel_id, sentence_id, granularity, event_type,
                        subtype, confidence, detail, duration_modifier) VALUES (?, 1, ?, 'sentence', ?, ?, ?, ?, ?)""",
                     (eid, sentence, etype, subtype, conf, json.dumps(detail), modifier))
        conn.execute("""INSERT INTO granularity_comparison (novel_id, event_id, signal, word_position,
                        visible_at_word, visible_at_scene) VALUES (1, ?, 'x', ?, 1, ?)""", (eid, word, scene_visible))

    event(1, "scene_boundary", 400, 0.7, {"duration_label": "jump", "jumps": 2, "date_jumps": 1,
                                          "stated_elapsed_days": 9}, subtype="division")
    event(2, "flashback", 120, 1.0, {"cue_phrases": ["years before"]}, sentence=100, scene_visible=0)
    event(3, "flashback", 800, 0.6, {"cue_phrases": []}, sentence=102)
    event(4, "explicit_marker", 450, 1.0, {"phrases": ["3 may", "7 may"],
                                           "categories": ["calendar_date", "calendar_date"]}, sentence=101)
    event(5, "explicit_marker", 600, 0.9, {"phrases": ["two days later"], "categories": ["forward_jump"]})
    event(6, "explicit_marker", 300, 0.7, {"phrases": ["used to"], "categories": ["frequency"]},
          modifier="multi-unit")
    conn.commit()
    conn.close()
    return data.connect(path)


def test_scenes_tile_the_novel_and_carry_labels(tmp_path):
    d = data.load_timeline(_tiny_db(tmp_path), "t.txt")
    assert [(s["start_word"], s["end_word"], s["label"], s["division"]) for s in d["scenes"]] == [
        (0, 400, "iterative", "CHAPTER I"), (400, 1000, "jump", "CHAPTER II")]
    assert d["total_words"] == 1000


def test_opening_scene_is_labelled_from_its_own_cues(tmp_path):
    # the engine logs labels on boundary events, which the opening scene
    # lacks; its "used to" makes it iterative by the engine's own rule
    opening = data.load_timeline(_tiny_db(tmp_path), "t.txt")["scenes"][0]
    assert opening["label"] == "iterative" and opening["label_derived"]


def test_story_time_is_dated_span_plus_quantified_jumps(tmp_path):
    scene = data.load_timeline(_tiny_db(tmp_path), "t.txt")["scenes"][1]
    # 3 May -> 7 May is 4 days; "two days later" adds 2; the engine's
    # running sum (9) is kept alongside, not used
    assert scene["dated_span_days"] == 4 and scene["cue_days"] == [("two days later", 2)]
    assert scene["story_days"] == 6 and scene["stated_elapsed_days"] == 9


def test_low_confidence_flashbacks_are_not_discrete_events(tmp_path):
    d = data.load_timeline(_tiny_db(tmp_path), "t.txt", min_confidence=0.8)
    assert [(e["lane"], e["word"]) for e in d["events"]] == [
        ("flashback", 120), ("absolute", 450), ("jump", 600)]  # "used to" is neither lane
    assert d["events"][0]["excerpt"] == "She had seen it years before."


def test_timeline_figure_has_a_trace_per_label_and_lane(tmp_path):
    d = data.load_timeline(_tiny_db(tmp_path), "t.txt")
    fig = timeline.build_timeline(d)
    names = [t.name for t in fig.data]
    assert timeline.LABEL_TEXT["jump"] in names and timeline.LABEL_TEXT["iterative"] in names
    assert timeline.LABEL_TEXT["opening"] not in names  # the opening scene now has a real label
    assert {"flashbacks", "forward jumps", "dates & years"} <= set(names)
    # lanes can be switched off
    assert "flashbacks" not in [t.name for t in timeline.build_timeline(d, lanes={"jump"}).data]


def test_format_days():
    assert [timeline.format_days(x) for x in (0.5, 1, 45, 365, 730, None)] == [
        "+12 h", "+1 d", "+2 mo", "+1 yr", "+2 yr", ""]


def test_pace_is_story_time_over_discourse_time(tmp_path):
    d = data.load_pace(_tiny_db(tmp_path), "t.txt")
    # scene 2: 6 story days told in 600 words -> 10 days per 1,000 words
    assert d["scenes"][1]["pace"] == 10.0 and d["scenes"][0]["pace"] is None
    # the "used to" at word 300 falls in the second 200-word passage
    assert [p["iterative_density"] for p in d["passages"]] == [0.0, 5.0, 0.0, 0.0, 0.0]
    fig = pace.build_pace(d)
    assert fig.layout.yaxis.type == "log" and pace.summary(d)["timed_scenes"] == 1


def test_flashback_map_marks_washed_out_events_hollow(tmp_path):
    d = data.load_flashback_map(_tiny_db(tmp_path), "t.txt")
    assert [(e["kind"], e["visible"]["scene"]) for e in d["flash_events"]] == [
        ("flashback", 0), ("flashback", None)]
    fig = flashback_map.build_flashback_map(d, "scene")
    names = [t.name for t in fig.data]
    assert "flashbacks, washed out at scene scale" in names
    assert flashback_map.summary(d)["visible_at_scale"] == 0
