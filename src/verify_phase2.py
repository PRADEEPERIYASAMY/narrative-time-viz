"""
Checks the Phase 2 deliverables against the database (mirrors verify.py's
role for Phase 1):

  feature detection
    - the SOW's 4 required feature types are all present: tense shifts,
      explicit temporal markers, scene boundaries, and flashbacks and/or
      flash-forwards
    - every confidence value is in [0, 1]
    - absolute time references are detected (Dracula, the epistolary test
      novel, has calendar-date markers)
  cue taxonomy (Weeks 9-10)
    - duration_modifier is NULL or "multi-unit"; every scene's duration
      label is one of the five evidence-based labels (never a default)
    - no apparatus or closing-tag residue in any eligible novel's sentences
  test slice
    - every Phase 2 test novel has events, and every one of its sentences
      is tagged
  granularity comparison
    - every analyzed novel has signal units at word, passage, and scene
      level, at page level if it has reliable pagination, and at paragraph
      level exactly when its paragraphs survive (Weeks 9-10)
    - every event has exactly one granularity_comparison row
    - visibility values are 0, 1, or NULL (not measurable), never anything else
  scope
    - no analysis_eligible = 0 novel (single-volume extract) was analyzed
    - with --require-full: all analysis-eligible novels were analyzed

Usage:
    python -m src.verify_phase2                  # after --test-slice or a partial run
    python -m src.verify_phase2 --require-full   # after the full 91-novel run
Exit 0 = pass, 1 = fail.
"""
import argparse
import sqlite3
import sys

from . import config
from .analyze_temporal import TEST_SLICE
from .temporal.granularity import RELIABLE_PAGE_NOVELS, has_paragraphs
from .temporal.scene_duration import DURATION_LABELS

REQUIRED = ["tense_shift", "explicit_marker", "scene_boundary"]
FLASHBACK_TYPES = ["flashback", "flashforward"]
VIS_COLS = ["visible_at_word", "visible_at_paragraph", "visible_at_passage", "visible_at_scene",
            "visible_at_page"]


def main():
    parser = argparse.ArgumentParser(description="Check Phase 2 deliverables")
    parser.add_argument("--require-full", action="store_true",
                        help="fail unless every analysis-eligible novel has been analyzed")
    args = parser.parse_args()

    if not config.DB_PATH.exists():
        print(f"FAIL: no database at {config.DB_PATH}. Run build_pipeline.py first.")
        sys.exit(1)

    conn = sqlite3.connect(config.DB_PATH)
    ok = True

    def fail(msg):
        nonlocal ok
        ok = False
        print(f"FAIL: {msg}")

    # --- feature detection ---------------------------------------------------
    types = dict(conn.execute(
        "SELECT event_type, COUNT(*) FROM temporal_events GROUP BY event_type").fetchall())
    print("events by type:")
    for t in REQUIRED + FLASHBACK_TYPES:
        print(f"  {t:16s} {types.get(t, 0):>9,}")
    for t in REQUIRED:
        if not types.get(t):
            fail(f"no {t} events")
    if not any(types.get(t) for t in FLASHBACK_TYPES):
        fail("no flashback or flashforward events")

    bad = conn.execute(
        "SELECT COUNT(*) FROM temporal_events WHERE confidence < 0 OR confidence > 1").fetchone()[0]
    print(f"\nconfidence values outside [0,1]: {bad}")
    if bad:
        fail("confidence out of range")

    dates = conn.execute(
        """SELECT COUNT(*) FROM temporal_events te JOIN novels n ON n.id = te.novel_id
           WHERE n.filename = '1897.txt' AND te.event_type = 'explicit_marker'
             AND te.detail LIKE '%calendar_date%'""").fetchone()[0]
    print(f"Dracula sentences with calendar-date markers: {dates}")
    if not dates and conn.execute(
            "SELECT 1 FROM temporal_events te JOIN novels n ON n.id = te.novel_id "
            "WHERE n.filename = '1897.txt' LIMIT 1").fetchone():
        fail("Dracula analyzed but no calendar dates detected")

    # --- cue taxonomy (Weeks 9-10) -------------------------------------------
    modifiers = dict(conn.execute(
        "SELECT COALESCE(duration_modifier, 'none'), COUNT(*) FROM temporal_events GROUP BY 1").fetchall())
    print(f"\nduration_modifier: {modifiers}")
    if set(modifiers) - {"none", "multi-unit"}:
        fail("unexpected duration_modifier value")
    labels = dict(conn.execute(
        """SELECT json_extract(detail, '$.duration_label'), COUNT(*) FROM temporal_events
           WHERE event_type = 'scene_boundary' GROUP BY 1""").fetchall())
    print(f"scene duration labels: {labels}")
    if labels and set(labels) - set(DURATION_LABELS):
        fail("scene duration label outside " + ", ".join(DURATION_LABELS))
    residue = conn.execute(
        """SELECT COUNT(*) FROM sentences s JOIN novels n ON n.id = s.novel_id
           WHERE n.analysis_eligible = 1 AND (s.text LIKE '%</chapter>%' OR s.text LIKE '%<Footnote%'
                 OR s.text LIKE '%<PREFACE%' OR s.text LIKE '%<Illustration%')""").fetchone()[0]
    print(f"sentences with apparatus or markup residue: {residue}")
    if residue:
        fail("apparatus or closing tags left in sentences -- rebuild the corpus")

    # --- test slice ----------------------------------------------------------
    print("\ntest slice:")
    for fn in TEST_SLICE:
        row = conn.execute(
            """SELECT (SELECT COUNT(*) FROM temporal_events te WHERE te.novel_id = n.id),
                      (SELECT COUNT(*) FROM sentences s WHERE s.novel_id = n.id),
                      (SELECT COUNT(*) FROM sentence_features sf JOIN sentences s
                         ON s.id = sf.sentence_id WHERE s.novel_id = n.id)
               FROM novels n WHERE n.filename = ?""", (fn,)).fetchone()
        if row is None:
            fail(f"{fn} not in novels table")
            continue
        n_events, n_sent, n_feat = row
        print(f"  {fn}: {n_events:,} events, {n_feat:,}/{n_sent:,} sentences tagged")
        if n_events == 0:
            fail(f"{fn} has no temporal events")
        if n_feat != n_sent:
            fail(f"{fn} has untagged sentences")

    # --- granularity comparison ----------------------------------------------
    analyzed = conn.execute(
        """SELECT n.id, n.filename, n.cleaned_text FROM novels n
           WHERE n.id IN (SELECT DISTINCT novel_id FROM temporal_events)""").fetchall()
    missing_levels, with_paragraphs = [], 0
    for nid, fn, text in analyzed:
        levels = {r[0] for r in conn.execute(
            "SELECT DISTINCT level FROM granularity_units WHERE novel_id = ?", (nid,))}
        need = {"word", "passage", "scene"} | ({"page"} if fn in RELIABLE_PAGE_NOVELS else set())
        if has_paragraphs(text):
            need.add("paragraph")
            with_paragraphs += 1
        elif "paragraph" in levels:
            missing_levels.append(f"{fn} (paragraph level without surviving paragraphs)")
        if need - levels:
            missing_levels.append(f"{fn} (missing {sorted(need - levels)})")
    print(f"\nnovels analyzed: {len(analyzed)}; missing granularity levels: {len(missing_levels)}")
    for m in missing_levels[:10]:
        fail(f"granularity units incomplete for {m}")

    n_events = conn.execute("SELECT COUNT(*) FROM temporal_events").fetchone()[0]
    n_cmp = conn.execute("SELECT COUNT(*) FROM granularity_comparison").fetchone()[0]
    orphans = conn.execute(
        """SELECT COUNT(*) FROM temporal_events te LEFT JOIN granularity_comparison gc
           ON gc.event_id = te.id WHERE gc.id IS NULL""").fetchone()[0]
    dupes = conn.execute(
        "SELECT COUNT(*) FROM (SELECT event_id FROM granularity_comparison "
        "GROUP BY event_id HAVING COUNT(*) > 1)").fetchone()[0]
    print(f"granularity_comparison rows: {n_cmp:,} for {n_events:,} events "
          f"(events without a row: {orphans}, events with >1 row: {dupes})")
    if orphans or dupes:
        fail("every event needs exactly one granularity_comparison row")

    bad_vis = conn.execute(
        "SELECT COUNT(*) FROM granularity_comparison WHERE "
        + " OR ".join(f"({c} IS NOT NULL AND {c} NOT IN (0, 1))" for c in VIS_COLS)).fetchone()[0]
    if bad_vis:
        fail(f"{bad_vis} comparison rows with visibility outside 0/1/NULL")

    print("\nshare of events still visible, by level (flashbacks / all sentence events):")
    for label, where in [("flashback", "signal = 'retrospection'"),
                         ("all", "signal != 'structural'")]:
        avgs = conn.execute(
            f"SELECT {', '.join(f'AVG({c})' for c in VIS_COLS)} FROM granularity_comparison "
            f"WHERE {where}").fetchone()
        print(f"  {label:10s} " + "  ".join(
            f"{c.split('_')[-1]} {'n/a' if v is None else f'{v:.0%}'}" for c, v in zip(VIS_COLS, avgs)))

    # --- scope -----------------------------------------------------------------
    leaked = conn.execute(
        """SELECT COUNT(DISTINCT n.filename) FROM temporal_events te
           JOIN novels n ON n.id = te.novel_id WHERE n.analysis_eligible = 0""").fetchone()[0]
    eligible = conn.execute("SELECT COUNT(*) FROM novels WHERE analysis_eligible = 1").fetchone()[0]
    print(f"\nsingle-volume (ineligible) novels with events: {leaked}")
    print(f"eligible novels analyzed: {len(analyzed) - leaked}/{eligible}")
    if leaked:
        fail("events written for analysis_eligible = 0 novels")
    if args.require_full and len(analyzed) - leaked < eligible:
        fail(f"--require-full: only {len(analyzed) - leaked}/{eligible} eligible novels analyzed")

    conn.close()
    print("\nPASS" if ok else "\nFAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
