"""
Corpus-level analysis of the Phase 2 temporal event log, across every
analyzed novel (all 91 analysis-eligible novels after a full
analyze_temporal run).

Writes:
    reports/data/temporal_novel_stats.csv        one row per novel
    reports/data/temporal_corpus_summary.json    corpus-level findings

and prints a readable summary. Everything here is descriptive: rates are
heuristic detections, not ground truth. The trend and group tests
(Spearman correlation with publication year; Mann-Whitney U for author
gender) are exploratory evidence for close reading to test, not
conclusions, and are reported with a Bonferroni-corrected threshold
alongside the raw p-values.

Sentence length is a confound for any per-sentence measure. Mean sentence
length halves across the century (Spearman rho = -0.65 with year), and a
long sentence holds more verbs, so it is more likely to contain *some*
past-perfect clause. Per-sentence rates (past-perfect share of sentences,
flashbacks per 1,000 sentences) therefore fall over time even if
retrospection itself doesn't. Every trend is reported twice: raw, and as a
partial rank correlation with year controlling for mean sentence length.
Length-robust measures (share of verb constructions, events per 10k words)
are included alongside the per-sentence ones.

Weeks 9-10, with Shawna Ross's cue taxonomy (cue_taxonomy.csv) and the
apparatus-free corpus: the Weeks 7-8 metric family is re-run unchanged so
its findings can be compared directly, and the taxonomy's new categories
are tested as a second family with its own Bonferroni threshold (adding
them to the first would quietly raise the bar for findings already
reported). The retrospective-signposting trend is also re-checked on the
original phrase set and on Ross's additions separately, and scene duration
labels are summarized.

Usage: python -m src.analyze_temporal_corpus
"""
import csv
import json
import sqlite3
import statistics as st
from collections import Counter, defaultdict

import numpy as np
from scipy.stats import mannwhitneyu, pearsonr, rankdata, spearmanr

from . import config
from .temporal import flashback_detector
from .temporal.scene_duration import DURATION_LABELS
from .temporal.temporal_markers import CATEGORY_TIER, TAXONOMY_PATH

OUT_CSV = config.ROOT / "reports" / "data" / "temporal_novel_stats.csv"
OUT_JSON = config.ROOT / "reports" / "data" / "temporal_corpus_summary.json"

TENSES = ["past_simple", "past_perfect", "present", "present_perfect", "future_in_past", "other"]
CATEGORIES = list(CATEGORY_TIER)
LEVELS = ["word", "passage", "scene", "page"]

# metrics tested for a trend across the century and a difference by author
# gender. Per-sentence measures are kept so the sentence-length artifact is
# visible next to the length-robust versions, not hidden.
KEY_METRICS = [
    "mean_sentence_words",
    # per-sentence (length-confounded)
    "past_perfect_share", "present_share", "flashbacks_per_1k_sent", "tense_shifts_per_1k_sent",
    # length-robust
    "retrospection_per_verb", "prospection_per_verb",
    "flashbacks_per_10k_words", "flashbacks_hi_per_10k_words", "flashforwards_per_10k_words",
    "forward_jump_per_10k", "retrospective_per_10k", "abruptness_per_10k",
    "clock_time_per_10k", "calendar_date_per_10k", "median_scene_words",
]
# Weeks 9-10: the categories Shawna Ross's taxonomy introduced, tested as a
# separate family
TAXONOMY_METRICS = [
    "sequence_per_10k", "recollection_per_10k", "duration_per_10k", "frequency_per_10k",
    "holiday_per_10k", "seasonal_per_10k", "meal_per_10k", "biographical_per_10k",
    "travel_per_10k", "year_per_10k", "iterative_scene_share", "unmarked_scene_share",
]
ALPHA = 0.05


def novel_rows(conn) -> list[dict]:
    novels = {r[0]: {"novel_id": r[0], "filename": r[1], "title": r[2], "author": r[3],
                     "gender": r[4], "year": r[5], "decade": r[6], "words": r[7]}
              for r in conn.execute(
                  """SELECT id, filename, title, author, author_gender, year, decade, word_count
                     FROM novels WHERE id IN (SELECT DISTINCT novel_id FROM temporal_events)""")}

    for nid, n_sent in conn.execute(
            "SELECT novel_id, COUNT(*) FROM sentences GROUP BY novel_id"):
        if nid in novels:
            novels[nid]["sentences"] = n_sent

    tense = defaultdict(Counter)
    for nid, t, n in conn.execute(
            """SELECT s.novel_id, sf.dominant_tense, COUNT(*) FROM sentence_features sf
               JOIN sentences s ON s.id = sf.sentence_id GROUP BY s.novel_id, sf.dominant_tense"""):
        tense[nid][t] = n

    events = defaultdict(Counter)
    for nid, et, hi, n in conn.execute(
            """SELECT novel_id, event_type, confidence >= 0.8, COUNT(*) FROM temporal_events
               GROUP BY novel_id, event_type, confidence >= 0.8"""):
        events[nid][et] += n
        if hi:
            events[nid][et + "_hi"] += n

    cats = defaultdict(Counter)
    retro_split = defaultdict(Counter)  # retrospective cues: original phrase set vs Ross additions
    sources = cue_sources()
    for nid, detail in conn.execute(
            "SELECT novel_id, detail FROM temporal_events WHERE event_type = 'explicit_marker'"):
        d = json.loads(detail)
        cats[nid].update(d["categories"])
        for p, c in zip(d["phrases"], d["categories"]):
            if c == "retrospective":
                retro_split[nid]["ross" if sources.get(p) == "ross" else "original"] += 1

    scenes = defaultdict(list)
    for nid, subtype, detail in conn.execute(
            "SELECT novel_id, subtype, detail FROM temporal_events WHERE event_type = 'scene_boundary'"):
        scenes[nid].append((subtype, json.loads(detail)))

    # verb-construction totals from the word-level units: past-perfect and
    # future-in-past as a share of all verb constructions, which -- unlike a
    # share of sentences -- doesn't depend on how long the sentences are
    verbs = {r[0]: r[1:] for r in conn.execute(
        """SELECT novel_id, SUM(retrospection * verbs), SUM(prospection * verbs), SUM(verbs)
           FROM granularity_units WHERE level = 'word' AND verbs > 0 GROUP BY novel_id""")}

    survival = {}
    for row in conn.execute(
            f"""SELECT novel_id, {', '.join(f'AVG(visible_at_{lv})' for lv in LEVELS)}
                FROM granularity_comparison WHERE signal = 'retrospection' GROUP BY novel_id"""):
        survival[row[0]] = row[1:]

    out = []
    for nid, n in sorted(novels.items(), key=lambda kv: kv[1]["filename"]):
        sent = n.get("sentences", 0) or 1
        words = n["words"] or 1
        tot = sum(tense[nid].values()) or 1
        for t in TENSES:
            n[f"{t}_share"] = round(tense[nid][t] / tot, 4)
        n["mean_sentence_words"] = round(words / sent, 2)
        pp, fip, nverbs = verbs.get(nid, (0, 0, 0))
        n["retrospection_per_verb"] = round(pp / nverbs, 4) if nverbs else None
        n["prospection_per_verb"] = round(fip / nverbs, 4) if nverbs else None
        ev = events[nid]
        n["flashbacks_per_1k_sent"] = round(1000 * ev["flashback"] / sent, 2)
        n["flashbacks_hi_per_1k_sent"] = round(1000 * ev["flashback_hi"] / sent, 3)
        n["flashforwards_per_1k_sent"] = round(1000 * ev["flashforward"] / sent, 2)
        n["tense_shifts_per_1k_sent"] = round(1000 * ev["tense_shift"] / sent, 1)
        n["flashbacks_per_10k_words"] = round(10000 * ev["flashback"] / words, 3)
        n["flashbacks_hi_per_10k_words"] = round(10000 * ev["flashback_hi"] / words, 3)
        n["flashforwards_per_10k_words"] = round(10000 * ev["flashforward"] / words, 3)
        for c in CATEGORIES:
            n[f"{c}_per_10k"] = round(10000 * cats[nid][c] / words, 3)
        sc = scenes[nid]
        n["scenes"] = len(sc) + 1  # boundaries + the opening scene
        n["asterisk_breaks"] = sum(1 for s, _ in sc if s == "asterisk_break")
        n["median_scene_words"] = st.median(d["words"] for _, d in sc) if sc else words
        n["scenes_with_jumps_share"] = round(sum(1 for _, d in sc if d["jumps"]) / len(sc), 3) if sc else 0
        n["date_jumps"] = sum(d.get("date_jumps", 0) for _, d in sc)
        for label in DURATION_LABELS:
            n[f"{label}_scene_share"] = (round(sum(d["duration_label"] == label for _, d in sc) / len(sc), 3)
                                         if sc else None)
        n["retrospective_original_per_10k"] = round(10000 * retro_split[nid]["original"] / words, 3)
        n["retrospective_ross_per_10k"] = round(10000 * retro_split[nid]["ross"] / words, 3)
        for lv, v in zip(LEVELS, survival.get(nid, [None] * 4)):
            n[f"flashback_visible_{lv}"] = None if v is None else round(v, 3)
        out.append(n)
    return out


def cue_sources() -> dict:
    """phrase -> where it entered the vocabulary (phase1, weeks03-04, ross,
    audit), for the literal rows of cue_taxonomy.csv."""
    with open(TAXONOMY_PATH, encoding="utf-8") as f:
        return {r["pattern"].lower(): r["source"] for r in csv.DictReader(f)
                if r["status"] == "active" and r["match"].startswith("phrase")}


def threshold_recheck(conn) -> dict:
    """Re-run the flashback detector at 1, 2, and 3 required signals over
    every analyzed novel, to check the Weeks 5-6 choice at corpus scale."""
    totals, n_sent = Counter(), 0
    for (nid,) in conn.execute("SELECT DISTINCT novel_id FROM temporal_events"):
        rows = conn.execute(
            """SELECT s.text, sf.dominant_tense, sf.marker_phrases FROM sentences s
               JOIN sentence_features sf ON sf.sentence_id = s.id
               WHERE s.novel_id = ? ORDER BY s.sentence_index""", (nid,)).fetchall()
        sents = [{"text": r[0]} for r in rows]
        feats = [{"dominant_tense": r[1], "marker_phrases": json.loads(r[2])} for r in rows]
        n_sent += len(rows)
        for k in (1, 2, 3):
            flashback_detector.MIN_SIGNALS = k
            totals[k] += len(flashback_detector.detect(sents, feats))
    flashback_detector.MIN_SIGNALS = 2
    return {str(k): {"detections": v, "share_of_sentences": round(v / n_sent, 4)}
            for k, v in sorted(totals.items())} | {"sentences": n_sent}


def phrase_counts(conn, top: int = 12) -> dict:
    """The most frequent matched text in each category (pattern-matched cues
    vary: "two years later", "a twelvemonth after", ...)."""
    by_cat = defaultdict(Counter)
    for (detail,) in conn.execute(
            "SELECT detail FROM temporal_events WHERE event_type = 'explicit_marker'"):
        d = json.loads(detail)
        for p, cat in zip(d["phrases"], d["categories"]):
            by_cat[cat][p] += 1
    return {cat: dict(c.most_common(top)) for cat, c in sorted(by_cat.items())}


def scene_labels(conn) -> dict:
    """Scene duration labels across the corpus, and how much story time the
    scenes' cues state."""
    labels, stated, multi = Counter(), [], 0
    for detail, modifier in conn.execute(
            "SELECT detail, duration_modifier FROM temporal_events WHERE event_type = 'scene_boundary'"):
        d = json.loads(detail)
        labels[d["duration_label"]] += 1
        if d.get("stated_elapsed_days"):
            stated.append(d["stated_elapsed_days"])
        multi += modifier == "multi-unit"
    total = sum(labels.values())
    return {"scenes": total, "labels": {lb: labels[lb] for lb in DURATION_LABELS},
            "shares": {lb: round(labels[lb] / total, 4) for lb in DURATION_LABELS},
            "multi_unit_scenes": multi,
            "scenes_with_stated_elapsed_time": len(stated),
            "median_stated_elapsed_days": st.median(stated) if stated else None}


def partial_rank_corr(x, y, z):
    """Spearman-style partial correlation of x and y, controlling for z:
    rank all three, regress z's ranks out of x's and y's, correlate the
    residuals."""
    rx, ry, rz = rankdata(x), rankdata(y), rankdata(z)
    resid = lambda a: a - np.polyval(np.polyfit(rz, a, 1), rz)  # noqa: E731
    r, p = pearsonr(resid(rx), resid(ry))
    return float(r), float(p)


def trends(rows: list[dict], metrics=KEY_METRICS, extra=()) -> dict:
    """extra: metrics reported alongside but not counted in the family's
    Bonferroni correction (robustness checks)."""
    tested = [m for m in metrics if m != "mean_sentence_words"]
    bonferroni = ALPHA / len(tested)
    out = {"_bonferroni_threshold": round(bonferroni, 5)}
    for m in [*metrics, *extra]:
        use = [r for r in rows if r["year"] and r[m] is not None]
        years = [r["year"] for r in use]
        vals = [r[m] for r in use]
        rho, p = spearmanr(years, vals)
        entry = {"spearman_rho": round(float(rho), 3), "p": round(float(p), 5)}
        if m != "mean_sentence_words":
            pr, pp = partial_rank_corr(years, vals, [r["mean_sentence_words"] for r in use])
            entry |= {"partial_rho_controlling_sentence_length": round(pr, 3),
                      "partial_p": round(pp, 5),
                      "survives_bonferroni_after_control": bool(pp < bonferroni)}
        by_decade = defaultdict(list)
        for r in use:
            by_decade[r["decade"]].append(r[m])
        entry["decade_medians"] = {d: round(st.median(v), 4) for d, v in sorted(by_decade.items())}
        out[m] = entry
    return out


def gender(rows: list[dict], metrics=KEY_METRICS) -> dict:
    bonferroni = ALPHA / len(metrics)
    out = {"_bonferroni_threshold": round(bonferroni, 5)}
    for m in metrics:
        f = [r[m] for r in rows if r["gender"] == "F" and r[m] is not None]
        mm = [r[m] for r in rows if r["gender"] == "M" and r[m] is not None]
        u, p = mannwhitneyu(f, mm, alternative="two-sided")
        out[m] = {"female_median": round(st.median(f), 4), "male_median": round(st.median(mm), 4),
                  "n_female": len(f), "n_male": len(mm), "U": float(u), "p": round(float(p), 5),
                  "survives_bonferroni": bool(p < bonferroni)}
    return out


def granularity_summary(conn) -> dict:
    out = {}
    for sig in ("retrospection", "prospection", "marker_density", "tense_churn"):
        row = conn.execute(
            f"""SELECT COUNT(*), {', '.join(f'AVG(visible_at_{lv}), SUM(visible_at_{lv} IS NOT NULL)'
                                           for lv in LEVELS)}
                FROM granularity_comparison WHERE signal = ?""", (sig,)).fetchone()
        out[sig] = {"events": row[0]} | {
            lv: {"visible_share": None if row[1 + 2 * i] is None else round(row[1 + 2 * i], 4),
                 "measurable_events": row[2 + 2 * i]} for i, lv in enumerate(LEVELS)}
    # same flashbacks, high-confidence only
    row = conn.execute(
        f"""SELECT COUNT(*), {', '.join(f'AVG(gc.visible_at_{lv})' for lv in LEVELS)}
            FROM granularity_comparison gc JOIN temporal_events te ON te.id = gc.event_id
            WHERE gc.signal = 'retrospection' AND te.confidence >= 0.8""").fetchone()
    out["retrospection_high_confidence"] = {"events": row[0]} | {
        lv: None if v is None else round(v, 4) for lv, v in zip(LEVELS, row[1:])}
    # a coarse level only "washes out" if the finest level saw the event first
    row = conn.execute(
        """SELECT SUM(visible_at_word = 1),
                  SUM(visible_at_word = 1 AND visible_at_passage = 0),
                  SUM(visible_at_word = 1 AND visible_at_scene = 0),
                  SUM(visible_at_word = 1 AND visible_at_passage = 0 AND visible_at_scene = 0)
           FROM granularity_comparison WHERE signal = 'retrospection'""").fetchone()
    out["retrospection_washout"] = {"visible_at_word": row[0], "lost_by_passage": row[1],
                                    "lost_by_scene": row[2], "lost_by_both": row[3]}
    # unit sizes, for reading the levels against each other
    sizes = defaultdict(list)
    for level, words in conn.execute("SELECT level, words FROM granularity_units"):
        sizes[level].append(words)
    out["median_unit_words"] = {lv: st.median(v) for lv, v in sizes.items()}
    return out


def main():
    conn = sqlite3.connect(config.DB_PATH)
    rows = novel_rows(conn)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    events = dict(conn.execute("SELECT event_type, COUNT(*) FROM temporal_events GROUP BY 1"))
    multi_unit = conn.execute(
        "SELECT COUNT(*) FROM temporal_events WHERE duration_modifier = 'multi-unit'").fetchone()[0]
    cats = Counter()
    for (d,) in conn.execute("SELECT detail FROM temporal_events WHERE event_type='explicit_marker'"):
        cats.update(json.loads(d)["categories"])

    summary = {
        "novels": len(rows),
        "sentences": sum(r["sentences"] for r in rows),
        "words": sum(r["words"] for r in rows),
        "events": events,
        "marker_categories": dict(cats.most_common()),
        "marker_tiers": dict(sum((Counter({CATEGORY_TIER[c]: n}) for c, n in cats.items()), Counter())),
        "multi_unit_events": multi_unit,
        "scene_durations": scene_labels(conn),
        "phrase_counts": phrase_counts(conn),
        "threshold_recheck": threshold_recheck(conn),
        "granularity": granularity_summary(conn),
        "trends": trends(rows, extra=["retrospective_original_per_10k", "retrospective_ross_per_10k"]),
        "taxonomy_trends": trends(rows, TAXONOMY_METRICS),
        "gender": gender(rows),
        "taxonomy_gender": gender(rows, TAXONOMY_METRICS),
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    conn.close()

    print(f"novels {summary['novels']}, sentences {summary['sentences']:,}, words {summary['words']:,}")
    print("events:", summary["events"])
    print("marker categories:", summary["marker_categories"])
    print("marker tiers:", summary["marker_tiers"], "| multi-unit events:", multi_unit)
    print("scene durations:", summary["scene_durations"])
    print("threshold recheck:", summary["threshold_recheck"])
    print("granularity:", json.dumps(summary["granularity"], indent=1))
    for key in ("trends", "taxonomy_trends"):
        t = summary[key]
        print(f"\n{key} (Spearman vs. year; partial = controlling mean sentence length; "
              f"Bonferroni threshold {t['_bonferroni_threshold']}):")
        for m, v in t.items():
            if m.startswith("_"):
                continue
            extra = ("" if "partial_rho_controlling_sentence_length" not in v else
                     f" | partial {v['partial_rho_controlling_sentence_length']:+.3f} "
                     f"p={v['partial_p']:.5f}{'  *' if v['survives_bonferroni_after_control'] else ''}")
            print(f"  {m:32s} rho={v['spearman_rho']:+.3f} p={v['p']:.5f}{extra}")
    for key in ("gender", "taxonomy_gender"):
        g = summary[key]
        print(f"\n{key} (Mann-Whitney U; Bonferroni threshold {g['_bonferroni_threshold']}):")
        for m, v in g.items():
            if m.startswith("_"):
                continue
            print(f"  {m:32s} F={v['female_median']:<9} M={v['male_median']:<9} p={v['p']:.5f}"
                  f"{'  *' if v['survives_bonferroni'] else ''}")
    print(f"\nwrote {OUT_CSV} and {OUT_JSON}")


if __name__ == "__main__":
    main()
