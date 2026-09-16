"""
Phase 1 CLI entrypoint: walk data/raw/, parse every .txt, load into SQLite.

Usage:
    python -m src.build_pipeline                 # full corpus
    python -m src.build_pipeline --limit 10       # first 10 files (test run)
    python -m src.build_pipeline --decade 1840-1849

Note: this INSERT OR REPLACEs each novel row, which resets
author_gender/author_birth_year/author_death_year/volume_note to NULL
(those columns aren't populated here -- see enrich_metadata.py). If you
re-run this after having run enrich_metadata.py, re-run
`python -m src.enrich_metadata` afterward too.
"""
import argparse
import sys

from . import config, db
from .preprocess import parse_novel


def find_raw_files(decade: str | None):
    if decade:
        decade_dirs = [config.RAW_DIR / decade]
    else:
        decade_dirs = sorted(p for p in config.RAW_DIR.iterdir() if p.is_dir() and not p.name.startswith("_"))
    for d in decade_dirs:
        for f in sorted(d.rglob("*.txt")):
            yield d.name, f


def main():
    parser = argparse.ArgumentParser(description="Build the Phase 1 corpus SQLite database")
    parser.add_argument("--limit", type=int, default=None, help="only process the first N files (for the 10-novel test run)")
    parser.add_argument("--decade", default=None, help="only process one decade, e.g. 1840-1849")
    args = parser.parse_args()

    if not config.RAW_DIR.exists() or not any(config.RAW_DIR.iterdir()):
        print(f"No raw corpus found at {config.RAW_DIR}. Run src/download_corpus.py first.", file=sys.stderr)
        sys.exit(1)

    conn = db.get_connection()
    processed, clean_count, warned_count = 0, 0, 0

    for decade, path in find_raw_files(args.decade):
        if args.limit and processed >= args.limit:
            break
        try:
            novel = parse_novel(path)
        except Exception as e:
            print(f"  [ERROR] {path.name}: {e}", file=sys.stderr)
            continue

        db.insert_novel(conn, novel, decade)
        processed += 1
        if novel.warnings:
            warned_count += 1
            print(f"  [warn] {path.name}: {'; '.join(novel.warnings)}")
        else:
            clean_count += 1
        print(f"  [{processed}] {path.name} -> {novel.word_count} words, "
              f"{len(novel.divisions)} divisions, {len(novel.pages)} pages, "
              f"{len(novel.sentences)} sentences")

    conn.close()
    print(f"\ndone. {processed} novel(s) ingested into {config.DB_PATH} "
          f"({clean_count} clean, {warned_count} with warnings -- see qc_log table)")


if __name__ == "__main__":
    main()
