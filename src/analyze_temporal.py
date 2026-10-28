"""
Phase 2 CLI: runs the temporal analysis engine (src/temporal/) over
analysis-eligible novels and writes:

    sentence_features       tense + temporal markers per sentence
    temporal_events         the per-novel temporal event log
    granularity_units       4 temporal signals per word bin / passage / scene / page
    granularity_comparison  per event: still visible at each granularity?

Usage:
    python -m src.analyze_temporal --test-slice        # the 5 Phase 2 test novels
    python -m src.analyze_temporal --novel 1847.txt
    python -m src.analyze_temporal --limit 10
    python -m src.analyze_temporal                     # all 91 eligible novels
    python -m src.analyze_temporal --include-partial   # also the 9 single-volume
        # novels excluded via analysis_eligible. Off by default -- only use if
        # that exclusion decision changes.

Event types written:
    tense_shift      sentence-level change in dominant narrative tense
    explicit_marker  sentence with a temporal-marker phrase, calendar date, or clock time
    scene_boundary   start of a new scene (asterisk break or new division)
    flashback        past-perfect-led retrospective passage
    flashforward     future-in-past-led prospective passage

Idempotent: re-running a novel deletes and rewrites its rows first.
"""
import argparse
import json
import sqlite3
import sys
import time
from bisect import bisect_left, bisect_right
from collections import Counter

from . import config, db
from .temporal import (event_log, flashback_detector, granularity, nlp_setup, scene_boundaries,
                       scene_duration, temporal_markers, tense_tagger)
from .temporal.tense_tagger import TENSE_FUTURE_IN_PAST, TENSE_OTHER, TENSE_PAST_PERFECT

# SOW Phase 2 deliverable: "working analysis for at least 5 test novels."
# Each stresses a different structural case.
TEST_SLICE = [
    "1805.txt",  # Fleetwood -- dense real page markers (page-anchoring case)
    "1847.txt",  # Wuthering Heights -- frame / retrospective narration
    "1865.txt",  # Alice's Adventures in Wonderland -- short, dream frame
    "1877.txt",  # Black Beauty -- episodic first-person, no page data
    "1897.txt",  # Dracula -- epistolary, in-text dates
]

UNIT_COLUMNS = ("words", "verbs", *granularity.SIGNALS, *(f"{s}_z" for s in granularity.SIGNALS))


def fetch_novels(conn, *, limit=None, filenames=None, include_partial=False):
    query = "SELECT id, filename, cleaned_text FROM novels"
    conditions, params = [], []
    if not include_partial:
        conditions.append("analysis_eligible = 1")
    if filenames:
        conditions.append(f"filename IN ({','.join('?' * len(filenames))})")
        params.extend(filenames)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY filename"
    if limit:
        query += " LIMIT ?"
        params.append(limit)
    return conn.execute(query, params).fetchall()


def _clear_novel(conn, novel_id: int) -> None:
    conn.execute("DELETE FROM granularity_comparison WHERE novel_id = ?", (novel_id,))
    conn.execute("DELETE FROM granularity_units WHERE novel_id = ?", (novel_id,))
    conn.execute("DELETE FROM temporal_events WHERE novel_id = ?", (novel_id,))
    conn.execute(
        "DELETE FROM sentence_features WHERE sentence_id IN "
        "(SELECT id FROM sentences WHERE novel_id = ?)", (novel_id,))


def process_novel(conn, novel_id: int, filename: str, cleaned_text: str) -> Counter:
    """Runs every detector and the granularity comparison for one novel.
    Returns event counts by type."""
    sentences = [dict(r) for r in conn.execute(
        "SELECT id, division_id, page_id, text, start_char, end_char, token_count "
        "FROM sentences WHERE novel_id = ? ORDER BY sentence_index", (novel_id,))]
    counts: Counter = Counter()
    if not sentences:
        return counts

    # word position of each sentence's first word, so anything found at a
    # char offset inside a sentence can be placed on the novel's word axis
    word_starts, total_words = [], 0
    for s in sentences:
        word_starts.append(total_words)
        total_words += s["token_count"] or 0

    def word_at(i: int, char_offset: int) -> int:
        return word_starts[i] + len(sentences[i]["text"][:char_offset].split())

    texts = [s["text"] for s in sentences]
    tense_results = [tense_tagger.classify_sentence(doc) for doc in nlp_setup.pipe_sentences(texts)]
    features = []
    for i, (s, tr) in enumerate(zip(sentences, tense_results)):
        markers = temporal_markers.find_marker_spans(s["text"])
        refs = temporal_markers.find_time_refs(s["text"])
        features.append({
            "dominant_tense": tr.dominant_tense, "tense_confidence": tr.confidence,
            "has_past_perfect": tr.has_past_perfect,
            "marker_phrases": [m.surface for m in markers], "markers": markers, "time_refs": refs,
            "constructions": [(word_at(i, c), t) for t, c in tr.constructions],
            "marker_words": sorted([word_at(i, m.start) for m in markers] + [word_at(i, r.start) for r in refs]),
        })

    _clear_novel(conn, novel_id)
    conn.executemany(
        """INSERT INTO sentence_features
           (sentence_id, dominant_tense, tense_confidence, has_past_perfect,
            has_explicit_marker, marker_phrases)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [(s["id"], f["dominant_tense"], f["tense_confidence"], int(f["has_past_perfect"]),
          int(bool(f["marker_phrases"] or f["time_refs"])),
          json.dumps(f["marker_phrases"] + [r.surface for r in f["time_refs"]]))
         for s, f in zip(sentences, features)],
    )

    logged = []  # (event_id, event_type, word_pos)

    def log(event_type, granularity_name, word_pos, s=None, **kwargs):
        if s is not None:
            for key in ("division_id", "page_id", "start_char", "end_char"):
                kwargs.setdefault(key, s[key])
            kwargs.setdefault("sentence_id", s["id"])
        event_id = event_log.log_event(conn, novel_id=novel_id, granularity=granularity_name,
                                       event_type=event_type, **kwargs)
        logged.append((event_id, event_type, word_pos))
        counts[event_type] += 1

    def first_construction(i: int, tense: str) -> int:
        return next((w for w, t in features[i]["constructions"] if t == tense), word_starts[i])

    # tense_shift -- compare each substantive-tense sentence with the last
    # one seen; 'other' (fragments, bare dialogue tags) is skipped rather
    # than treated as a tense of its own. Confidence is the weaker of the
    # two sentences' tense confidences.
    prev = None
    shift_words = []
    for i, (s, f) in enumerate(zip(sentences, features)):
        if f["dominant_tense"] == TENSE_OTHER:
            continue
        if prev is not None and f["dominant_tense"] != prev["dominant_tense"]:
            w = first_construction(i, f["dominant_tense"])
            shift_words.append(w)
            log("tense_shift", "sentence", w, s,
                subtype=f"{prev['dominant_tense']}->{f['dominant_tense']}",
                confidence=min(prev["tense_confidence"], f["tense_confidence"]),
                detail={"from": prev["dominant_tense"], "to": f["dominant_tense"]})
        prev = f

    # explicit_marker -- one event per sentence with any taxonomy cue,
    # calendar date, clock time, or year; subtyped by the first one's
    # category. Confidence is the most reliable cue's taxonomy confidence
    # (dates, clock times, and years are pattern-normalized: 1.0). A
    # sentence with an iterative cue gets duration_modifier "multi-unit":
    # its story-time span is unknown but likely more than one occasion.
    for i, (s, f) in enumerate(zip(sentences, features)):
        found = sorted([(m.start, m.surface, m.category, m.confidence) for m in f["markers"]] +
                       [(r.start, r.surface, r.category, 1.0) for r in f["time_refs"]])
        if found:
            categories = [c for _, _, c, _ in found]
            log("explicit_marker", "sentence", f["marker_words"][0], s,
                subtype=categories[0], confidence=max(conf for *_, conf in found),
                duration_modifier="multi-unit" if any(m.duration_modifier for m in f["markers"]) else None,
                detail={"phrases": [p for _, p, _, _ in found], "categories": categories,
                        "tiers": sorted({temporal_markers.CATEGORY_TIER[c] for c in categories}),
                        "delta_days": [m.delta_days for m in f["markers"] if m.delta_days is not None]})

    # scene_boundary + duration -- every scene start except the novel's
    # opening. A scene's forward jumps are its forward_jump cues plus every
    # time a calendar date advances ("3 May" ... "4 May"); its label needs
    # positive evidence (scene_duration.duration_label), and the story time
    # its cues state adds up to a lower bound on what it covers.
    dated = [(i, r.month_day) for i, f in enumerate(features)
             for r in f["time_refs"] if r.category == "calendar_date"]
    moves = scene_duration.date_movements([md for _, md in dated])
    advances = [(i, scene_duration.advance_days(dated[k - 1][1], md))
                for k, ((i, md), move) in enumerate(zip(dated, moves)) if move == "advance"]
    advance_sentences = [i for i, _ in advances]

    division_starts = [(r[0], r[1]) for r in conn.execute(
        "SELECT id, start_char FROM divisions WHERE novel_id = ? ORDER BY start_char", (novel_id,))]
    page_rows = conn.execute(
        "SELECT id, char_offset FROM pages WHERE novel_id = ? ORDER BY char_offset", (novel_id,)).fetchall()
    page_offsets, page_ids = [r[1] for r in page_rows], [r[0] for r in page_rows]
    sent_starts = [s["start_char"] for s in sentences]

    def word_of_char(char_offset: int) -> int:
        i = bisect_left(sent_starts, char_offset)
        return word_starts[i] if i < len(sentences) else total_words

    scene_spans = []
    for idx, scene in enumerate(scene_boundaries.compute_scenes(cleaned_text, division_starts)):
        lo = bisect_left(sent_starts, scene["start_char"])
        hi = bisect_left(sent_starts, scene["end_char"])
        words = sum(s["token_count"] or 0 for s in sentences[lo:hi])
        scene_markers = [m for f in features[lo:hi] for m in f["markers"]]
        phrase_jumps = sum(m.category == "forward_jump" for m in scene_markers)
        a_lo, a_hi = bisect_left(advance_sentences, lo), bisect_left(advance_sentences, hi)
        date_jumps = a_hi - a_lo
        jumps = phrase_jumps + date_jumps
        iterative = sum(any(m.duration_modifier for m in f["markers"]) for f in features[lo:hi])
        sequence = sum(m.category == "sequence" for m in scene_markers)
        anchors = (sum(temporal_markers.CATEGORY_TIER[m.category] in ("absolute", "position") for m in scene_markers)
                   + sum(len(f["time_refs"]) for f in features[lo:hi]))
        stated = ([m.delta_days for m in scene_markers if m.category == "forward_jump" and m.delta_days]
                  + [d for _, d in advances[a_lo:a_hi] if d])
        label = scene_duration.duration_label(jumps, iterative, sequence, anchors)
        scene_spans.append((word_of_char(scene["start_char"]), word_of_char(scene["end_char"]),
                            scene["division_id"]))
        if idx == 0:
            continue
        p = bisect_right(page_offsets, scene["start_char"]) - 1
        log("scene_boundary", "division", word_of_char(scene["start_char"]),
            sentence_id=sentences[lo]["id"] if lo < len(sentences) else None,
            division_id=scene["division_id"], page_id=page_ids[p] if p >= 0 else None,
            start_char=scene["start_char"], end_char=scene["end_char"],
            subtype=scene["source"],
            # an asterisk break is an unambiguous authorial signal; a new
            # chapter is a structural boundary that may or may not change scene
            confidence=1.0 if scene["source"] == "asterisk_break" else 0.7,
            duration_modifier="multi-unit" if iterative else None,
            detail={"words": words, "sentences": hi - lo, "jumps": jumps,
                    "phrase_jumps": phrase_jumps, "date_jumps": date_jumps,
                    "jumps_per_1k_words": scene_duration.jumps_per_1k_words(jumps, words),
                    "iterative_sentences": iterative, "sequence_cues": sequence, "anchors": anchors,
                    "stated_elapsed_days": round(sum(stated), 2) if stated else None,
                    "duration_label": label})

    # flashback / flashforward -- positioned at the defining verb
    for ev in flashback_detector.detect(sentences, features):
        i = ev["sentence_index"]
        tense = TENSE_PAST_PERFECT if ev["event_type"] == "flashback" else TENSE_FUTURE_IN_PAST
        log(ev["event_type"], "sentence", first_construction(i, tense), sentences[i],
            confidence=ev["confidence"], detail=ev["detail"])

    # --- multi-granularity signals + comparison ------------------------------
    obs = granularity.Observations(
        total_words=total_words,
        constructions=[c for f in features for c in f["constructions"]],
        markers=[w for f in features for w in f["marker_words"]],
        shifts=shift_words,
    )
    levels = {
        "word": granularity.word_units(total_words),
        "passage": granularity.passage_units(word_starts, total_words),
        "scene": granularity.span_units(scene_spans),
        "page": None,
    }
    if filename in granularity.RELIABLE_PAGE_NOVELS and page_offsets:
        bounds = page_offsets + [len(cleaned_text)]
        levels["page"] = granularity.span_units(
            [(word_of_char(bounds[k]), word_of_char(bounds[k + 1]), page_ids[k])
             for k in range(len(page_ids))])

    indexes = {}
    for level, units in levels.items():
        if not units:
            continue
        granularity.measure(units, obs)
        indexes[level] = granularity.index_units(units)
        conn.executemany(
            f"""INSERT INTO granularity_units
                (novel_id, level, unit_index, start_word, end_word, ref_id, {', '.join(UNIT_COLUMNS)})
                VALUES (?, ?, ?, ?, ?, ?, {', '.join('?' * len(UNIT_COLUMNS))})""",
            [(novel_id, level, k, u["start_word"], u["end_word"], u["ref_id"],
              *(u[c] for c in UNIT_COLUMNS)) for k, u in enumerate(units)],
        )

    rows = []
    for event_id, event_type, word_pos in logged:
        cmp = granularity.compare(event_type, word_pos, indexes)
        rows.append((novel_id, event_id, f"te:{event_id}:{event_type}", cmp["signal"], word_pos,
                     # detection level: sentence events are seen there by
                     # construction; scene boundaries aren't sentence-level
                     None if event_type == "scene_boundary" else 1,
                     *(cmp[f"visible_at_{lv}"] for lv in granularity.LEVELS),
                     *(cmp[f"{lv}_z"] for lv in granularity.LEVELS)))
    conn.executemany(
        """INSERT INTO granularity_comparison
           (novel_id, event_id, event_signature, signal, word_position, visible_at_sentence,
            visible_at_word, visible_at_passage, visible_at_scene, visible_at_page,
            word_z, passage_z, scene_z, page_z)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", rows)

    conn.commit()
    return counts


def main():
    parser = argparse.ArgumentParser(description="Run the Phase 2 temporal analysis engine")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--test-slice", action="store_true", help="the 5 Phase 2 test novels")
    group.add_argument("--novel", help="a single novel by filename, e.g. 1847.txt")
    parser.add_argument("--limit", type=int, help="only the first N eligible novels")
    parser.add_argument("--include-partial", action="store_true",
                        help="also process the 9 single-volume novels (off by default)")
    args = parser.parse_args()

    if not config.DB_PATH.exists():
        print(f"No database at {config.DB_PATH}. Run build_pipeline.py first.", file=sys.stderr)
        sys.exit(1)

    conn = db.get_connection()
    conn.row_factory = sqlite3.Row
    filenames = TEST_SLICE if args.test_slice else ([args.novel] if args.novel else None)
    novels = fetch_novels(conn, limit=args.limit, filenames=filenames,
                          include_partial=args.include_partial)
    if not novels:
        print("No matching eligible novels.", file=sys.stderr)
        sys.exit(1)

    totals: Counter = Counter()
    started = time.time()
    for i, n in enumerate(novels, 1):
        counts = process_novel(conn, n["id"], n["filename"], n["cleaned_text"])
        totals.update(counts)
        summary = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        print(f"  [{i}/{len(novels)}] {n['filename']}: {summary}", flush=True)
    conn.close()

    print(f"\ndone in {time.time() - started:.0f}s. {len(novels)} novel(s), "
          f"{sum(totals.values())} events: " + ", ".join(f"{k} {v}" for k, v in sorted(totals.items())))


if __name__ == "__main__":
    main()
