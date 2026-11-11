"""
Reads what the Phase 3 views draw from corpus.db: one novel's scenes (with
their duration labels and the story time their cues state), its pages
where reliable, and its labelled events (flashbacks, flash-forwards,
forward jumps, absolute time references), all on one axis -- word position
in the novel, the axis the Phase 2 engine already uses for every event.
"""
import json
import re
import sqlite3
from bisect import bisect_right

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
    for r in conn.execute(
            """SELECT gc.word_position, te.detail FROM temporal_events te
               JOIN granularity_comparison gc ON gc.event_id = te.id
               WHERE te.novel_id = ? AND te.event_type = 'explicit_marker'""", (nid,)):
        i = bisect_right(starts, r["word_position"]) - 1
        if i < 0:
            continue
        d = json.loads(r["detail"])
        for phrase, cat in zip(d["phrases"], d["categories"]):
            if cat == "calendar_date":
                # surfaces are stored lowercased; months match case-sensitively
                restored = _MONTH_WORD.sub(lambda m: m.group(0).capitalize(), phrase)
                dates[i] += [t.month_day for t in temporal_markers.find_time_refs(restored) if t.month_day]
            elif cat == "forward_jump":
                cue_days[i] += [(phrase, m.delta_days) for m in temporal_markers.find_marker_spans(phrase)
                                if m.delta_days]
    for s, ds, cues in zip(scenes, dates, cue_days):
        span = scene_duration.advance_days(min(ds), max(ds)) if len(set(ds)) > 1 else None
        s["dated_span_days"] = span
        s["dated_range"] = (min(ds), max(ds)) if span else None
        s["cue_days"] = cues
        total = (span or 0) + sum(d for _, d in cues)
        s["story_days"] = round(total, 2) if total else None


def page_at(pages: list[tuple], word: int):
    """The original-edition page holding a word position, or None."""
    i = bisect_right([w for w, _ in pages], word) - 1
    return pages[i][1] if i >= 0 else None
