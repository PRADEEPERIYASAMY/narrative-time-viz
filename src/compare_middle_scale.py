"""
The alternative path for the SOW's middle scale: the author's own
paragraphs instead of the fixed 10-sentence passage.

Weeks 7-8 chose the passage because paragraph breaks survive in only 64 of
the 91 novels. This asks what that choice cost, by running the alternative
on those 64 and comparing it with the present method on the same events:

    present      91 novels, 10-sentence passages (the reported results)
    present-64   the same method, restricted to the 64 paragraph novels
    alternative  the 64 novels, their real paragraphs
    strict-56    the alternative on the 56 novels whose blocks are
                 unmistakably paragraphs (median <= 200 words)

It reports unit sizes, visibility at each scale, event-by-event agreement
between paragraph and passage (Cohen's kappa, McNemar), the per-novel
picture, who the 27 excluded novels are (would restricting to 64 bias the
corpus?), whether the Weeks 9-10 findings hold on the 64, and whether
authors place flashbacks at the start of a paragraph.

Writes reports/data/middle_scale_comparison.json and
reports/data/middle_scale_by_novel.csv, and figures to
reports/figures/weeks-09-10/.

Usage: python -m src.compare_middle_scale
"""
import csv
import json
import sqlite3
import statistics as st
from bisect import bisect_right
from collections import Counter, defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy.stats import binomtest, chi2, mannwhitneyu, spearmanr  # noqa: E402

from . import config  # noqa: E402
from .analyze_temporal_corpus import gender, novel_rows, trends  # noqa: E402
from .temporal import granularity  # noqa: E402
from .viz.style import AQUA, AXIS, BLUE, GRID, INK, INK2, MUTED, NEUTRAL, ORANGE, SURFACE  # noqa: E402

OUT_JSON = config.ROOT / "reports" / "data" / "middle_scale_comparison.json"
OUT_CSV = config.ROOT / "reports" / "data" / "middle_scale_by_novel.csv"
FIG = config.ROOT / "reports" / "figures" / "weeks-09-10"
SIGNALS = ("retrospection", "prospection", "marker_density", "tense_churn")
EVENT_FOR_SIGNAL = {"retrospection": "flashbacks", "prospection": "flash-forwards",
                    "marker_density": "marker sentences", "tense_churn": "tense shifts"}
# the Weeks 9-10 findings re-checked on the 64
FINDING_METRICS = ["abruptness_per_10k", "retrospective_original_per_10k", "retrospective_ross_per_10k",
                   "sequence_per_10k", "recollection_per_10k", "clock_time_per_10k",
                   "retrospection_per_verb", "flashbacks_hi_per_10k_words"]


def paragraph_novels(conn) -> dict:
    """filename -> median block words, for every eligible novel."""
    return {fn: granularity.median_block_words(text) for fn, text in conn.execute(
        "SELECT filename, cleaned_text FROM novels WHERE analysis_eligible = 1")}


def _groups(medians: dict) -> dict:
    para = {f for f, m in medians.items() if 0 < m <= granularity.PARAGRAPH_MEDIAN_WORDS}
    strict = {f for f, m in medians.items() if 0 < m <= granularity.STRICT_PARAGRAPH_MEDIAN_WORDS}
    return {"all": set(medians), "para": para, "strict": strict, "excluded": set(medians) - para}


def unit_sizes(conn, files: set) -> dict:
    """Unit length per level, pooled and as each novel's coefficient of
    variation (how unequal one novel's units are)."""
    pooled, cv = defaultdict(list), defaultdict(list)
    for fn in files:
        for level in ("paragraph", "passage"):
            w = [r[0] for r in conn.execute(
                """SELECT gu.words FROM granularity_units gu JOIN novels n ON n.id = gu.novel_id
                   WHERE n.filename = ? AND gu.level = ?""", (fn, level))]
            if w:
                pooled[level] += w
                cv[level].append(st.pstdev(w) / st.mean(w))
    return {lv: {"units": len(v), "median_words": st.median(v),
                 "p10": float(np.percentile(v, 10)), "p90": float(np.percentile(v, 90)),
                 "share_under_25_words": round(sum(x < 25 for x in v) / len(v), 4),
                 "median_within_novel_cv": round(st.median(cv[lv]), 3)} for lv, v in pooled.items()}


def _comparison_rows(conn, files: set, signal: str, min_conf: float | None = None):
    q = """SELECT n.filename, gc.visible_at_word, gc.visible_at_paragraph, gc.visible_at_passage,
                  gc.visible_at_scene FROM granularity_comparison gc
           JOIN novels n ON n.id = gc.novel_id JOIN temporal_events te ON te.id = gc.event_id
           WHERE gc.signal = ?""" + (" AND te.confidence >= ?" if min_conf else "")
    params = (signal, min_conf) if min_conf else (signal,)
    return [r for r in conn.execute(q, params) if r[0] in files]


def visibility(conn, files: set, middle: str, signal: str) -> dict:
    """Share visible at word / middle / scene, over events measurable at
    all three (so every scale is judged on the same events)."""
    idx = {"paragraph": 2, "passage": 3}[middle]
    rows = [r for r in _comparison_rows(conn, files, signal)
            if r[1] is not None and r[idx] is not None and r[4] is not None]
    n = len(rows) or 1
    word_vis = [r for r in rows if r[1] == 1]
    return {"events": len(rows), "word": round(sum(r[1] for r in rows) / n, 4),
            middle: round(sum(r[idx] for r in rows) / n, 4), "scene": round(sum(r[4] for r in rows) / n, 4),
            "lost_from_word": round(sum(r[idx] == 0 for r in word_vis) / (len(word_vis) or 1), 4)}


def agreement(conn, files: set, signal: str, min_conf=None) -> dict:
    """Event by event: is the verdict at paragraph scale the same as at
    passage scale?"""
    rows = [r for r in _comparison_rows(conn, files, signal, min_conf) if r[2] is not None and r[3] is not None]
    both = sum(r[2] == 1 and r[3] == 1 for r in rows)
    para_only = sum(r[2] == 1 and r[3] == 0 for r in rows)
    pass_only = sum(r[2] == 0 and r[3] == 1 for r in rows)
    neither = len(rows) - both - para_only - pass_only
    n = len(rows)
    po = (both + neither) / n
    p_par, p_pas = (both + para_only) / n, (both + pass_only) / n
    pe = p_par * p_pas + (1 - p_par) * (1 - p_pas)
    kappa = (po - pe) / (1 - pe) if pe < 1 else 1.0
    b, c = para_only, pass_only
    mcnemar_p = float(chi2.sf((abs(b - c) - 1) ** 2 / (b + c), 1)) if b + c else 1.0
    return {"events": n, "both_visible": both, "paragraph_only": para_only, "passage_only": pass_only,
            "neither": neither, "agreement": round(po, 4), "cohen_kappa": round(kappa, 3),
            "paragraph_visible": round(p_par, 4), "passage_visible": round(p_pas, 4),
            "mcnemar_p": mcnemar_p}


def per_novel(conn, groups: dict, medians: dict) -> list[dict]:
    meta = {r[0]: r[1:] for r in conn.execute(
        "SELECT filename, title, author, year, author_gender, source FROM novels WHERE analysis_eligible = 1")}
    out = []
    for fn in sorted(groups["all"]):
        rows = _comparison_rows(conn, {fn}, "retrospection")
        par = [r[2] for r in rows if r[2] is not None]
        pas = [r[3] for r in rows if r[3] is not None]
        t, a, y, g, src = meta[fn]
        out.append({"filename": fn, "title": t, "author": a, "year": y, "gender": g,
                    "source": src, "median_block_words": medians[fn],
                    "paragraph_novel": fn in groups["para"], "strict_paragraph_novel": fn in groups["strict"],
                    "flashbacks": len(rows),
                    "flashback_visible_paragraph": round(st.mean(par), 4) if par else None,
                    "flashback_visible_passage": round(st.mean(pas), 4) if pas else None})
    return out


def who_is_excluded(rows: list[dict], groups: dict) -> dict:
    """Would restricting to the 64 bias the corpus?"""
    def describe(files):
        r = [x for x in rows if x["filename"] in files]
        return {"novels": len(r), "median_year": st.median(x["year"] for x in r),
                "women": sum(x["gender"] == "F" for x in r),
                "project_gutenberg": sum("gutenberg" in (x["source"] or "").lower() for x in r),
                "by_half_century": dict(Counter("1800-1849" if x["year"] < 1850 else "1850-1899" for x in r))}
    inc = [x["year"] for x in rows if x["filename"] in groups["para"]]
    exc = [x["year"] for x in rows if x["filename"] in groups["excluded"]]
    return {"included_64": describe(groups["para"]), "excluded_27": describe(groups["excluded"]),
            "year_difference_mannwhitney_p": round(float(mannwhitneyu(inc, exc).pvalue), 5)}


def findings_on_subset(conn, files: set) -> dict:
    """The Weeks 9-10 trend and gender findings, re-run on a subset."""
    rows = [r for r in novel_rows(conn) if r["filename"] in files]
    t = trends(rows, FINDING_METRICS + ["mean_sentence_words"])
    g = gender(rows, ["frequency_per_10k", "seasonal_per_10k"])
    return {"novels": len(rows),
            "trends": {m: {k: v[k] for k in ("spearman_rho", "partial_rho_controlling_sentence_length", "partial_p")
                           if k in v} for m, v in t.items() if not m.startswith("_")},
            "gender": {m: {k: v[k] for k in ("female_median", "male_median", "p")} for m, v in g.items()
                       if not m.startswith("_")}}


def paragraph_initial(conn, files: set) -> dict:
    """Do flashbacks open paragraphs more often than sentences in general?
    A raw comparison is unfair: one-line dialogue paragraphs make "opens a
    paragraph" common for sentences at large, and flashbacks sit in
    narration. So the test that counts is length-matched -- within
    multi-sentence paragraphs of the same length (2, 3, 4, 5, 6+ sentences),
    is a flashback the first sentence more or less often than chance?"""
    counts = Counter()
    by_len = defaultdict(Counter)  # paragraph length -> sentence / flashback counts
    for fn in sorted(files):
        nid, text = conn.execute("SELECT id, cleaned_text FROM novels WHERE filename = ?", (fn,)).fetchone()
        block_starts = [off for off, _ in granularity.paragraph_blocks(text)]
        sents = conn.execute("SELECT id, start_char FROM sentences WHERE novel_id = ? ORDER BY sentence_index",
                             (nid,)).fetchall()
        initial, prev = set(), -1
        para_of = {}
        for sid, start in sents:
            i = bisect_right(block_starts, start) - 1
            if i >= 0 and block_starts[i] > prev:
                initial.add(sid)
            para_of[sid] = i
            prev = start
        size = Counter(para_of.values())
        flashbacks = {r[0]: r[1] for r in conn.execute(
            "SELECT sentence_id, confidence FROM temporal_events WHERE novel_id = ? AND event_type = 'flashback'",
            (nid,))}
        for sid, _ in sents:
            k = min(size[para_of[sid]], 6)
            if k < 2:
                continue
            by_len[k]["sentences"] += 1
            by_len[k]["initial"] += sid in initial
            if sid in flashbacks:
                for tag in ("flashback", "flashback_hi") if flashbacks[sid] >= 0.8 else ("flashback",):
                    by_len[k][tag] += 1
                    by_len[k][tag + "_initial"] += sid in initial
        counts["sentences"] += len(sents)
        counts["sentences_initial"] += len(initial)
        for etype, conf, sid in conn.execute(
                """SELECT event_type, confidence, sentence_id FROM temporal_events
                   WHERE novel_id = ? AND event_type IN ('flashback', 'flashforward')""", (nid,)):
            key = etype + ("_hi" if conf >= 0.8 else "")
            for k in {etype, key}:
                counts[k] += 1
                counts[k + "_initial"] += sid in initial
    base = counts["sentences_initial"] / counts["sentences"]
    out = {"paragraph_initial_share_of_all_sentences": round(base, 4)}
    for k in ("flashback", "flashback_hi", "flashforward", "flashforward_hi"):
        n, x = counts[k], counts[k + "_initial"]
        out[k] = {"events": n, "paragraph_initial": x, "share": round(x / n, 4) if n else None,
                  "ratio_to_baseline": round(x / n / base, 2) if n else None,
                  "binomial_p": float(binomtest(x, n, base).pvalue) if n else None}
    matched = {"by_paragraph_sentences": {
        ("6+" if k == 6 else str(k)): {"chance": round(c["initial"] / c["sentences"], 4),
                                        "flashbacks": c["flashback"],
                                        "flashback_share": round(c["flashback_initial"] / c["flashback"], 4)}
        for k, c in sorted(by_len.items())}}
    for tag in ("flashback", "flashback_hi"):
        obs = sum(c[tag + "_initial"] for c in by_len.values())
        exp = sum(c[tag] * c["initial"] / c["sentences"] for c in by_len.values())
        var = sum(c[tag] * (c["initial"] / c["sentences"]) * (1 - c["initial"] / c["sentences"])
                  for c in by_len.values())
        matched[tag] = {"observed": obs, "expected": round(exp, 1), "ratio": round(obs / exp, 3),
                        "z": round((obs - exp) / var ** 0.5, 2)}
    out["length_matched"] = matched
    return out


# --- figures ----------------------------------------------------------------

def _style():
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "axes.titlecolor": INK,
        "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
        "axes.spines.top": False, "axes.spines.right": False,
        "font.family": ["Segoe UI", "DejaVu Sans", "sans-serif"], "font.size": 9,
        "axes.titlesize": 10, "axes.titleweight": "bold", "legend.frameon": False,
    })


def fig_unit_sizes(conn, files):
    fig, ax = plt.subplots(figsize=(10, 3.4), constrained_layout=True)
    bins = np.logspace(0, 4, 60)
    for level, color, name in (("passage", BLUE, "10-sentence passage"), ("paragraph", ORANGE, "author's paragraph")):
        w = [r[0] for r in conn.execute(
            f"""SELECT gu.words FROM granularity_units gu JOIN novels n ON n.id = gu.novel_id
                WHERE gu.level = ? AND n.filename IN ({','.join('?' * len(files))})""", (level, *files))]
        ax.hist(w, bins=bins, color=color, alpha=0.55, label=f"{name} (median {st.median(w):.0f} words)",
                edgecolor=SURFACE, linewidth=0.5)
    ax.set_xscale("log")
    ax.set_xlabel("unit length (words, log scale)")
    ax.set_ylabel("units")
    ax.legend(loc="upper right")
    ax.set_title("The two middle scales in the 64 paragraph novels: the author's paragraph is five times "
                 "smaller and far more uneven", loc="left")
    fig.savefig(FIG / "unit_sizes.png", dpi=140, bbox_inches="tight")
    plt.close(fig)


def fig_visibility(vis: dict):
    fig, ax = plt.subplots(figsize=(10, 3.6), constrained_layout=True)
    configs = [("present (91, passage)", "present", "passage", NEUTRAL),
               ("present on the 64 (passage)", "present_64", "passage", BLUE),
               ("alternative: the 64, paragraphs", "alternative", "paragraph", ORANGE),
               ("strict 56, paragraphs", "strict_56", "paragraph", AQUA)]
    x = np.arange(3)
    w = 0.2
    for i, (name, key, middle, color) in enumerate(configs):
        v = vis[key]["retrospection"]
        vals = [100 * v["word"], 100 * v[middle], 100 * v["scene"]]
        bars = ax.bar(x + (i - 1.5) * w, vals, w - 0.02, color=color, label=name, edgecolor=SURFACE)
        for b, val in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, val + 1, f"{val:.0f}", ha="center", fontsize=7, color=INK2)
    ax.set_xticks(x, ["word (25-word bin)", "middle scale\n(passage or paragraph)", "scene"])
    ax.set_ylabel("flashbacks still visible (%)")
    ax.set_ylim(0, 105)
    ax.legend(loc="upper right", fontsize=8)
    ax.set_title("Flashback visibility by scale under each middle-scale choice", loc="left")
    fig.savefig(FIG / "visibility_by_scale.png", dpi=140, bbox_inches="tight")
    plt.close(fig)


def fig_per_novel(rows: list[dict]):
    r = [x for x in rows if x["paragraph_novel"] and x["flashback_visible_paragraph"] is not None]
    fig, ax = plt.subplots(figsize=(6.4, 5.2), constrained_layout=True)
    for x in r:
        color = ORANGE if x["strict_paragraph_novel"] else MUTED
        ax.plot(100 * x["flashback_visible_passage"], 100 * x["flashback_visible_paragraph"], "o", ms=6,
                color=color, alpha=0.85, markeredgecolor=SURFACE)
    ax.plot([0, 100], [0, 100], color=AXIS, lw=1, zorder=0)
    rho = spearmanr([x["flashback_visible_passage"] for x in r], [x["flashback_visible_paragraph"] for x in r])[0]
    ax.set_xlabel("flashbacks visible at passage scale (%)")
    ax.set_ylabel("flashbacks visible at paragraph scale (%)")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.set_title(f"One dot per novel (n = {len(r)}); Spearman rho = {rho:.2f}", loc="left")
    gap = sorted(r, key=lambda x: x["flashback_visible_paragraph"] - x["flashback_visible_passage"])
    labelled = [x for x in gap if x["flashbacks"] >= 30]  # a handful of flashbacks is noise
    for x in labelled[:3] + labelled[-3:]:
        ax.annotate(x["title"][:22], (100 * x["flashback_visible_passage"], 100 * x["flashback_visible_paragraph"]),
                    xytext=(4, 2), textcoords="offset points", fontsize=7, color=INK2)
    ax.text(0.02, 0.97, "orange: strict-56 (unmistakable paragraphs)\ngray: the other 8 of the 64",
            transform=ax.transAxes, va="top", fontsize=7, color=MUTED)
    fig.savefig(FIG / "per_novel_paragraph_vs_passage.png", dpi=140, bbox_inches="tight")
    plt.close(fig)


def fig_initial(pi: dict):
    m = pi["length_matched"]
    rows = m["by_paragraph_sentences"]
    fig, ax = plt.subplots(figsize=(9, 3.2), constrained_layout=True)
    x = np.arange(len(rows))
    chance = [100 * r["chance"] for r in rows.values()]
    fb = [100 * r["flashback_share"] for r in rows.values()]
    ax.bar(x - 0.18, chance, 0.34, color=NEUTRAL, edgecolor=SURFACE, label="any sentence (chance)")
    ax.bar(x + 0.18, fb, 0.34, color=ORANGE, edgecolor=SURFACE, label="a flashback sentence")
    for i, (c, f) in enumerate(zip(chance, fb)):
        ax.text(i - 0.18, c + 0.8, f"{c:.0f}", ha="center", fontsize=7, color=INK2)
        ax.text(i + 0.18, f + 0.8, f"{f:.0f}", ha="center", fontsize=7, color=INK2)
    ax.set_xticks(x, [f"{k} sentences" for k in rows])
    ax.set_ylabel("opens the paragraph (%)")
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper right", fontsize=8)
    f = m["flashback"]
    ax.set_title(f"Flashbacks open paragraphs a little less than chance: {f['observed']:,} observed, "
                 f"{f['expected']:,.0f} expected (56 strict paragraph novels)", loc="left")
    fig.savefig(FIG / "paragraph_initial.png", dpi=140, bbox_inches="tight")
    plt.close(fig)


def main():
    conn = sqlite3.connect(config.DB_PATH)
    medians = paragraph_novels(conn)
    groups = _groups(medians)
    sets = {"present": groups["all"], "present_64": groups["para"],
            "alternative": groups["para"], "strict_56": groups["strict"]}
    middle = {"present": "passage", "present_64": "passage", "alternative": "paragraph", "strict_56": "paragraph"}
    vis = {k: {sig: visibility(conn, files, middle[k], sig) for sig in SIGNALS} for k, files in sets.items()}
    rows = per_novel(conn, groups, medians)
    para_rows = [r for r in rows if r["paragraph_novel"] and r["flashback_visible_paragraph"] is not None]
    rho, p = spearmanr([r["flashback_visible_passage"] for r in para_rows],
                       [r["flashback_visible_paragraph"] for r in para_rows])
    diff_vs_len = spearmanr([r["median_block_words"] for r in para_rows],
                            [r["flashback_visible_paragraph"] - r["flashback_visible_passage"] for r in para_rows])

    summary = {
        "groups": {k: len(v) for k, v in groups.items()},
        "the_8_long_block_novels": sorted(groups["para"] - groups["strict"]),
        "unit_sizes": unit_sizes(conn, groups["para"]),
        "visibility": vis,
        "agreement": {sig: agreement(conn, groups["para"], sig) for sig in SIGNALS}
        | {"retrospection_high_confidence": agreement(conn, groups["para"], "retrospection", 0.8),
           "retrospection_strict_56": agreement(conn, groups["strict"], "retrospection")},
        "per_novel_spearman": {"rho": round(float(rho), 3), "p": float(p), "novels": len(para_rows)},
        "difference_vs_median_paragraph_length": {"rho": round(float(diff_vs_len[0]), 3),
                                                  "p": float(diff_vs_len[1])},
        "who_is_excluded": who_is_excluded(rows, groups),
        "findings": {"present_91": findings_on_subset(conn, groups["all"]),
                     "subset_64": findings_on_subset(conn, groups["para"])},
        "paragraph_initial": paragraph_initial(conn, groups["strict"]),
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    FIG.mkdir(parents=True, exist_ok=True)
    _style()
    fig_unit_sizes(conn, groups["para"])
    fig_visibility(vis)
    fig_per_novel(rows)
    fig_initial(summary["paragraph_initial"])
    conn.close()
    print(json.dumps({k: v for k, v in summary.items() if k != "findings"}, indent=1))
    print(json.dumps(summary["findings"], indent=1))
    print(f"wrote {OUT_JSON}, {OUT_CSV}, figures in {FIG}")


if __name__ == "__main__":
    main()
