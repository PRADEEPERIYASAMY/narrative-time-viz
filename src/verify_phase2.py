"""
Checks Phase 2 deliverables against the database (mirrors verify.py's role
for Phase 1):

  - the SOW's 4 required feature types are all present: tense shifts,
    explicit temporal markers, scene boundaries, and flashbacks and/or
    flash-forwards
  - every confidence value is in [0, 1]
  - every Phase 2 test-slice novel has temporal events
  - every sentence in an analyzed novel has a sentence_features row
  - no analysis_eligible = 0 novel (single-volume extract) was analyzed

Granularity comparison (sentence vs. division vs. page) is scheduled for
Weeks 7-9 and is reported here as pending, not checked.

Usage: python -m src.verify_phase2   (exit 0 = pass, 1 = fail)
"""
import sqlite3
import sys

from . import config
from .analyze_temporal import TEST_SLICE

REQUIRED = ["tense_shift", "explicit_marker", "scene_boundary"]
FLASHBACK_TYPES = ["flashback", "flashforward"]


def main():
    if not config.DB_PATH.exists():
        print(f"FAIL: no database at {config.DB_PATH}. Run build_pipeline.py first.")
        sys.exit(1)

    conn = sqlite3.connect(config.DB_PATH)
    ok = True

    def fail(msg):
        nonlocal ok
        ok = False
        print(f"FAIL: {msg}")

    types = dict(conn.execute(
        "SELECT event_type, COUNT(*) FROM temporal_events GROUP BY event_type").fetchall())
    print("events by type:")
    for t in REQUIRED + FLASHBACK_TYPES:
        print(f"  {t:16s} {types.get(t, 0):>7,}")
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

    print("\ntest slice:")
    for fn in TEST_SLICE:
        row = conn.execute(
            """SELECT n.id,
                      (SELECT COUNT(*) FROM temporal_events te WHERE te.novel_id = n.id),
                      (SELECT COUNT(*) FROM sentences s WHERE s.novel_id = n.id),
                      (SELECT COUNT(*) FROM sentence_features sf JOIN sentences s
                         ON s.id = sf.sentence_id WHERE s.novel_id = n.id)
               FROM novels n WHERE n.filename = ?""", (fn,)).fetchone()
        if row is None:
            fail(f"{fn} not in novels table")
            continue
        _, n_events, n_sent, n_feat = row
        print(f"  {fn}: {n_events:,} events, {n_feat:,}/{n_sent:,} sentences tagged")
        if n_events == 0:
            fail(f"{fn} has no temporal events")
        if n_feat != n_sent:
            fail(f"{fn} has untagged sentences")

    leaked = conn.execute(
        """SELECT COUNT(DISTINCT n.filename) FROM temporal_events te
           JOIN novels n ON n.id = te.novel_id WHERE n.analysis_eligible = 0""").fetchone()[0]
    print(f"\nsingle-volume (ineligible) novels with events: {leaked}")
    if leaked:
        fail("events written for analysis_eligible = 0 novels")

    print("\ngranularity comparison: pending (scheduled Weeks 7-9)")
    conn.close()
    print("\nPASS" if ok else "\nFAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
