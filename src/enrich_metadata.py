"""
Backfill author gender and birth/death years, and flag partial-volume
novels (setting novels.analysis_eligible = 0 for them), from HUM19UK's own
"Corpus Contents" PDF -- the corpus creators' official bibliographic index
(100 rows: year, author, gender, lifespan, title, source, notes).

Why this exists: per-novel header files carry a Gender field in only 1 of
100 novels (see reports/weeks-01-02.md), so author gender is essentially
unusable straight from the downloaded .txt files. The compilers' own PDF
has it for all 100, plus author birth/death years and an explicit
"Volume I only" / "All N volumes" note wherever a file is a partial
extract of a multi-volume original -- both of which are otherwise
undiscoverable from the text files alone.

Usage:
    python -m src.download_corpus --with-description   # fetches the PDF to
                                                         # data/raw/_description/
    python -m src.enrich_metadata "data/raw/_description/HUM19UK Corpus Contents.pdf"

Requires PyPDF2 (see requirements.txt). Matching PDF rows to DB novels is
by normalized title similarity (not year), because 2 of the 100
header-derived `year` values are themselves wrong (see Findings #6 in the
report) and can't be trusted as a join key.
"""
import argparse
import difflib
import re
import sqlite3
import sys

from . import config, db

# matches "Volume I only" / "Volume II only" -- the exact phrasing the PDF
# uses when a file is a partial extract. Deliberately narrow: volume_note
# also holds unrelated notes ("Published under pseudonym...", "Two
# authors", "All 3 volumes") that must NOT be treated as partial-volume
# flags -- a blanket "volume_note IS NOT NULL" check would incorrectly
# exclude those too (8 novels, including 2 explicitly marked complete).
VOLUME_ONLY_NOTE_PATTERN = re.compile(r"\bvolume\s+[ivxlc]+\s+only\b", re.IGNORECASE)

SOURCES = [
    "Gutenberg", "Chawton House", "Chadwyck Healey",
    "Chadwyck healey or archive.org", "Public Library UK",
    "Celebration of Women Writers",
]
_SRC_PATTERN = "|".join(re.escape(s) for s in SOURCES)
_ROW_RE = re.compile(r"^(?P<no>\d+)\s+(?P<year>\d{4}(?:-\d{4})?)\s+(?P<rest>.+)$")
_TAIL_RE = re.compile(
    rf"^(?P<names>.+?)\s+(?P<gender>[MF])\s+(?P<alive>[\d?]+[-–]+[\d?]+\??)\s+"
    rf"(?P<title>.+?)\s+(?P<source>{_SRC_PATTERN})\b\s*(?P<notes>.*)$"
)

# manual overrides for PDF/filename title spellings that differ too much
# for fuzzy matching to bridge safely (checked by hand against the corpus)
TITLE_ALIASES = {
    "ask mama": "ask mamma or the richest commoner in england",
}


def parse_contents_pdf(path: str) -> list[dict]:
    import PyPDF2
    reader = PyPDF2.PdfReader(path)
    text = "\n".join(page.extract_text() for page in reader.pages)
    lines = [l for l in text.split("\n") if l.strip()][1:]  # drop header row

    # the one row with two credited authors ("Diary of a Nobody") wraps
    # onto a second line that doesn't start with a row number -- stitch it
    # back onto the row above rather than treating it as its own row.
    fixed = []
    for line in lines:
        if re.match(r"^\d+\s", line):
            fixed.append(line)
        elif fixed:
            fixed[-1] += " | " + line.strip()

    parsed = []
    for line in fixed:
        m = _ROW_RE.match(line)
        if not m:
            print(f"  [skip] couldn't parse row: {line!r}", file=sys.stderr)
            continue
        tm = _TAIL_RE.match(m.group("rest"))
        if not tm:
            print(f"  [skip] couldn't parse row tail: {line!r}", file=sys.stderr)
            continue
        alive = tm.group("alive")
        birth, _, death = alive.partition("-") if "-" in alive else alive.partition("–")
        parsed.append({
            "no": int(m.group("no")),
            "year": m.group("year"),
            "names": tm.group("names").strip(),
            "gender": tm.group("gender"),
            "birth_year": birth.strip().rstrip("?") or None,
            "death_year": death.strip().rstrip("?") or None,
            "title": tm.group("title").strip(),
            "source": tm.group("source"),
            "notes": tm.group("notes").strip(),
        })
    return parsed


def _norm_title(t: str) -> str:
    t = t.lower()
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^(the|a|an) ", "", t)
    return TITLE_ALIASES.get(t, t)


def match_to_db(parsed: list[dict], db_novels: list[sqlite3.Row]) -> tuple[list, list, list]:
    """Fuzzy-match each PDF row to exactly one DB novel by normalized title
    similarity. Returns (matches, unmatched_pdf_rows, unmatched_db_novels)."""
    used_ids = set()
    matches = []
    for p in parsed:
        ptitle = _norm_title(p["title"])
        best, best_score = None, 0.0
        for n in db_novels:
            if n["id"] in used_ids:
                continue
            ntitle = _norm_title(n["title"] or "")
            score = difflib.SequenceMatcher(None, ptitle, ntitle).ratio()
            if ntitle.startswith(ptitle) or ptitle.startswith(ntitle):
                score += 0.3
            if score > best_score:
                best, best_score = n, score
        if best and best_score > 0.5:
            used_ids.add(best["id"])
            matches.append((p, best, best_score))
    unmatched_pdf = [p for p in parsed if p["no"] not in {m[0]["no"] for m in matches}]
    unmatched_db = [n for n in db_novels if n["id"] not in used_ids]
    return matches, unmatched_pdf, unmatched_db


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf_path", help='path to "HUM19UK Corpus Contents.pdf"')
    parser.add_argument("--dry-run", action="store_true", help="report matches without writing to the DB")
    args = parser.parse_args()

    if not config.DB_PATH.exists():
        print(f"No database at {config.DB_PATH}. Run build_pipeline.py first.", file=sys.stderr)
        sys.exit(1)

    parsed = parse_contents_pdf(args.pdf_path)
    print(f"parsed {len(parsed)} rows from the corpus contents PDF")

    conn = db.get_connection()  # also runs the novels-table column migration
    conn.row_factory = sqlite3.Row

    db_novels = conn.execute("SELECT id, filename, title FROM novels").fetchall()
    matches, unmatched_pdf, unmatched_db = match_to_db(parsed, db_novels)
    print(f"matched {len(matches)}/{len(parsed)}")
    if unmatched_pdf:
        print("UNMATCHED PDF ROWS (not applied):")
        for p in unmatched_pdf:
            print(f"  {p}")
    if unmatched_db:
        print("DB NOVELS WITH NO PDF MATCH (left unenriched):")
        for n in unmatched_db:
            print(f"  {dict(n)}")

    if args.dry_run:
        print("\n--dry-run: no changes written.")
        return

    n_partial = 0
    for p, n, score in matches:
        notes = p["notes"] or None
        eligible = 0 if (notes and VOLUME_ONLY_NOTE_PATTERN.search(notes)) else 1
        n_partial += 1 - eligible
        conn.execute(
            """UPDATE novels SET author_gender = ?, author_birth_year = ?,
               author_death_year = ?, volume_note = ?, analysis_eligible = ?
               WHERE id = ?""",
            (p["gender"], p["birth_year"], p["death_year"], notes, eligible, n["id"]),
        )
    conn.commit()
    print(f"\nbackfilled author_gender/author_birth_year/author_death_year/volume_note "
          f"for {len(matches)} novels")
    print(f"analysis_eligible: {len(matches) - n_partial} eligible, "
          f"{n_partial} excluded (confirmed single-volume extracts)")
    conn.close()


if __name__ == "__main__":
    main()
