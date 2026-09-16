"""
Checks the Phase 1 deliverables from the scope-of-work against the actual
database contents:
  - working corpus directory with 10+ preprocessed novels
  - SQLite database with corpus metadata and text
  - at least 10 test novels "cleaned and verified"

Usage: python -m src.verify
Exit code 0 = all checks pass, 1 = something is short.
"""
import sqlite3
import sys

from . import config


def main():
    if not config.DB_PATH.exists():
        print(f"FAIL: no database at {config.DB_PATH}. Run build_pipeline.py first.")
        sys.exit(1)

    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    n_novels = cur.execute("SELECT COUNT(*) FROM novels").fetchone()[0]
    n_with_divisions = cur.execute(
        "SELECT COUNT(DISTINCT novel_id) FROM divisions"
    ).fetchone()[0]
    n_with_pages = cur.execute(
        "SELECT COUNT(DISTINCT novel_id) FROM pages"
    ).fetchone()[0]
    n_warned = cur.execute(
        "SELECT COUNT(DISTINCT novel_id) FROM qc_log"
    ).fetchone()[0]
    n_sentences = cur.execute("SELECT COUNT(*) FROM sentences").fetchone()[0]

    print(f"novels ingested:              {n_novels}")
    print(f"novels with divisions found:  {n_with_divisions}")
    print(f"novels with page markers:     {n_with_pages}")
    print(f"novels with >=1 QC warning:   {n_warned}")
    print(f"total sentences:              {n_sentences}")

    ok = True
    if n_novels < 10:
        print("FAIL: fewer than 10 novels in the database.")
        ok = False
    if n_with_divisions < min(10, n_novels):
        print("WARN: some test novels have no detected chapter/volume divisions "
              "-- check DIVISION_* patterns in config.py against a real file "
              "with src/inspect_corpus.py.")
    if n_with_pages < min(10, n_novels):
        print("WARN: some test novels have no detected page markers -- check "
              "PAGE_TAG_PATTERN in config.py.")

    if n_warned:
        print("\nnovels with warnings:")
        rows = cur.execute(
            """SELECT n.filename, q.warning FROM qc_log q
               JOIN novels n ON n.id = q.novel_id ORDER BY n.filename"""
        ).fetchall()
        for r in rows:
            print(f"  {r['filename']}: {r['warning']}")

    conn.close()
    print("\nPASS" if ok else "\nFAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
