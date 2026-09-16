"""
Descriptive analysis over the Phase 1 SQLite database -- corpus composition,
coverage, and distribution, at both the full-corpus and per-novel level.

This is NOT Phase 2's temporal analysis engine (tense shifts, flashback
detection, etc.) -- it characterizes the *structure* of what got ingested
(word/sentence/division counts, page-marker coverage, provenance mix,
outliers) so Phase 2/3 scope decisions can be made from real numbers
instead of the SOW's corpus estimates.

Usage:
    python -m src.analyze_corpus                    # print full report to stdout
    python -m src.analyze_corpus --csv out.csv       # also write per-novel CSV
"""
import argparse
import csv
import re
import sqlite3
import statistics as stats
import sys
from collections import Counter

from . import config

# title-text heuristic for "this looks like one volume of a multi-volume
# original" -- kept only as a cross-check against the authoritative
# `volume_note` column (from enrich_metadata.py / the corpus's own
# "Corpus Contents" PDF), which is what should actually be trusted. The
# heuristic both over- and under-fires: it flagged 1812.txt from its
# "Vol. 1-3" title even though the PDF confirms that file has all 3
# volumes, and it missed 1851.txt (Lavengro) entirely because nothing in
# that file's title hints it's volume II only -- that fact only exists in
# the compilers' own documentation.
VOLUME_ONLY_NOTE_PATTERN = re.compile(r"\bvolume\s+[ivxlc]+\s+only\b", re.IGNORECASE)
MULTIVOLUME_TITLE_PATTERN = re.compile(
    r'\bvol(?:ume)?s?\.?\s*[ivxlc0-9]+\b|\b(?:of|in)\s+\d\s+vol|\bpart\s+[ivxlc0-9]+\b',
    re.IGNORECASE,
)

# seed phrases from the SOW's own "explicit temporal markers" examples, plus
# a few obvious variants -- a feasibility sounding for Phase 2, NOT a claim
# that this is the actual temporal-marker detector (that's Phase 2's job).
TEMPORAL_MARKER_PHRASES = [
    "years later", "months later", "days later", "weeks later",
    "at dawn", "at dusk", "in the meantime", "meanwhile",
    "the following day", "the next day", "years before", "long ago",
    "years ago",
]


def _dist(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "min": None, "max": None, "mean": None, "median": None, "stdev": None}
    return {
        "n": len(values),
        "min": min(values),
        "max": max(values),
        "mean": round(stats.mean(values), 1),
        "median": stats.median(values),
        "stdev": round(stats.stdev(values), 1) if len(values) > 1 else 0.0,
    }


def _print_dist(label: str, d: dict, unit: str = ""):
    print(f"  {label}: n={d['n']} min={d['min']} max={d['max']} "
          f"mean={d['mean']}{unit} median={d['median']}{unit} stdev={d['stdev']}")


def fetch_novel_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Per-novel stats, computed as separate single-table aggregates and
    merged in Python -- joining divisions+pages+sentences directly in one
    query multiplies rows across all three tables per novel (a novel with
    50 divisions x 300 pages x 8000 sentences would blow up to ~120M
    intermediate rows), which is both wrong and pathologically slow."""
    novels = conn.execute("""
        SELECT id, filename, title, author, author_gender, author_birth_year,
               author_death_year, volume_note, year, decade, source, word_count
        FROM novels ORDER BY year, filename
    """).fetchall()

    div_stats = {r["novel_id"]: r for r in conn.execute("""
        SELECT novel_id, COUNT(*) AS division_count,
               SUM(CASE WHEN division_type = 'chapter' THEN 1 ELSE 0 END) AS chapter_count,
               SUM(CASE WHEN division_type = 'volume'  THEN 1 ELSE 0 END) AS volume_count
        FROM divisions GROUP BY novel_id
    """)}
    page_stats = {r["novel_id"]: r["page_count"] for r in conn.execute("""
        SELECT novel_id, COUNT(*) AS page_count FROM pages GROUP BY novel_id
    """)}
    sentence_stats = {r["novel_id"]: r for r in conn.execute("""
        SELECT novel_id, COUNT(*) AS sentence_count,
               AVG(token_count) AS avg_sentence_words,
               MIN(token_count) AS min_sentence_words,
               MAX(token_count) AS max_sentence_words
        FROM sentences GROUP BY novel_id
    """)}

    merged = []
    for n in novels:
        d = div_stats.get(n["id"])
        s = sentence_stats.get(n["id"])
        merged.append({
            **{k: n[k] for k in n.keys()},
            "division_count": d["division_count"] if d else 0,
            "chapter_count": d["chapter_count"] if d else 0,
            "volume_count": d["volume_count"] if d else 0,
            "page_count": page_stats.get(n["id"], 0),
            "sentence_count": s["sentence_count"] if s else 0,
            "avg_sentence_words": s["avg_sentence_words"] if s else None,
            "min_sentence_words": s["min_sentence_words"] if s else None,
            "max_sentence_words": s["max_sentence_words"] if s else None,
        })
    return merged


def fetch_qc_warnings(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("""
        SELECT n.filename, n.decade, q.warning
        FROM qc_log q JOIN novels n ON n.id = q.novel_id
        ORDER BY n.filename
    """).fetchall()


def fetch_outlier_sentences(conn: sqlite3.Connection, long_threshold=150, n=10) -> list[sqlite3.Row]:
    """Very long 'sentences' usually mean the tokenizer missed a boundary
    (unclosed quote, abbreviation it doesn't know, stray markup) -- useful
    as a QC signal, not a claim that these are real 150+ word sentences."""
    return conn.execute(f"""
        SELECT n.filename, s.sentence_index, s.token_count, substr(s.text, 1, 90) AS preview
        FROM sentences s JOIN novels n ON n.id = s.novel_id
        WHERE s.token_count >= {long_threshold}
        ORDER BY s.token_count DESC LIMIT {n}
    """).fetchall()


def detect_multivolume_authoritative(rows) -> list[dict]:
    """Novels confirmed partial by the corpus's own documentation
    (volume_note like 'Volume I only') -- trust this over the title regex."""
    return [r for r in rows if r["volume_note"] and VOLUME_ONLY_NOTE_PATTERN.search(r["volume_note"])]


def detect_multivolume_heuristic(rows) -> list[dict]:
    """Title-text guess only -- see VOLUME_ONLY_NOTE_PATTERN's comment for
    why this disagrees with the authoritative list."""
    return [r for r in rows if r["title"] and MULTIVOLUME_TITLE_PATTERN.search(r["title"])]


def words_per_page_estimate(rows) -> dict:
    """Crude words-per-original-page ratio, derived only from the 9 novels
    that carry real page markers. word_count / page_count is a proxy for
    'words per page interval', not exact (page tags mark boundaries
    unevenly), but gives a defensible fallback constant if page-level
    visualization needs to be estimated for the other 91 novels."""
    per_novel = []
    for r in rows:
        if (r["page_count"] or 0) > 0 and r["word_count"]:
            per_novel.append(r["word_count"] / r["page_count"])
    return _dist(per_novel)


def length_metric_by_decade(rows, numerator_key, denom_key) -> dict:
    """Mean of numerator/denominator per novel, grouped by decade (e.g.
    words per chapter, words per sentence) -- skips novels with a zero
    denominator."""
    by_decade = {}
    for r in rows:
        denom = r[denom_key] or 0
        if denom == 0:
            continue
        by_decade.setdefault(r["decade"], []).append((r[numerator_key] or 0) / denom)
    return {d: round(stats.mean(v), 1) for d, v in sorted(by_decade.items())}


def scan_cleaned_text(conn: sqlite3.Connection, novel_ids_filenames) -> tuple[Counter, dict]:
    """Single pass over cleaned_text for every novel: counts SOW-example
    temporal-marker phrases (feasibility sounding for Phase 2) and computes
    a type-token ratio per novel (vocabulary richness, length-biased --
    reported with that caveat, not as a normalized metric)."""
    phrase_counts = Counter()
    ttr_by_novel = {}
    for novel_id, filename in novel_ids_filenames:
        text = conn.execute(
            "SELECT cleaned_text FROM novels WHERE id = ?", (novel_id,)
        ).fetchone()[0] or ""
        lower = text.lower()
        for phrase in TEMPORAL_MARKER_PHRASES:
            c = lower.count(phrase)
            if c:
                phrase_counts[phrase] += c
        words = re.findall(r"[a-z']+", lower)
        if words:
            ttr_by_novel[filename] = len(set(words)) / len(words)
    return phrase_counts, ttr_by_novel


def main():
    parser = argparse.ArgumentParser(description="Analyze the Phase 1 corpus database")
    parser.add_argument("--csv", default=None, help="write per-novel stats to this CSV path")
    parser.add_argument("--deep", action="store_true",
                         help="also scan cleaned_text for temporal-marker phrases and "
                              "vocabulary richness (reads every novel's full text -- slower)")
    args = parser.parse_args()

    if not config.DB_PATH.exists():
        print(f"No database at {config.DB_PATH}. Run build_pipeline.py first.", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = fetch_novel_rows(conn)

    print("=" * 72)
    print("FULL-CORPUS SUMMARY")
    print("=" * 72)
    n_novels = len(rows)
    total_words = sum(r["word_count"] or 0 for r in rows)
    total_sentences = sum(r["sentence_count"] or 0 for r in rows)
    total_divisions = sum(r["division_count"] or 0 for r in rows)
    total_pages = sum(r["page_count"] or 0 for r in rows)
    print(f"novels:            {n_novels}")
    print(f"total words:       {total_words:,}")
    print(f"total sentences:   {total_sentences:,}")
    print(f"total divisions:   {total_divisions:,}")
    print(f"total page marks:  {total_pages:,}")
    print(f"unique authors:    {len({r['author'] for r in rows if r['author']})}")

    print("\n--- word count per novel ---")
    _print_dist("words/novel", _dist([r["word_count"] for r in rows if r["word_count"]]))
    print("\n--- sentences per novel ---")
    _print_dist("sentences/novel", _dist([r["sentence_count"] for r in rows]))
    print("\n--- chapters per novel (division_type='chapter') ---")
    _print_dist("chapters/novel", _dist([r["chapter_count"] or 0 for r in rows]))
    print("\n--- avg sentence length (words) per novel ---")
    vals = [r["avg_sentence_words"] for r in rows if r["avg_sentence_words"] is not None]
    _print_dist("avg words/sentence", _dist(vals))

    print("\n--- decade breakdown ---")
    by_decade = {}
    for r in rows:
        d = by_decade.setdefault(r["decade"], {"novels": 0, "words": 0, "sentences": 0, "pages": 0})
        d["novels"] += 1
        d["words"] += r["word_count"] or 0
        d["sentences"] += r["sentence_count"] or 0
        d["pages"] += 1 if (r["page_count"] or 0) > 0 else 0
    for decade in sorted(by_decade):
        d = by_decade[decade]
        print(f"  {decade}: {d['novels']} novels, {d['words']:,} words, "
              f"{d['sentences']:,} sentences, {d['pages']}/{d['novels']} with page markers")

    print("\n--- source / provenance breakdown ---")
    source_counts = Counter(r["source"] or "(unknown)" for r in rows)
    for src, count in source_counts.most_common():
        with_pages = sum(1 for r in rows if (r["source"] or "(unknown)") == src and (r["page_count"] or 0) > 0)
        print(f"  {src}: {count} novels ({with_pages} with page markers)")

    print("\n--- page-marker coverage ---")
    with_pages = [r for r in rows if (r["page_count"] or 0) > 0]
    print(f"  {len(with_pages)}/{n_novels} novels have original page markers:")
    for r in with_pages:
        print(f"    {r['filename']} ({r['decade']}, {r['source']}): {r['page_count']} page marks")

    print("\n--- novels with zero divisions ---")
    zero_div = [r for r in rows if (r["division_count"] or 0) == 0]
    for r in zero_div:
        print(f"    {r['filename']} ({r['decade']}): {r['title']!r} by {r['author']}")

    print("\n--- longest 5 novels by word count ---")
    for r in sorted(rows, key=lambda r: r["word_count"] or 0, reverse=True)[:5]:
        print(f"    {r['filename']}: {r['word_count']:,} words -- {r['title']!r} ({r['author']}, {r['year']})")
    print("--- shortest 5 novels by word count ---")
    for r in sorted(rows, key=lambda r: r["word_count"] or 0)[:5]:
        print(f"    {r['filename']}: {r['word_count']:,} words -- {r['title']!r} ({r['author']}, {r['year']})")

    print("\n--- repeat authors (>1 novel in corpus) ---")
    author_counts = Counter(r["author"] for r in rows if r["author"])
    repeats = {a: c for a, c in author_counts.items() if c > 1}
    if repeats:
        for a, c in sorted(repeats.items(), key=lambda kv: -kv[1]):
            print(f"    {a}: {c} novels")
    else:
        print("    none -- every novel in the corpus has a distinct credited author")

    print(f"\n--- longest sentences (>=150 words; usually a tokenizer/markup QC signal, not real prose) ---")
    for r in fetch_outlier_sentences(conn):
        print(f"    {r['filename']} #{r['sentence_index']} ({r['token_count']} words): {r['preview']}...")

    print("\n--- QC warning breakdown ---")
    warnings = fetch_qc_warnings(conn)
    warning_counts = Counter(w["warning"] for w in warnings)
    for w, c in warning_counts.most_common():
        print(f"    {c}x: {w}")

    print("\n--- author gender (backfilled from the corpus's own Contents PDF"
          " via enrich_metadata.py) ---")
    gender_counts = Counter(r["author_gender"] for r in rows if r["author_gender"])
    for g, c in gender_counts.most_common():
        print(f"    {g}: {c}")
    if sum(gender_counts.values()) < n_novels:
        print(f"    (unknown/unenriched: {n_novels - sum(gender_counts.values())} "
              f"-- run 'python -m src.enrich_metadata <contents pdf>')")

    print("\n--- partial-volume novels: authoritative (volume_note) vs. title-text heuristic ---")
    authoritative = detect_multivolume_authoritative(rows)
    heuristic = detect_multivolume_heuristic(rows)
    auth_files = {r["filename"] for r in authoritative}
    heur_files = {r["filename"] for r in heuristic}
    print(f"  authoritative (volume_note says 'Volume N only'): {len(authoritative)}/{n_novels}")
    for r in authoritative:
        print(f"    {r['filename']}: {r['title']!r} -- {r['volume_note']}")
    print(f"  title-text heuristic only, not confirmed by volume_note: "
          f"{sorted(heur_files - auth_files)}")
    print(f"  authoritative only, title didn't hint at it: {sorted(auth_files - heur_files)}")

    print("\n--- words-per-page estimate (from the 9 novels with real page markers) ---")
    _print_dist("words/page", words_per_page_estimate(rows))

    print("\n--- avg words/chapter by decade (pacing proxy) ---")
    for decade, val in length_metric_by_decade(rows, "word_count", "chapter_count").items():
        print(f"    {decade}: {val:,.1f} words/chapter")

    print("\n--- avg words/sentence by decade (style proxy) ---")
    by_decade_sent = {}
    for r in rows:
        if r["avg_sentence_words"] is not None:
            by_decade_sent.setdefault(r["decade"], []).append(r["avg_sentence_words"])
    for decade in sorted(by_decade_sent):
        print(f"    {decade}: {stats.mean(by_decade_sent[decade]):.1f} words/sentence")

    if args.deep:
        print("\n--- deep scan: temporal-marker phrases + vocabulary richness "
              "(reading full cleaned_text for all novels) ---")
        ids_filenames = [(r["id"], r["filename"]) for r in rows]
        phrase_counts, ttr_by_novel = scan_cleaned_text(conn, ids_filenames)
        print("  temporal-marker phrase counts, corpus-wide (SOW example phrases, "
              "feasibility sounding only -- not a Phase 2 detector):")
        for phrase, count in phrase_counts.most_common():
            print(f"    {count:>5}x  \"{phrase}\"")
        print(f"    total: {sum(phrase_counts.values()):,} occurrences across {n_novels} novels")

        ttr_vals = list(ttr_by_novel.values())
        print("\n  vocabulary richness (type-token ratio, unique words / total words; "
              "biased toward shorter novels, not length-normalized):")
        _print_dist("TTR", _dist(ttr_vals))
        ranked = sorted(ttr_by_novel.items(), key=lambda kv: -kv[1])
        print("  highest TTR (5):", ", ".join(f"{f} ({v:.3f})" for f, v in ranked[:5]))
        print("  lowest TTR (5):", ", ".join(f"{f} ({v:.3f})" for f, v in ranked[-5:]))

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "filename", "title", "author", "author_gender", "author_birth_year",
                "author_death_year", "volume_note", "year", "decade", "source",
                "word_count", "division_count", "chapter_count", "volume_count",
                "page_count", "sentence_count", "avg_sentence_words",
                "min_sentence_words", "max_sentence_words",
            ])
            for r in rows:
                writer.writerow([
                    r["filename"], r["title"], r["author"], r["author_gender"],
                    r["author_birth_year"], r["author_death_year"], r["volume_note"],
                    r["year"], r["decade"], r["source"], r["word_count"], r["division_count"],
                    r["chapter_count"], r["volume_count"], r["page_count"], r["sentence_count"],
                    round(r["avg_sentence_words"], 2) if r["avg_sentence_words"] is not None else "",
                    r["min_sentence_words"], r["max_sentence_words"],
                ])
        print(f"\nper-novel CSV written to {args.csv}")

    conn.close()


if __name__ == "__main__":
    main()
