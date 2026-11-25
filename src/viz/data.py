"""
Reads what the Phase 3 views draw from corpus.db: one novel's scenes (with
their duration labels and the story time their cues state), its pages
where reliable, and its labelled events (flashbacks, flash-forwards,
forward jumps, absolute time references), all on one axis -- word position
in the novel, the axis the Phase 2 engine already uses for every event.

load_timeline feeds the timeline view; load_pace the pace/density plot;
load_flashback_map the flashback map (Weeks 11-12).
"""
import json
import re
import sqlite3
from bisect import bisect_left, bisect_right
from collections import Counter

from .. import config
from ..temporal import scene_duration, temporal_markers

# event lanes on the timeline, bottom to top: (lane, how it's selected)
JUMP_CATEGORIES = {"forward_jump"}
ABSOLUTE_CATEGORIES = {"calendar_date", "year", "holiday", "clock_time"}
EXCERPT_CHARS = 180
_MONTH_WORD = re.compile(r"\b(?:" + "|".join(m.lower() for m in temporal_markers.MONTHS) + r")\b")


def connect(db_path=config.DB_PATH) -> sqlite3.Connection:
    """Read-only, so the dashboard can run while the engine writes."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=60, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def list_novels(conn) -> list[dict]:
    """Every analyzed novel, in publication order."""
    return [dict(r) for r in conn.execute(
        """SELECT filename, title, author, year FROM novels
           WHERE analysis_eligible = 1 AND id IN (SELECT DISTINCT novel_id FROM granularity_units)
           ORDER BY year, filename""")]


def _excerpt(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= EXCERPT_CHARS else text[:EXCERPT_CHARS].rsplit(" ", 1)[0] + " ..."


def load_timeline(conn, filename: str, min_confidence: float = 0.8) -> dict:
    """Everything the timeline view needs for one novel. Flashbacks and
    flash-forwards below min_confidence are left out as discrete events
    (they stay in the density curves of the Phase 2 figures)."""
    novel = conn.execute(
        "SELECT id, title, author, year, word_count FROM novels WHERE filename = ?", (filename,)).fetchone()
    if novel is None:
        raise KeyError(filename)
    nid = novel["id"]
    total = conn.execute(
        "SELECT MAX(end_word) FROM granularity_units WHERE novel_id = ? AND level = 'word'", (nid,)).fetchone()[0] or 0

    titles = {r["id"]: r["title"] for r in conn.execute(
        "SELECT id, title FROM divisions WHERE novel_id = ?", (nid,))}
    boundaries = {r["word_position"]: (r["subtype"], json.loads(r["detail"])) for r in conn.execute(
        """SELECT gc.word_position, te.subtype, te.detail FROM temporal_events te
           JOIN granularity_comparison gc ON gc.event_id = te.id
           WHERE te.novel_id = ? AND te.event_type = 'scene_boundary'""", (nid,))}
    scenes = []
    for r in conn.execute(
            """SELECT unit_index, start_word, end_word, ref_id FROM granularity_units
               WHERE novel_id = ? AND level = 'scene' ORDER BY unit_index""", (nid,)):
        source, d = boundaries.get(r["start_word"], (None, {}))
        scenes.append({
            "index": r["unit_index"], "start_word": r["start_word"], "end_word": r["end_word"],
            "words": r["end_word"] - r["start_word"],
            "division": titles.get(r["ref_id"]) or "",
            "source": source or "opening",
            "label": d.get("duration_label", "opening"),
            "jumps": d.get("jumps"), "date_jumps": d.get("date_jumps"),
            "iterative_sentences": d.get("iterative_sentences"),
            "stated_elapsed_days": d.get("stated_elapsed_days"),
        })

    pages = [(r["start_word"], r["page_number"]) for r in conn.execute(
        """SELECT gu.start_word, p.page_number FROM granularity_units gu JOIN pages p ON p.id = gu.ref_id
           WHERE gu.novel_id = ? AND gu.level = 'page' ORDER BY gu.start_word""", (nid,))]

    _add_story_time(conn, nid, scenes)

    events = []
    for r in conn.execute(
            """SELECT te.event_type, te.subtype, te.confidence, te.detail, gc.word_position, s.text
               FROM temporal_events te JOIN granularity_comparison gc ON gc.event_id = te.id
               LEFT JOIN sentences s ON s.id = te.sentence_id
               WHERE te.novel_id = ? AND te.event_type IN ('flashback', 'flashforward', 'explicit_marker')""",
            (nid,)):
        d = json.loads(r["detail"]) if r["detail"] else {}
        if r["event_type"] in ("flashback", "flashforward"):
            if r["confidence"] < min_confidence:
                continue
            lane, label = r["event_type"], ", ".join(d.get("cue_phrases", [])) or "no cue phrase"
        else:
            cues = list(zip(d.get("phrases", []), d.get("categories", [])))
            for lane, group in (("jump", JUMP_CATEGORIES), ("absolute", ABSOLUTE_CATEGORIES)):
                picked = [p for p, c in cues if c in group]
                if picked:
                    label = ", ".join(picked)
                    break
            else:
                continue
        events.append({"lane": lane, "word": r["word_position"], "confidence": r["confidence"],
                       "label": label, "excerpt": _excerpt(r["text"])})
    events.sort(key=lambda e: e["word"])

    return {"filename": filename, "title": novel["title"], "author": novel["author"],
            "year": novel["year"], "total_words": total, "scenes": scenes, "pages": pages,
            "events": events, "min_confidence": min_confidence}


def _add_story_time(conn, nid: int, scenes: list[dict]) -> None:
    """Story time each scene's cues state, read two ways.

    The engine's stated_elapsed_days adds up every date advance in reading
    order. In a novel of several diarists that double-counts: in Dracula,
    Mina's journal runs 24 July to 1 August and then Seward's diary starts
    again at 5 June, so the chain counts overlapping weeks twice. The
    timeline instead uses the scene's dated span (earliest to latest date
    in it, same-year assumption) plus its forward-jump cues with a stated
    quantity ("two years later")."""
    starts = [s["start_word"] for s in scenes]
    dates = [[] for _ in scenes]
    cue_days = [[] for _ in scenes]
    cues = [Counter() for _ in scenes]  # for labelling the opening scene
    for r in conn.execute(
            """SELECT gc.word_position, te.detail, te.duration_modifier FROM temporal_events te
               JOIN granularity_comparison gc ON gc.event_id = te.id
               WHERE te.novel_id = ? AND te.event_type = 'explicit_marker'
               ORDER BY gc.word_position""", (nid,)):
        i = bisect_right(starts, r["word_position"]) - 1
        if i < 0:
            continue
        d = json.loads(r["detail"])
        cues[i]["iterative"] += r["duration_modifier"] == "multi-unit"
        for cat in d["categories"]:
            cues[i]["jump"] += cat == "forward_jump"
            cues[i]["sequence"] += cat == "sequence"
            cues[i]["anchor"] += temporal_markers.CATEGORY_TIER.get(cat) in ("absolute", "position")
        for phrase, cat in zip(d["phrases"], d["categories"]):
            if cat == "calendar_date":
                # surfaces are stored lowercased; months match case-sensitively
                restored = _MONTH_WORD.sub(lambda m: m.group(0).capitalize(), phrase)
                dates[i] += [t.month_day for t in temporal_markers.find_time_refs(restored) if t.month_day]
            elif cat == "forward_jump":
                cue_days[i] += [(phrase, m.delta_days) for m in temporal_markers.find_marker_spans(phrase)
                                if m.delta_days]
    for s, ds, quantified in zip(scenes, dates, cue_days):
        span = scene_duration.advance_days(min(ds), max(ds)) if len(set(ds)) > 1 else None
        s["dated_span_days"] = span
        s["dated_range"] = (min(ds), max(ds)) if span else None
        s["cue_days"] = quantified
        total = (span or 0) + sum(d for _, d in quantified)
        s["story_days"] = round(total, 2) if total else None

    # The engine logs a scene's label on its boundary event, and the
    # opening scene has none. Label it here from its own cues, by the
    # engine's rule (scene_duration.duration_label).
    for s, ds, c in zip(scenes, dates, cues):
        if s["label"] == "opening":
            advances = scene_duration.date_movements(ds).count("advance")
            s["label"] = scene_duration.duration_label(c["jump"] + advances, c["iterative"], c["sequence"],
                                                       c["anchor"])
            s["label_derived"] = True


def page_at(pages: list[tuple], word: int):
    """The original-edition page holding a word position, or None."""
    i = bisect_right([w for w, _ in pages], word) - 1
    return pages[i][1] if i >= 0 else None


def _passages(conn, nid: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        """SELECT start_word, end_word, words, retrospection, prospection, marker_density
           FROM granularity_units WHERE novel_id = ? AND level = 'passage' ORDER BY start_word""", (nid,))]


def load_pace(conn, filename: str) -> dict:
    """The pace/density plot's data: every scene's discourse length and the
    story time its cues state (from load_timeline), and, per 10-sentence
    passage, how densely the text marks time and how densely it narrates
    habitually."""
    data = load_timeline(conn, filename)
    nid = conn.execute("SELECT id FROM novels WHERE filename = ?", (filename,)).fetchone()[0]
    passages = _passages(conn, nid)
    iterative = sorted(r[0] for r in conn.execute(
        """SELECT gc.word_position FROM temporal_events te JOIN granularity_comparison gc ON gc.event_id = te.id
           WHERE te.novel_id = ? AND te.event_type = 'explicit_marker' AND te.duration_modifier = 'multi-unit'""",
        (nid,)))
    for p in passages:
        n = bisect_left(iterative, p["end_word"]) - bisect_left(iterative, p["start_word"])
        p["iterative_density"] = 1000 * n / p["words"] if p["words"] else None
    for s in data["scenes"]:
        s["pace"] = s["story_days"] / (s["words"] / 1000) if s["story_days"] and s["words"] else None
    data["passages"] = passages
    return data


def load_flashback_map(conn, filename: str) -> dict:
    """The flashback map's data: every flashback and flash-forward (all
    confidence levels) with its visibility at each scale, the scenes for
    context, and per-passage retrospection and prospection."""
    data = load_timeline(conn, filename)
    nid = conn.execute("SELECT id FROM novels WHERE filename = ?", (filename,)).fetchone()[0]
    events = []
    for r in conn.execute(
            """SELECT te.event_type, te.confidence, te.detail, gc.word_position, gc.visible_at_word,
                      gc.visible_at_paragraph, gc.visible_at_passage, gc.visible_at_scene, s.text
               FROM temporal_events te JOIN granularity_comparison gc ON gc.event_id = te.id
               LEFT JOIN sentences s ON s.id = te.sentence_id
               WHERE te.novel_id = ? AND te.event_type IN ('flashback', 'flashforward')
               ORDER BY gc.word_position""", (nid,)):
        d = json.loads(r["detail"]) if r["detail"] else {}
        events.append({"kind": r["event_type"], "word": r["word_position"], "confidence": r["confidence"],
                       "cues": ", ".join(d.get("cue_phrases", [])) or "no cue phrase",
                       "visible": {lv: r[f"visible_at_{lv}"] for lv in ("word", "paragraph", "passage", "scene")},
                       "excerpt": _excerpt(r["text"])})
    data["flash_events"] = events
    data["passages"] = _passages(conn, nid)
    data["has_paragraphs"] = any(e["visible"]["paragraph"] is not None for e in events)
    return data
