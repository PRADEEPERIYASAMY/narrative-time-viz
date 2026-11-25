"""
Iterative and seasonal time by author gender: the Weeks 9-10 finding,
tested to the standard a journal referee would apply.

Weeks 9-10 found that novels by women carry more iterative cues ("used
to", "every day") and more seasonal cues ("the summer", "the winter") than
novels by men (Mann-Whitney, Bonferroni-corrected). This asks whether that
survives everything that could explain it away:

  effect size        rank-biserial r; Hodges-Lehmann shift with a bootstrap
                     95% interval
  design             a permutation test that shuffles gender only within
                     each decade (the corpus is balanced by decade)
  confounds          negative binomial count models with each novel's
                     length as exposure, adding in turn: year, mean sentence
                     length, first-person narration, dialogue share
  change over time   the gender x year interaction
  stability          leave-one-novel-out and leave-one-decade-out
  measurement        the hand-checked precision audit
                     (reports/data/gender_precision_audit.csv), applied per
                     gender, including its worst case
  where it lives     cue families, with false-discovery-rate correction;
                     narration vs. dialogue

Writes reports/data/gender_time.json and gender_time_by_novel.csv, and
figures to reports/figures/weeks-11-12/.

Usage: python -m src.analyze_gender_time [--db path]
"""
import argparse
import csv
import json
import re
import sqlite3
import statistics as st
from collections import Counter, defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import statsmodels.formula.api as smf  # noqa: E402
from scipy.stats import mannwhitneyu  # noqa: E402
from statsmodels.stats.multitest import multipletests  # noqa: E402
from statsmodels.stats.proportion import proportion_confint  # noqa: E402

from . import config  # noqa: E402
from .viz.style import AXIS, BLUE, GRID, INK, INK2, MUTED, ORANGE, SURFACE  # noqa: E402

OUT_JSON = config.ROOT / "reports" / "data" / "gender_time.json"
OUT_CSV = config.ROOT / "reports" / "data" / "gender_time_by_novel.csv"
AUDIT = config.ROOT / "reports" / "data" / "gender_precision_audit.csv"
FIG = config.ROOT / "reports" / "figures" / "weeks-11-12"
MEASURES = {"frequency": "iterative cues", "seasonal": "seasonal cues"}
RNG = np.random.default_rng(1847)

# quotation marks open dialogue; an apostrophe-led line is a quotation in
# the single-quote editions
_QUOTE = re.compile(r"[\"“”‘]|^\s*'")
_FIRST_PERSON = re.compile(r"\b(?:I|me|my|myself)\b")

FAMILIES = {
    "frequency": [("used to", r"^used to$"), ("usually", r"^usually$"),
                  ("every / each + unit", r"^(?:every|each) "),
                  ("X after X", r"^(\w+) after \1$"),
                  ("again and again, over and over, many a time", r"again|over and over|many (?:and many )?a time"),
                  ("constantly, repeatedly, habitually", r"^(?:constantly|repeatedly|habitually|customarily)$"),
                  ("was accustomed to, made a point of, custom", r"accustomed|made a point|custom"),
                  ("of an evening, on Sundays", r"^(?:of an?|on) ")],
    "seasonal": [("summer", r"summer"), ("winter", r"winter"), ("spring", r"spring"), ("autumn", r"autumn"),
                 ("harvest and other", r".")],
}


def _family(measure: str, phrase: str) -> str:
    for name, pattern in FAMILIES[measure]:
        if re.search(pattern, phrase):
            return name
    return FAMILIES[measure][-1][0]


def novel_table(conn) -> pd.DataFrame:
    rows = {}
    for nid, fn, title, author, g, year, decade in conn.execute(
            """SELECT id, filename, title, author, author_gender, year, decade FROM novels
               WHERE analysis_eligible = 1 AND id IN (SELECT DISTINCT novel_id FROM temporal_events)"""):
        rows[nid] = dict(filename=fn, title=title, author=author, gender=g, female=int(g == "F"), year=year,
                         decade=decade, words=0, sentences=0, narration_words=0, dialogue_words=0,
                         dialogue_sentences=0, first_person=0)
    quoted = {}
    for nid, sid, text, tokens in conn.execute("SELECT novel_id, id, text, token_count FROM sentences"):
        r = rows.get(nid)
        if r is None:
            continue
        q = bool(_QUOTE.search(text))
        quoted[sid] = q
        r["words"] += tokens or 0
        r["sentences"] += 1
        if q:
            r["dialogue_words"] += tokens or 0
            r["dialogue_sentences"] += 1
        else:
            r["narration_words"] += tokens or 0
            r["first_person"] += len(_FIRST_PERSON.findall(text))
    fam = defaultdict(Counter)
    for nid, sid, detail in conn.execute(
            "SELECT novel_id, sentence_id, detail FROM temporal_events WHERE event_type = 'explicit_marker'"):
        if nid not in rows:
            continue
        d = json.loads(detail)
        for phrase, cat in zip(d["phrases"], d["categories"]):
            if cat in MEASURES:
                rows[nid][cat] = rows[nid].get(cat, 0) + 1
                where = "dialogue" if quoted.get(sid) else "narration"
                rows[nid][f"{cat}_{where}"] = rows[nid].get(f"{cat}_{where}", 0) + 1
                fam[nid][(cat, _family(cat, phrase))] += 1
    labels = defaultdict(Counter)
    for nid, detail in conn.execute(
            "SELECT novel_id, detail FROM temporal_events WHERE event_type = 'scene_boundary'"):
        labels[nid][json.loads(detail)["duration_label"]] += 1

    out = []
    for nid, r in rows.items():
        for m in MEASURES:
            r.setdefault(m, 0)
            r[f"{m}_per_10k"] = 10000 * r[m] / r["words"]
            for where in ("narration", "dialogue"):
                n = r.get(f"{m}_{where}", 0)
                r[f"{m}_{where}"] = n
                r[f"{m}_{where}_per_10k"] = 10000 * n / r[f"{where}_words"] if r[f"{where}_words"] else None
            for name, _ in FAMILIES[m]:
                r[f"{m}: {name}"] = 10000 * fam[nid][(m, name)] / r["words"]
        r["mean_sentence_words"] = r["words"] / r["sentences"]
        r["first_person_per_1k"] = 1000 * r["first_person"] / r["narration_words"] if r["narration_words"] else 0
        r["dialogue_share"] = r["dialogue_sentences"] / r["sentences"]
        total = sum(labels[nid].values())
        r["iterative_scene_share"] = labels[nid]["iterative"] / total if total else None
        out.append(r)
    return pd.DataFrame(out).sort_values("filename").reset_index(drop=True)


def _mw(f, m) -> dict:
    u, p = mannwhitneyu(f, m, alternative="two-sided")
    return {"U": float(u), "p": float(p), "rank_biserial": round(float(2 * u / (len(f) * len(m)) - 1), 3)}


def hodges_lehmann(f, m) -> float:
    return float(np.median(np.subtract.outer(np.asarray(f), np.asarray(m))))


def effect(df: pd.DataFrame, col: str, boots: int = 5000) -> dict:
    f, m = df.loc[df.female == 1, col].to_numpy(), df.loc[df.female == 0, col].to_numpy()
    hl = [hodges_lehmann(RNG.choice(f, len(f)), RNG.choice(m, len(m))) for _ in range(boots)]
    return {"female_median": round(float(np.median(f)), 3), "male_median": round(float(np.median(m)), 3),
            "n_female": len(f), "n_male": len(m), **_mw(f, m),
            "hodges_lehmann_shift": round(hodges_lehmann(f, m), 3),
            "shift_95ci": [round(float(np.percentile(hl, 2.5)), 3), round(float(np.percentile(hl, 97.5)), 3)]}


def stratified_permutation(df: pd.DataFrame, col: str, perms: int = 10000) -> float:
    """Shuffle gender within each decade; statistic = mean rank of women's
    novels (equivalent to the Mann-Whitney U)."""
    ranks = df[col].rank().to_numpy()
    female = df.female.to_numpy()
    groups = [np.flatnonzero(df.decade.to_numpy() == d) for d in df.decade.unique()]
    observed = ranks[female == 1].mean()
    center = ranks.mean()
    extreme = 0
    for _ in range(perms):
        shuffled = female.copy()
        for idx in groups:
            shuffled[idx] = RNG.permutation(shuffled[idx])
        extreme += abs(ranks[shuffled == 1].mean() - center) >= abs(observed - center)
    return (extreme + 1) / (perms + 1)


MODELS = [
    ("gender only", "female"),
    ("+ year", "female + year_c"),
    ("+ sentence length", "female + year_c + msl_z"),
    ("+ first-person narration", "female + year_c + msl_z + fp_z"),
    ("+ dialogue share", "female + year_c + msl_z + fp_z + dlg_z"),
]


def count_models(df: pd.DataFrame, measure: str) -> dict:
    """Negative binomial regression of the cue count, with the novel's
    length as exposure: the female coefficient is an incidence-rate ratio
    (IRR), the rate in women's novels relative to men's, other things equal."""
    d = df.assign(year_c=(df.year - 1850) / 10, msl_z=(df.mean_sentence_words - df.mean_sentence_words.mean())
                  / df.mean_sentence_words.std(),
                  fp_z=(df.first_person_per_1k - df.first_person_per_1k.mean()) / df.first_person_per_1k.std(),
                  dlg_z=(df.dialogue_share - df.dialogue_share.mean()) / df.dialogue_share.std())
    out = {}
    for name, rhs in MODELS + [("+ gender x year", "female * year_c + msl_z + fp_z + dlg_z")]:
        fit = smf.negativebinomial(f"{measure} ~ {rhs}", d, offset=np.log(d.words)).fit(disp=0, maxiter=200)
        lo, hi = fit.conf_int().loc["female"]
        entry = {"irr": round(float(np.exp(fit.params["female"])), 3),
                 "ci": [round(float(np.exp(lo)), 3), round(float(np.exp(hi)), 3)],
                 "p": float(fit.pvalues["female"])}
        for term in ("year_c", "msl_z", "fp_z", "dlg_z", "female:year_c"):
            if term in fit.params:
                entry[term] = {"irr": round(float(np.exp(fit.params[term])), 3), "p": float(fit.pvalues[term])}
        out[name] = entry
    return out


def stability(df: pd.DataFrame, col: str) -> dict:
    f, m = df.female == 1, df.female == 0
    loo = [mannwhitneyu(df.loc[f & (df.index != i), col], df.loc[m & (df.index != i), col]).pvalue
           for i in df.index]
    lodo = {d: float(mannwhitneyu(df.loc[f & (df.decade != d), col], df.loc[m & (df.decade != d), col]).pvalue)
            for d in sorted(df.decade.unique())}
    by_decade = {d: [round(float(df.loc[f & (df.decade == d), col].median()), 2),
                     round(float(df.loc[m & (df.decade == d), col].median()), 2)]
                 for d in sorted(df.decade.unique())}
    return {"leave_one_novel_out_max_p": float(max(loo)), "leave_one_decade_out_p": lodo,
            "leave_one_decade_out_max_p": max(lodo.values()),
            "decades_women_lead": sum(a > b for a, b in by_decade.values()), "decade_medians_f_m": by_decade}


def precision(measure: str) -> dict:
    """The audit's precision per gender (unclear items left out), with
    Wilson intervals, and the medians it implies -- including the worst case
    for the finding (women at the low end of their interval, men at the high
    end of theirs)."""
    rows = [r for r in csv.DictReader(open(AUDIT, encoding="utf-8")) if r["category"] == measure]
    out = {}
    for g in ("F", "M"):
        judged = [r for r in rows if r["gender"] == g and r["judgment"] != "unclear"]
        ok = sum(r["judgment"] == "correct" for r in judged)
        lo, hi = proportion_confint(ok, len(judged), method="wilson")
        out[g] = {"correct": ok, "judged": len(judged), "precision": round(ok / len(judged), 3),
                  "ci": [round(lo, 3), round(hi, 3)]}
    return out


def families(df: pd.DataFrame, measure: str) -> list[dict]:
    rows = []
    for name, _ in FAMILIES[measure]:
        col = f"{measure}: {name}"
        f, m = df.loc[df.female == 1, col], df.loc[df.female == 0, col]
        rows.append({"family": name, "female_mean": round(float(f.mean()), 3), "male_mean": round(float(m.mean()), 3),
                     "p": float(mannwhitneyu(f, m).pvalue)})
    reject, q, _, _ = multipletests([r["p"] for r in rows], method="fdr_bh")
    for r, qq, rej in zip(rows, q, reject):
        r["q_fdr"], r["significant_fdr"] = float(qq), bool(rej)
    return rows


# --- figures ------------------------------------------------------------------

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


def fig_forest(res: dict):
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.4), constrained_layout=True, sharey=True)
    names = [n for n, _ in MODELS]
    for ax, (measure, label) in zip(axes, MEASURES.items()):
        models = res[measure]["models"]
        for i, n in enumerate(names):
            e = models[n]
            y = len(names) - 1 - i
            ax.plot(e["ci"], [y, y], color=INK2, lw=1.5)
            ax.plot(e["irr"], y, "o", ms=8, color=ORANGE, markeredgecolor=SURFACE, markeredgewidth=1.5)
            ax.text(e["ci"][1] + 0.02, y, f"{e['irr']:.2f}", va="center", fontsize=8, color=INK2)
        ax.axvline(1, color=AXIS, lw=1, zorder=0)
        ax.set_yticks(range(len(names)), names[::-1])
        ax.set_xlabel("rate in women's novels / rate in men's (IRR, 95% CI)")
        ax.set_title(label, loc="left")
    fig.suptitle("The gender difference under successive controls (negative binomial, novel length as exposure)",
                 x=0.01, ha="left", fontsize=11, fontweight="bold")
    fig.savefig(FIG / "gender_forest.png", dpi=140, bbox_inches="tight")
    plt.close(fig)


def fig_decades(res: dict):
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.2), constrained_layout=True)
    for ax, (measure, label) in zip(axes, MEASURES.items()):
        med = res[measure]["stability"]["decade_medians_f_m"]
        mids = [int(d[:4]) + 5 for d in med]
        ax.plot(mids, [v[0] for v in med.values()], "-o", color=ORANGE, lw=2, ms=6, label="women",
                markeredgecolor=SURFACE, markeredgewidth=1.5)
        ax.plot(mids, [v[1] for v in med.values()], "-o", color=BLUE, lw=2, ms=6, label="men",
                markeredgecolor=SURFACE, markeredgewidth=1.5)
        ax.set_ylim(bottom=0)
        ax.set_title(f"{label} per 10k words, decade medians (women lead in "
                     f"{res[measure]['stability']['decades_women_lead']} of 10)", loc="left")
        ax.legend(loc="lower right", fontsize=8)
    fig.savefig(FIG / "gender_decades.png", dpi=140, bbox_inches="tight")
    plt.close(fig)


def fig_families(res: dict):
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6), constrained_layout=True,
                             gridspec_kw={"width_ratios": [1.6, 1]})
    for ax, (measure, label) in zip(axes, MEASURES.items()):
        fam = res[measure]["families"]
        y = np.arange(len(fam))
        ax.barh(y + 0.18, [r["female_mean"] for r in fam], 0.34, color=ORANGE, label="women", edgecolor=SURFACE)
        ax.barh(y - 0.18, [r["male_mean"] for r in fam], 0.34, color=BLUE, label="men", edgecolor=SURFACE)
        ax.set_yticks(y, [r["family"] + (" *" if r["significant_fdr"] else "") for r in fam], fontsize=8)
        ax.invert_yaxis()
        ax.set_xlabel("per 10k words (mean across novels)")
        ax.grid(axis="y", visible=False)
        n_sig = sum(r["significant_fdr"] for r in fam)
        ax.set_title(f"{label}: women higher in {sum(r['female_mean'] > r['male_mean'] for r in fam)} of "
                     f"{len(fam)} families; {n_sig} individually significant", loc="left", fontsize=9)
    axes[0].legend(loc="lower right")
    fig.suptitle("Where the difference lives: cue families (* q < 0.05, Benjamini-Hochberg)",
                 x=0.01, ha="left", fontsize=11, fontweight="bold")
    fig.savefig(FIG / "gender_families.png", dpi=140, bbox_inches="tight")
    plt.close(fig)


def fig_narration(df: pd.DataFrame):
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.2), constrained_layout=True, sharey=True)
    for ax, where in zip(axes, ("narration", "dialogue")):
        col = f"frequency_{where}_per_10k"
        for i, (g, color, name) in enumerate([(1, ORANGE, "women"), (0, BLUE, "men")]):
            v = df.loc[df.female == g, col].dropna()
            ax.plot(i + RNG.uniform(-0.15, 0.15, len(v)), v, "o", ms=5, color=color, alpha=0.75,
                    markeredgecolor=SURFACE, markeredgewidth=1)
            ax.plot([i - 0.25, i + 0.25], [v.median()] * 2, color=INK, lw=2)
        ax.set_xticks([0, 1], ["women\nauthors", "men\nauthors"])
        ax.set_xlim(-0.6, 1.6)
        ax.set_title(f"iterative cues per 10k words of {where}", loc="left")
    fig.suptitle("Narrator or characters? Iterative cues outside and inside quotation (black bar = median)",
                 x=0.01, ha="left", fontsize=11, fontweight="bold")
    fig.savefig(FIG / "gender_narration_dialogue.png", dpi=140, bbox_inches="tight")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Iterative and seasonal time by author gender")
    parser.add_argument("--db", default=str(config.DB_PATH))
    args = parser.parse_args()
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    df = novel_table(conn)

    res = {"novels": len(df), "women": int(df.female.sum()), "men": int((df.female == 0).sum())}
    for measure in MEASURES:
        col = f"{measure}_per_10k"
        prec = precision(measure)
        f_med, m_med = df.loc[df.female == 1, col].median(), df.loc[df.female == 0, col].median()
        res[measure] = {
            "effect": effect(df, col),
            "stratified_permutation_p": stratified_permutation(df, col),
            "models": count_models(df, measure),
            "stability": stability(df, col),
            "precision": prec,
            "precision_adjusted_medians": {
                "female": round(f_med * prec["F"]["precision"], 3), "male": round(m_med * prec["M"]["precision"], 3),
                "worst_case_female": round(f_med * prec["F"]["ci"][0], 3),
                "worst_case_male": round(m_med * prec["M"]["ci"][1], 3)},
            "families": families(df, measure),
            "narration": effect(df.dropna(subset=[f"{measure}_narration_per_10k"]), f"{measure}_narration_per_10k"),
            "dialogue": effect(df.dropna(subset=[f"{measure}_dialogue_per_10k"]), f"{measure}_dialogue_per_10k"),
        }
    res["iterative_scene_share"] = effect(df.dropna(subset=["iterative_scene_share"]), "iterative_scene_share")
    res["covariates_by_gender"] = {c: effect(df, c, boots=500) for c in
                                   ("first_person_per_1k", "dialogue_share", "mean_sentence_words")}

    OUT_JSON.write_text(json.dumps(res, indent=2), encoding="utf-8")
    df.to_csv(OUT_CSV, index=False)
    FIG.mkdir(parents=True, exist_ok=True)
    _style()
    fig_forest(res)
    fig_decades(res)
    fig_families(res)
    fig_narration(df)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
