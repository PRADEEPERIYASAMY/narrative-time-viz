"""
SQLite schema and insert helpers.

Schema is designed for Phase 2/3's multi-granularity requirement: sentences
carry both a division_id and a page_id foreign key, so "does this temporal
shift show up at sentence-level but wash out at page-level" (SOW Phase 2) is
a straightforward join, and page-anchored plots (SOW: "this shift occurs at
page 47 of the original edition") come for free from the pages table.

Phase 2 adds: novels.analysis_eligible (0 for the 9 novels confirmed to be
a single volume of a multi-volume original -- see enrich_metadata.py, which
sets this after every ingest), plus the temporal analysis engine's output
(src/temporal/): sentence_features, temporal_events (the per-novel temporal
event log), granularity_units (each temporal signal measured per word bin,
passage, scene, and page), and granularity_comparison (for every event,
whether it is still visible at each of those levels). Weeks 9-10 adds
temporal_events.duration_modifier ("multi-unit" for iterative events).
"""
import sqlite3
from bisect import bisect_right
from pathlib import Path

from . import config
from .preprocess import ParsedNovel

SCHEMA = """
CREATE TABLE IF NOT EXISTS novels (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    filename            TEXT UNIQUE NOT NULL,
    title               TEXT,
    author              TEXT,
    author_gender       TEXT,
    author_birth_year   INTEGER,
    author_death_year   INTEGER,
    volume_note         TEXT,
    analysis_eligible   INTEGER DEFAULT 1,
    year                INTEGER,
    decade              TEXT,
    source              TEXT,
    word_count          INTEGER,
    cleaned_text        TEXT,
    ingested_at         TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS divisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    novel_id        INTEGER NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
    division_type   TEXT,
    division_number TEXT,
    title           TEXT,
    start_char      INTEGER,
    order_index     INTEGER
);

CREATE TABLE IF NOT EXISTS pages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    novel_id        INTEGER NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
    page_number     TEXT,
    char_offset     INTEGER,
    order_index     INTEGER
);

CREATE TABLE IF NOT EXISTS sentences (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    novel_id        INTEGER NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
    division_id     INTEGER REFERENCES divisions(id),
    page_id         INTEGER REFERENCES pages(id),
    sentence_index  INTEGER,
    text            TEXT,
    start_char      INTEGER,
    end_char        INTEGER,
    token_count     INTEGER
);

CREATE TABLE IF NOT EXISTS qc_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    novel_id        INTEGER NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
    warning         TEXT
);

CREATE TABLE IF NOT EXISTS sentence_features (
    sentence_id          INTEGER PRIMARY KEY REFERENCES sentences(id) ON DELETE CASCADE,
    dominant_tense       TEXT,
    tense_confidence     REAL,
    has_past_perfect     INTEGER DEFAULT 0,
    has_explicit_marker  INTEGER DEFAULT 0,
    marker_phrases       TEXT
);

CREATE TABLE IF NOT EXISTS temporal_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    novel_id     INTEGER NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
    sentence_id  INTEGER REFERENCES sentences(id),
    division_id  INTEGER REFERENCES divisions(id),
    page_id      INTEGER REFERENCES pages(id),
    granularity  TEXT CHECK(granularity IN ('sentence','division','page')),
    event_type   TEXT CHECK(event_type IN ('tense_shift','explicit_marker','scene_boundary','flashback','flashforward')),
    subtype      TEXT,
    confidence   REAL,
    detail       TEXT,
    start_char   INTEGER,
    end_char     INTEGER,
    duration_modifier TEXT   -- "multi-unit": iterative, span unknown but likely > 1 unit
);

CREATE TABLE IF NOT EXISTS granularity_units (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    novel_id             INTEGER NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
    level                TEXT CHECK(level IN ('word','passage','scene','page')),
    unit_index           INTEGER,
    start_word           INTEGER,
    end_word             INTEGER,
    ref_id               INTEGER,   -- division_id for scenes, page_id for pages
    words                INTEGER,
    verbs                INTEGER,
    retrospection        REAL,
    prospection          REAL,
    marker_density       REAL,
    tense_churn          REAL,
    retrospection_z      REAL,
    prospection_z        REAL,
    marker_density_z     REAL,
    tense_churn_z        REAL
);

CREATE TABLE IF NOT EXISTS granularity_comparison (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    novel_id            INTEGER NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
    event_id            INTEGER NOT NULL REFERENCES temporal_events(id) ON DELETE CASCADE,
    event_signature     TEXT,
    signal              TEXT,
    word_position       INTEGER,
    visible_at_sentence INTEGER,
    visible_at_word     INTEGER,
    visible_at_passage  INTEGER,
    visible_at_scene    INTEGER,
    visible_at_page     INTEGER,
    word_z              REAL,
    passage_z           REAL,
    scene_z             REAL,
    page_z              REAL
);

CREATE INDEX IF NOT EXISTS idx_sentences_novel ON sentences(novel_id);
CREATE INDEX IF NOT EXISTS idx_divisions_novel ON divisions(novel_id);
CREATE INDEX IF NOT EXISTS idx_pages_novel ON pages(novel_id);
CREATE INDEX IF NOT EXISTS idx_temporal_events_novel ON temporal_events(novel_id);
CREATE INDEX IF NOT EXISTS idx_sentence_features_tense ON sentence_features(dominant_tense);
CREATE INDEX IF NOT EXISTS idx_granularity_units_novel ON granularity_units(novel_id, level);
CREATE INDEX IF NOT EXISTS idx_granularity_comparison_novel ON granularity_comparison(novel_id);
"""

# columns added after the original schema shipped -- CREATE TABLE IF NOT
# EXISTS won't retroactively add a column to an existing table, so an
# already-built corpus.db needs an explicit ALTER TABLE.
_NOVELS_MIGRATIONS = [
    ("author_gender", "TEXT"),
    ("author_birth_year", "INTEGER"),
    ("author_death_year", "INTEGER"),
    ("volume_note", "TEXT"),
    ("analysis_eligible", "INTEGER DEFAULT 1"),
]


_EVENTS_MIGRATIONS = [
    ("duration_modifier", "TEXT"),  # Weeks 9-10
]


def _migrate_columns(conn: sqlite3.Connection, table: str, migrations) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for col, coltype in migrations:
        if col not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")


def _migrate_novels_columns(conn: sqlite3.Connection) -> None:
    _migrate_columns(conn, "novels", _NOVELS_MIGRATIONS)
    _migrate_columns(conn, "temporal_events", _EVENTS_MIGRATIONS)


def _migrate_granularity_comparison(conn: sqlite3.Connection) -> None:
    """granularity_comparison shipped in Weeks 3-4 as a placeholder (sentence/
    division/page flags, no link to its event) and never held a row. Replace
    it with the real schema -- but only if it's still empty, so this can
    never discard results."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(granularity_comparison)")}
    if "event_id" in cols:
        return
    if conn.execute("SELECT COUNT(*) FROM granularity_comparison").fetchone()[0]:
        raise RuntimeError("granularity_comparison has old-schema rows; migrate manually")
    conn.execute("DROP TABLE granularity_comparison")
    conn.executescript(SCHEMA)


def get_connection(db_path: Path = config.DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(SCHEMA)
    _migrate_novels_columns(conn)
    _migrate_granularity_comparison(conn)
    return conn


def _nearest_id(offsets: list[int], ids: list[int], char_pos: int) -> int | None:
    """Given parallel lists of (start offsets, row ids) sorted by offset,
    return the id of the last one whose offset is <= char_pos."""
    if not offsets:
        return None
    i = bisect_right(offsets, char_pos) - 1
    return ids[i] if i >= 0 else None


def insert_novel(conn: sqlite3.Connection, novel: ParsedNovel, decade: str) -> int:
    cur = conn.cursor()
    cur.execute(
        """INSERT OR REPLACE INTO novels
           (filename, title, author, author_gender, year, decade, source, word_count, cleaned_text)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (novel.filename, novel.title, novel.author, novel.author_gender,
         novel.year, decade, novel.source, novel.word_count, novel.cleaned_text),
    )
    novel_id = cur.lastrowid

    # wipe any prior rows for this novel (idempotent re-ingest)
    cur.execute("DELETE FROM divisions WHERE novel_id = ?", (novel_id,))
    cur.execute("DELETE FROM pages WHERE novel_id = ?", (novel_id,))
    cur.execute("DELETE FROM sentences WHERE novel_id = ?", (novel_id,))
    cur.execute("DELETE FROM qc_log WHERE novel_id = ?", (novel_id,))

    division_ids, division_offsets = [], []
    for d in novel.divisions:
        cur.execute(
            """INSERT INTO divisions (novel_id, division_type, division_number, title, start_char, order_index)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (novel_id, d.division_type, d.number, d.title, d.start_char, d.order_index),
        )
        division_ids.append(cur.lastrowid)
        division_offsets.append(d.start_char)

    page_ids, page_offsets = [], []
    for p in novel.pages:
        cur.execute(
            """INSERT INTO pages (novel_id, page_number, char_offset, order_index)
               VALUES (?, ?, ?, ?)""",
            (novel_id, p.page_number, p.char_offset, p.order_index),
        )
        page_ids.append(cur.lastrowid)
        page_offsets.append(p.char_offset)

    for s in novel.sentences:
        div_id = _nearest_id(division_offsets, division_ids, s.start_char)
        page_id = _nearest_id(page_offsets, page_ids, s.start_char)
        cur.execute(
            """INSERT INTO sentences
               (novel_id, division_id, page_id, sentence_index, text, start_char, end_char, token_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (novel_id, div_id, page_id, s.sentence_index, s.text, s.start_char, s.end_char, len(s.text.split())),
        )

    for w in novel.warnings:
        cur.execute("INSERT INTO qc_log (novel_id, warning) VALUES (?, ?)", (novel_id, w))

    conn.commit()
    return novel_id
