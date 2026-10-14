# Phase 1 — Corpus Setup & Data Pipeline

Literary Time Visualization in 19th/Early-20th-Century Novels — Shawna Ross GAR project.

Phase 1 is complete and validated against the real corpus: all 100 novels
downloaded, parsed, and ingested; `verify.py` passes; author gender and
volume-completeness metadata backfilled from the corpus's own
documentation. Phase 2 (temporal analysis engine) is about 75% complete:
tense shifts, explicit temporal markers, scene boundaries, scene duration,
and flashback/flash-forward detection all run end-to-end on the 5 Phase 2
test novels, writing a confidence-scored temporal event log, and
`verify_phase2.py` passes. Granularity comparison, the full 91-novel run,
and initial visualizations are next. See the biweekly reports for the full
write-up (architecture diagrams, corpus-wide analysis, findings, and open
items for review):
[`reports/weeks-01-02.md`](reports/weeks-01-02.md),
[`reports/weeks-03-04.md`](reports/weeks-03-04.md),
[`reports/weeks-05-06.md`](reports/weeks-05-06.md).

## Corpus source correction

The scope-of-work document points to `linguisticsathuddersfield.com/hum19uk-corpus`,
which no longer serves the files. As of Sept 2026 the corpus (same HUM19UK — 100 novels,
1800–1899, 13M words, 50/50 male/female, ~10 per decade) is mirrored decade-by-decade by
Uppsala University's English Department:

https://www.uu.se/en/department/english/research/english-linguistics/electronic-resource-projects/hum19-huddersfield-utrecht-uppsala-middelburg-corpus-of-19th-century-british-and-irish-fiction

`src/config.py` has the 10 decade-zip URLs plus the "Description of Contents" zip hardcoded.

## What's here

```
src/
  config.py          all tunable regex patterns + the download URLs, in one place
  download_corpus.py fetch + extract the decade zips (--with-description for the
                      corpus's own bibliographic PDF, used by enrich_metadata.py)
  inspect_corpus.py  calibration tool -- run on real files before trusting preprocess.py
  preprocess.py       core parser: encoding normalization, header extraction,
                       division/page tag stripping with offset tracking, sentence segmentation
  db.py               SQLite schema + insert logic
  build_pipeline.py   CLI: raw .txt files -> corpus.db
  verify.py           checks the Phase 1 deliverables against the DB
  analyze_corpus.py   corpus-wide + per-novel descriptive analysis (--deep for
                       temporal-marker/vocabulary extraction), exports CSV
  enrich_metadata.py  backfills real author gender/birth-death/volume-completeness
                       from the corpus's own Contents PDF (99% of this data doesn't
                       exist in the per-novel text files themselves); also sets
                       novels.analysis_eligible = 0 for the 9 confirmed
                       single-volume-of-a-multi-volume-original novels
  temporal/            Phase 2 engine (heuristic, rule-based -- no trained models):
    nlp_setup.py          shared spaCy pipeline (tagger only -- parser/NER/
                           lemmatizer/morphologizer all disabled, unused)
    tense_tagger.py        rule-based dominant-tense classification per sentence
    temporal_markers.py    explicit temporal-marker phrases, grouped into 6
                           categories (forward_jump, retrospective, ...)
    scene_boundaries.py    scenes from asterisk breaks, division fallback
    scene_duration.py      relative scene duration: discourse length vs.
                           forward jumps (no absolute story-time claimed)
    flashback_detector.py  flashback / flash-forward, 2-of-3 SOW signals
    event_log.py           writes the temporal_events table
    confidence.py           shared confidence-score clamp helper
  analyze_temporal.py CLI: runs every Phase 2 detector per novel ->
                       sentence_features + temporal_events
  verify_phase2.py    checks the Phase 2 deliverables against the DB
tests/
  test_preprocess.py  unit tests against fixtures matching the real file format
  test_temporal.py    unit tests for every Phase 2 detector
reports/
  weeks-01-02.md       biweekly report: Phase 1 pipeline, corpus-wide analysis
  weeks-03-04.md       biweekly report: GitHub publish, Phase 2 kickoff
  weeks-05-06.md       biweekly report: Phase 2 detectors + temporal event log
  data/novel_stats.csv full per-novel data (all 100 novels, all extracted fields)
```

## Corpus format (verified against real downloaded files)

The regexes in `config.py` were originally written from HUM19UK's public
documentation (which suggested TEI-style `<div type="chapter" n="3">` tags)
without having downloaded a real file to check against. That assumption
was wrong. The real format, confirmed against files from 3+ decades:

- Header block: `<Title: ...>`, `<Publication date: ...>` (also seen:
  `Date of publication`, and a `Publication data` typo), `<Page numbers:
  yes|no>`, `<Source: ...>` — bracket-wrapped, not bare `Title: ...` lines.
- `<text>...</text>` bounds the real novel body in every file (used as the
  hard content/header split point — also strips trailing OCR errata some
  Gutenberg-sourced files carry after `</text>`).
- Divisions: `<div title="VOL. I.">` / `<chapter title="...">` — no
  `type=`/`n=` attributes.
- Page markers: two conventions correlated with source library — bare
  `<3>` (Chawton House Collection) vs. `<Page 3 >` (public-library-UK).
  Only 9/100 novels have any page markers at all (most sources declare
  `Page numbers: no`), and only 6 of those 9 are dense enough to be real
  pagination rather than sparse editorial citations — see the report.

If a future decade or source introduces a new convention,
`inspect_corpus.py` is the calibration tool: it prints a file's raw
head/tail plus how many times each `config.py` pattern matches, so a
0-match regex is obvious immediately rather than silently ingesting
garbage.

```bash
python -m src.inspect_corpus data/raw/<decade>/*.txt | less
```

## Running Phase 1

```bash
# 1. download everything (or one decade with --decade); --with-description
#    also fetches the corpus's own bibliographic PDF for enrich_metadata.py
python -m src.download_corpus --with-description

# 2. test run on 10 novels first, per the SOW's Phase 1 acceptance step
python -m src.build_pipeline --limit 10
python -m src.verify

# 3. once verify.py passes cleanly, run the full corpus
python -m src.build_pipeline
python -m src.verify

# 4. backfill real author gender / birth-death / volume-completeness
#    (re-run this after any re-ingest -- step 3 resets these columns)
python -m src.enrich_metadata "data/raw/_description/HUM19UK Corpus Contents.pdf"

# 5. corpus-wide + per-novel analysis, with CSV export
python -m src.analyze_corpus --deep --csv reports/data/novel_stats.csv
```

## Running Phase 2

Requires the Phase 1 database above, plus spaCy's English model:

```bash
pip install -r requirements.txt
python -m spacy download en_core_web_sm

# 1. the 5 Phase 2 test novels (Fleetwood, Wuthering Heights, Alice,
#    Black Beauty, Dracula) -- ~80 seconds
python -m src.analyze_temporal --test-slice

# 2. check the Phase 2 deliverables
python -m src.verify_phase2

# other scopes: one novel, or the first N / all 91 analysis-eligible novels
python -m src.analyze_temporal --novel 1847.txt
python -m src.analyze_temporal --limit 10
python -m src.analyze_temporal
```

The 9 single-volume novels (`analysis_eligible = 0`) are skipped unless
`--include-partial` is passed. Results land in two tables:
`sentence_features` (tense + marker phrases per sentence) and
`temporal_events` (the per-novel temporal event log: `tense_shift`,
`explicit_marker`, `scene_boundary`, `flashback`, `flashforward`, each with
a confidence in [0, 1] and its sentence, division, and original page).
Re-running a novel replaces its previous results.

## Design decisions and how they set up Phase 2/3

- **Single-pass tag stripping with offset tracking** (`preprocess.py::_strip_tags_and_index`):
  rather than stripping tags then re-scanning for positions, the parser walks the raw text
  once, building the cleaned text incrementally and recording each division/page tag's
  offset *in the cleaned text* as it's produced. This is what makes page-anchored and
  chapter-anchored visualizations ("this shift occurs at page 47") a plain SQL join later,
  instead of a second pass over raw files in Phase 3.
- **Sentence-level granularity only, in Phase 1.** The SOW's Phase 2 wants word/sentence/
  scene/page granularity comparison. Word-level tense tagging is Phase 2's job (it needs
  spaCy/NLTK POS tagging, not just segmentation); Phase 1 hands it clean sentences already
  linked to their nearest page and division via foreign keys, via `_nearest_id` (bisect over
  sorted offsets) in `db.py`. Sentence segmentation uses the trained NLTK Punkt English
  model (not a blank tokenizer — a blank one mis-splits on ordinary abbreviations).
- **Dual division-detection strategy**: tries the corpus's real bracket-tag convention first
  (`<div title="...">` / `<chapter title="...">`), falls back to plain-text markers
  (`CHAPTER III` on its own line) only if a file has zero tag matches — a defensive path for
  any future decade that might use plain text instead.
- **QC log per novel** (`qc_log` table): every parsed novel that's missing a title, has no
  detected divisions, no page markers, or is suspiciously short gets a warning row instead of
  silently ingesting bad data. `verify.py` and `build_pipeline.py` both surface these — this
  directly satisfies the SOW's "clean and verify at least 10 test novels" step, and the
  warning list becomes ready-made content for the Phase 4 methodology doc's limitations
  section.
- **Idempotent re-ingest**: `insert_novel` deletes and re-inserts a novel's child rows on
  every run (keyed on `filename UNIQUE`), so re-running the pipeline after a regex fix in
  `config.py` doesn't create duplicate rows. Note this also resets `enrich_metadata.py`'s
  backfilled columns (`author_gender`, `author_birth_year`, `author_death_year`,
  `volume_note`) — re-run `enrich_metadata.py` after any re-ingest.

## Acceptance checklist (SOW Phase 1)

- [x] `python -m src.download_corpus` — full 100-novel corpus in `data/raw/`
- [x] `python -m src.build_pipeline --limit 10` then `python -m src.verify` passes
- [x] `python -m src.build_pipeline` (full run) then `python -m src.verify` passes
- [x] `corpus.db` contains `novels`, `divisions`, `pages`, `sentences`, `qc_log` populated
- [x] `pytest tests/` green (30/30 — 7 Phase 1 + 23 Phase 2 tests)

## Acceptance checklist (SOW Phase 2)

- [x] Temporal analysis engine (Python module) — `src/temporal/` + `src/analyze_temporal.py`
- [x] Structured temporal event log per novel — `temporal_events` (SQLite, JSON detail per event)
- [x] Detects the 4 required feature types: tense shifts, temporal markers,
      scene boundaries, flashbacks/flash-forwards
- [x] Confidence scoring on every detection
- [x] Working analysis for the 5 test novels — `python -m src.verify_phase2` passes
- [ ] Granularity comparison (sentence vs. division vs. page) — Weeks 7-9
- [ ] Full 91-novel run — Weeks 7-9
- [ ] Initial visualizations for the 5 test novels — Weeks 7-9

See [`reports/weeks-01-02.md`](reports/weeks-01-02.md) for corpus-wide
analysis, deviations from the SOW worth flagging to Shawna (page-marker
coverage, 9 partial-volume novels, the dead corpus URL), and open items;
see [`reports/weeks-03-04.md`](reports/weeks-03-04.md) for the GitHub
publish and Phase 2 kickoff; see
[`reports/weeks-05-06.md`](reports/weeks-05-06.md) for the Phase 2
detectors, the temporal event log, and how the detections hold up when read
against the novels themselves.
