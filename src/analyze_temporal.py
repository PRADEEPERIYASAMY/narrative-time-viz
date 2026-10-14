"""
Phase 2 CLI: runs the temporal analysis engine (src/temporal/) over
analysis-eligible novels and writes results to sentence_features and
temporal_events (the SOW's per-novel "temporal event log").

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
    explicit_marker  sentence containing a temporal-marker phrase
    scene_boundary   start of a new scene (asterisk break or new division)
    flashback        past-perfect-led retrospective passage
    flashforward     future-in-past-led prospective passage

Idempotent: re-running a novel deletes and rewrites its rows first.
"""
import argparse
import json
import sqlite3
import sys
from bisect import bisect_left, bisect_right
from collections import Counter

from . import config, db
from .temporal import (event_log, flashback_detector, nlp_setup, scene_boundaries,
                       scene_duration, temporal_markers, tense_tagger)
from .temporal.tense_tagger import TENSE_OTHER

# SOW Phase 2 deliverable: "working analysis for at least 5 test novels."
# Each stresses a different structural case.
TEST_SLICE = [
    "1805.txt",  # Fleetwood -- dense real page markers (page-anchoring case)
    "1847.txt",  # Wuthering Heights -- frame / retrospective narration
    "1865.txt",  # Alice's Adventures in Wonderland -- short, dream frame
    "1877.txt",  # Black Beauty -- episodic first-person, no page data
    "1897.txt",  # Dracula -- epistolary, in-text dates
]


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
    conn.execute("DELETE FROM temporal_events WHERE novel_id = ?", (novel_id,))
    conn.execute(
        "DELETE FROM sentence_features WHERE sentence_id IN "
        "(SELECT id FROM sentences WHERE novel_id = ?)", (novel_id,))


def process_novel(conn, novel_id: int, cleaned_text: str) -> Counter:
    """Runs every detector for one novel. Returns event counts by type."""
    sentences = [dict(r) for r in conn.execute(
        "SELECT id, division_id, page_id, text, start_char, end_char, token_count "
        "FROM sentences WHERE novel_id = ? ORDER BY sentence_index", (novel_id,))]
    counts: Counter = Counter()
    if not sentences:
        return counts

    texts = [s["text"] for s in sentences]
    tense_results = [tense_tagger.classify_sentence(doc) for doc in nlp_setup.pipe_sentences(texts)]
    features = [
        {"dominant_tense": tr.dominant_tense, "tense_confidence": tr.confidence,
         "has_past_perfect": tr.has_past_perfect,
         "marker_phrases": temporal_markers.find_markers(s["text"])}
        for s, tr in zip(sentences, tense_results)
    ]

    _clear_novel(conn, novel_id)
    conn.executemany(
        """INSERT INTO sentence_features
           (sentence_id, dominant_tense, tense_confidence, has_past_perfect,
            has_explicit_marker, marker_phrases)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [(s["id"], f["dominant_tense"], f["tense_confidence"], int(f["has_past_perfect"]),
          int(bool(f["marker_phrases"])), json.dumps(f["marker_phrases"]))
         for s, f in zip(sentences, features)],
    )

    def log(event_type, granularity, s=None, **kwargs):
        if s is not None:
            kwargs.setdefault("sentence_id", s["id"])
            kwargs.setdefault("division_id", s["division_id"])
            kwargs.setdefault("page_id", s["page_id"])
            kwargs.setdefault("start_char", s["start_char"])
            kwargs.setdefault("end_char", s["end_char"])
        event_log.log_event(conn, novel_id=novel_id, granularity=granularity,
                            event_type=event_type, **kwargs)
        counts[event_type] += 1

    # tense_shift -- compare each substantive-tense sentence with the last
    # one seen; 'other' (fragments, bare dialogue tags) is skipped rather
    # than treated as a tense of its own. Confidence is the weaker of the
    # two sentences' tense confidences: a shift is only as sure as its
    # least-sure endpoint.
    prev = None
    for s, f in zip(sentences, features):
        if f["dominant_tense"] == TENSE_OTHER:
            continue
        if prev is not None and f["dominant_tense"] != prev["dominant_tense"]:
            log("tense_shift", "sentence", s,
                subtype=f"{prev['dominant_tense']}->{f['dominant_tense']}",
                confidence=min(prev["tense_confidence"], f["tense_confidence"]),
                detail={"from": prev["dominant_tense"], "to": f["dominant_tense"]})
        prev = f

    # explicit_marker -- one event per matching sentence (a sentence with two
    # phrases is one event, not two), subtyped by the first phrase's
    # category. Literal match, so confidence is 1.0.
    for s, f in zip(sentences, features):
        if f["marker_phrases"]:
            log("explicit_marker", "sentence", s,
                subtype=temporal_markers.category_of(f["marker_phrases"][0]), confidence=1.0,
                detail={"phrases": f["marker_phrases"],
                        "categories": [temporal_markers.category_of(p) for p in f["marker_phrases"]]})

    # scene_boundary + duration -- every scene start except the novel's
    # opening. Each event carries its scene's discourse length and its count
    # of forward_jump markers only ("suddenly"/"meanwhile" don't skip time).
    division_starts = [(r[0], r[1]) for r in conn.execute(
        "SELECT id, start_char FROM divisions WHERE novel_id = ? ORDER BY start_char", (novel_id,))]
    page_rows = conn.execute(
        "SELECT id, char_offset FROM pages WHERE novel_id = ? ORDER BY char_offset", (novel_id,)).fetchall()
    page_offsets, page_ids = [r[1] for r in page_rows], [r[0] for r in page_rows]
    sent_starts = [s["start_char"] for s in sentences]

    for idx, scene in enumerate(scene_boundaries.compute_scenes(cleaned_text, division_starts)):
        lo = bisect_left(sent_starts, scene["start_char"])
        hi = bisect_left(sent_starts, scene["end_char"])
        in_scene = list(zip(sentences[lo:hi], features[lo:hi]))
        words = sum(s["token_count"] or 0 for s, _ in in_scene)
        jumps = sum(len(temporal_markers.phrases_in(f["marker_phrases"], "forward_jump"))
                    for _, f in in_scene)
        if idx == 0:
            continue
        p = bisect_right(page_offsets, scene["start_char"]) - 1
        log("scene_boundary", "division",
            sentence_id=sentences[lo]["id"] if lo < len(sentences) else None,
            division_id=scene["division_id"],
            page_id=page_ids[p] if p >= 0 else None,
            start_char=scene["start_char"], end_char=scene["end_char"],
            subtype=scene["source"],
            # an asterisk break is an unambiguous authorial signal; a new
            # chapter is a structural boundary that may or may not change scene
            confidence=1.0 if scene["source"] == "asterisk_break" else 0.7,
            detail={"words": words, "sentences": len(in_scene), "jumps": jumps,
                    "jumps_per_1k_words": scene_duration.jumps_per_1k_words(jumps, words),
                    "duration_label": scene_duration.duration_label(jumps)})

    # flashback / flashforward
    for ev in flashback_detector.detect(sentences, features):
        log(ev["event_type"], "sentence", sentences[ev["sentence_index"]],
            confidence=ev["confidence"], detail=ev["detail"])

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
    for i, n in enumerate(novels, 1):
        counts = process_novel(conn, n["id"], n["cleaned_text"])
        totals.update(counts)
        summary = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        print(f"  [{i}/{len(novels)}] {n['filename']}: {summary}")
    conn.close()

    print(f"\ndone. {len(novels)} novel(s), {sum(totals.values())} events: "
          + ", ".join(f"{k} {v}" for k, v in sorted(totals.items())))


if __name__ == "__main__":
    main()
