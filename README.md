# Phase 1 — Corpus Setup & Data Pipeline

Literary Time Visualization in 19th/Early-20th-Century Novels — Shawna Ross GAR project.

Phase 1 is complete and validated against the real corpus: all 100 novels
downloaded, parsed, and ingested; `verify.py` passes; author gender and
volume-completeness metadata backfilled from the corpus's own
documentation. Phase 2 (temporal analysis engine) is complete: tense
shifts, explicit temporal markers (phrases, calendar dates, clock times),
scene boundaries, scene duration, and flashback/flash-forward detection run
across all 91 analysis-eligible novels, writing a confidence-scored
temporal event log (344,675 events), and every event is compared across
four granularities (word, passage, scene, original page). Since Weeks 9-10
the markers come from a controlled vocabulary that merges Shawna Ross's
supplemental cue taxonomy (`src/temporal/cue_taxonomy.csv`), scholarly
apparatus is stripped from the corpus, and scene duration labels require
positive evidence rather than defaulting to "continuous".
`verify_phase2.py --require-full` passes, and the initial visualizations
for the 5 test novels are in `reports/figures/phase2/`. Since Weeks 9-10
the granularity comparison also has the author's own paragraph as a fifth
scale (in the 64 novels whose paragraphs survive), tested against the
10-sentence passage. Phase 3 (visualization suite) is complete: an
interactive Plotly Dash dashboard (`python -m src.dashboard`) shows all
three of the SOW's views (timeline, pace/density, flashback map) for any of
the 91 novels, with SVG/PDF/PNG export, and publication figures for 9
novels are in `reports/figures/phase3/`. The gender difference in
iterative and seasonal time (Weeks 9-10) has been tested to journal
standard (`python -m src.analyze_gender_time`). See the
biweekly reports for the full write-up (architecture diagrams, corpus-wide
analysis, findings, and open items for review):
[`reports/weeks-01-02.md`](reports/weeks-01-02.md),
[`reports/weeks-03-04.md`](reports/weeks-03-04.md),
[`reports/weeks-05-06.md`](reports/weeks-05-06.md),
[`reports/weeks-07-08.md`](reports/weeks-07-08.md),
[`reports/weeks-09-10.md`](reports/weeks-09-10.md),
[`reports/weeks-11-12.md`](reports/weeks-11-12.md).

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
                       division/page tag stripping with offset tracking, scholarly
                       apparatus removal (prefaces, notes, glossaries, imprints --
                       fictional frames kept), sentence segmentation
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
    tense_tagger.py        rule-based dominant tense per sentence, plus the
                           position of every verb construction (word level)
    temporal_markers.py    matches the cue taxonomy below, plus calendar
                           dates (numeric and spelled out), clock times, and
                           years (incl. the withheld "17--")
    cue_taxonomy.csv       the controlled vocabulary: 238 rows in 15
                           categories and 6 tiers, merging the original list
                           with Shawna Ross's supplemental taxonomy; each row
                           active, covered by a broader pattern, or excluded
                           with its reason. Editable without touching code
    scene_boundaries.py    scenes from asterisk breaks, division fallback
    scene_duration.py      evidence-based scene duration label (jump /
                           iterative / continuous / anchored / unmarked --
                           never a default) and a lower bound on the story
                           time the scene's cues state
    flashback_detector.py  flashback / flash-forward, 2-of-3 SOW signals
    granularity.py         4 temporal signals x 5 scales (word, paragraph,
                           passage, scene, page) and, per event, visible or
                           washed out; paragraph only where the source kept
                           paragraphs (64 novels), page only where pagination
                           is reliable
    event_log.py           writes the temporal_events table
    confidence.py           shared confidence-score clamp helper
  analyze_temporal.py CLI: runs every Phase 2 detector + the granularity
                       comparison per novel
  verify_phase2.py    checks the Phase 2 deliverables against the DB
  analyze_temporal_corpus.py  corpus-level findings: per-novel table, trends
                       across the century (sentence-length controlled),
                       author gender, threshold re-check
  plot_phase2.py      Phase 2 initial visualizations + corpus figures
  compare_middle_scale.py  the paragraph-vs-passage study: the author's
                       paragraphs as the middle scale in the 64 novels that
                       keep them, against the 10-sentence passage
  viz/                 Phase 3 visualization layer:
    data.py               reads one novel's scenes, pages, and labelled
                           events from corpus.db (read-only)
    timeline.py           the SOW's timeline view (Plotly)
    pace.py               the SOW's pace/density plot: story time per
                           1,000 words, scene by scene, + cue densities
    flashback_map.py      the SOW's flashback map: flashback / flash-forward
                           density and events, filled or hollow by whether
                           they survive at a chosen scale
    style.py              the shared, validated palette
  dashboard.py        Phase 3 interactive dashboard (Plotly Dash): pick a
                       novel and a view (3 tabs), zoom/pan, export SVG/PDF/PNG
  export_figures.py   batch publication export -> reports/figures/phase3/
  analyze_gender_time.py  the gender difference in iterative and seasonal
                       time, tested to journal standard (effect sizes,
                       count models with controls, permutation, stability,
                       the precision audit)
tests/
  test_preprocess.py  unit tests against fixtures matching the real file format
  test_temporal.py    unit tests for every Phase 2 detector and the
                       granularity comparison
  test_viz.py         unit tests for the Phase 3 data layer and all three views
reports/
  weeks-01-02.md       biweekly report: Phase 1 pipeline, corpus-wide analysis
  weeks-03-04.md       biweekly report: GitHub publish, Phase 2 kickoff
  weeks-05-06.md       biweekly report: Phase 2 detectors + temporal event log
  weeks-07-08.md       biweekly report: Phase 2 complete, first findings
  weeks-09-10.md       biweekly report: Shawna Ross's cue taxonomy, apparatus
                        removal, two findings revised, the paragraph-vs-passage
                        study, Phase 3 dashboard + timeline view
  weeks-11-12.md       biweekly report: Phase 3 complete (pace/density plot,
                        flashback map, publication figures), the gender
                        finding tested to journal standard
  data/novel_stats.csv full per-novel data (all 100 novels, all extracted fields)
  data/temporal_novel_stats.csv     per-novel temporal measures (91 novels)
  data/temporal_corpus_summary.json corpus-level temporal findings
  data/middle_scale_comparison.json paragraph vs. passage results
  data/middle_scale_by_novel.csv    the same, per novel
  figures/phase2/      current Phase 2 figures (PNG) + interactive/ (HTML)
  data/gender_time*.{json,csv}      the gender analysis, overall and per novel
  data/gender_precision_audit.csv   130 hand-checked cue hits behind it
  figures/phase3/      dashboard screenshots + exports of all three views (SVG/PDF/PNG)
  figures/weeks-NN-NN/ each report's own figures, as of its run
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
#    Black Beauty, Dracula) -- under a minute
python -m src.analyze_temporal --test-slice
python -m src.verify_phase2

# 2. all 91 analysis-eligible novels -- 45 min to 1 h 50 min on one CPU core
python -m src.analyze_temporal
python -m src.verify_phase2 --require-full

# 3. corpus-level findings and figures
python -m src.analyze_temporal_corpus   # -> reports/data/temporal_*
python -m src.plot_phase2               # -> reports/figures/phase2/
python -m src.compare_middle_scale      # paragraph vs. passage -> reports/data/middle_scale_*
python -m src.analyze_gender_time       # gender and iterative/seasonal time -> reports/data/gender_time*

# other scopes: one novel, or the first N eligible novels
python -m src.analyze_temporal --novel 1847.txt
python -m src.analyze_temporal --limit 10
```

The 9 single-volume novels (`analysis_eligible = 0`) are skipped unless
`--include-partial` is passed. Results land in four tables:

- `sentence_features`: tense and temporal markers per sentence.
- `temporal_events`: the per-novel temporal event log (`tense_shift`,
  `explicit_marker`, `scene_boundary`, `flashback`, `flashforward`), each
  with a confidence in [0, 1] and its sentence, division, and original page.
  `duration_modifier = 'multi-unit'` marks iterative events (habitual cues
  such as "every Sunday", "used to", "of an evening"): their story-time
  span is unknown but likely more than one occasion.
- `granularity_units`: retrospection, prospection, marker density, and
  tense churn, measured per 25-word bin, author's paragraph (where the
  source kept paragraphs), 10-sentence passage, scene, and original page.
- `granularity_comparison`: for every event, whether it still stands out at
  each of those scales, or was washed out.

Re-running a novel replaces its previous results.

## Running Phase 3

```bash
# the interactive dashboard -- then open http://127.0.0.1:8050
python -m src.dashboard

# publication figures (SVG, PDF, PNG), all three views -> reports/figures/phase3/
python -m src.export_figures                        # the publication set (9 novels)
python -m src.export_figures --novel 1862.txt       # any novel, repeatable
python -m src.export_figures --all                  # all 91
```

The dashboard reads `corpus.db` read-only. Pick a novel and a view
(timeline, pace & density, flashback map), set the flashback confidence
threshold, the timeline's event lanes, or the scale the flashback map judges
survival at; zoom by dragging, double-click to reset, and export the current
view at publication size. Static export uses Kaleido, which needs a local
Chrome or Edge.

To change the temporal vocabulary, edit `src/temporal/cue_taxonomy.csv`:
`match` is `phrase` (whole-word, case-insensitive), `phrase_cs`
(case-sensitive, e.g. "Lent" but not "lent"), `regex`, or `regex_cs`; only
`active` rows are matched. Run `pytest tests/` (it checks every row) and
re-run steps 1-3.

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
- **Scholarly apparatus removed, fiction kept** (Weeks 9-10, at Shawna's direction): every
  bracket-wrapped span the compilers used for title pages, imprints, dedications, prefaces,
  contents, footnotes, glossaries, and illustration captions is dropped from `cleaned_text`
  (640 spans, ~48,000 words, in 84 novels; all 659 were read before the rule was trusted).
  The 18 spans that belong to the fiction — The Last Man's Sibyl's-leaves introduction,
  Quatermain's and Pooter's prefaces, The Heavenly Twins' Proem, John Inglesant's fictional
  editor, Oldbuck's spoken asides — are listed in `config.FICTION_BRACKETS` and keep their
  text. The same rebuild fixed a Phase 1 offset drift: whitespace was collapsed *after*
  division/page offsets were recorded, so later chapter starts landed mid-sentence.

## Acceptance checklist (SOW Phase 1)

- [x] `python -m src.download_corpus` — full 100-novel corpus in `data/raw/`
- [x] `python -m src.build_pipeline --limit 10` then `python -m src.verify` passes
- [x] `python -m src.build_pipeline` (full run) then `python -m src.verify` passes
- [x] `corpus.db` contains `novels`, `divisions`, `pages`, `sentences`, `qc_log` populated
- [x] `pytest tests/` green (65/65 — 9 Phase 1 + 48 Phase 2 + 8 Phase 3 tests)

## Acceptance checklist (SOW Phase 2)

- [x] Temporal analysis engine (Python module) — `src/temporal/` + `src/analyze_temporal.py`
- [x] Structured temporal event log per novel — `temporal_events` (SQLite, JSON detail per event)
- [x] Detects the 4 required feature types: tense shifts, temporal markers,
      scene boundaries, flashbacks/flash-forwards
- [x] Confidence scoring on every detection
- [x] Multi-granularity analysis and granularity comparison — word, paragraph
      (where it survives), passage, scene, and page, for every event
- [x] Working analysis for the 5 test novels, and for all 91 eligible novels —
      `python -m src.verify_phase2 --require-full` passes
- [x] Initial visualizations for the 5 test novels — `reports/figures/phase2/`

## Acceptance checklist (SOW Phase 3)

- [x] Interactive dashboard (Plotly Dash): select a novel → see visualizations →
      zoom/pan → export — `python -m src.dashboard`, all 91 novels, 3 views
- [x] Timeline view: scene boundaries, durations, labeled events (flashbacks,
      temporal jumps) — `src/viz/timeline.py`
- [x] Pace/density plot: story time per 1,000 words against discourse, scene
      by scene, with cue densities — `src/viz/pace.py`
- [x] Flashback map: flashback/flash-forward annotations with clear visual
      distinction — `src/viz/flashback_map.py`
- [x] Export to publication-quality static figures (SVG/PDF) — dashboard
      buttons and `python -m src.export_figures`
- [x] Publication-quality figures for 5+ novels — all three views for 9
      novels in `reports/figures/phase3/`
- [x] Screenshots and exports for teaching and research — `reports/figures/phase3/`
- Comparative view (SOW: optional) — dropped at the Weeks 11-12 supervisor
  meeting

See [`reports/weeks-01-02.md`](reports/weeks-01-02.md) for corpus-wide
analysis, deviations from the SOW worth flagging to Shawna (page-marker
coverage, 9 partial-volume novels, the dead corpus URL), and open items;
see [`reports/weeks-03-04.md`](reports/weeks-03-04.md) for the GitHub
publish and Phase 2 kickoff; see
[`reports/weeks-05-06.md`](reports/weeks-05-06.md) for the Phase 2
detectors, the temporal event log, and how the detections hold up when read
against the novels themselves; see
[`reports/weeks-07-08.md`](reports/weeks-07-08.md) for Phase 2's
completion (multi-granularity comparison, absolute time, the full 91-novel
run) and the first corpus findings; see
[`reports/weeks-09-10.md`](reports/weeks-09-10.md) for Shawna Ross's
temporal-cue taxonomy, the apparatus removal, the two findings it revised,
the paragraph-vs-passage study of the middle scale, and the start of
Phase 3 (dashboard and timeline view); see
[`reports/weeks-11-12.md`](reports/weeks-11-12.md) for Phase 3's completion
(pace/density plot, flashback map, publication figures) and the gender
finding tested to journal standard.
