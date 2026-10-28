"""
Phase 2 initial visualizations (SOW Phase 2 deliverable: "initial
visualizations for those 5 novels"), plus corpus-level figures for the
Weeks 7-8 report.

Per test novel:
    <stem>_granularity.png   retrospection at word / passage / scene / page
                             level, high-confidence flashbacks overlaid --
                             the "washed out at coarser levels" question, drawn
    <stem>_timeline.png      scenes, flashback/flash-forward density, and
                             temporal markers across the novel
    interactive/<stem>.html  both, interactive (hover, zoom, pan)

Corpus (after analyze_temporal_corpus.py has run):
    corpus_granularity_survival.png   share of events still visible per level
    corpus_decade_trends.png          retrospection across the century, length-robust
    corpus_decade_markers.png         explicit temporal markers across the century
    corpus_confound.png               why per-sentence measures mislead (sentence length)
    corpus_gender.png                 length-robust signals by author gender
    corpus_scene_durations.png        scene labels: presumed continuous vs. evidenced (Weeks 9-10)

These are Phase 2's first-look figures, not Phase 3's dashboard. Palette and
mark rules follow the project's data-viz reference: categorical slots in
fixed order (blue, orange, aqua, yellow), thin marks, hairline grid, every
category also named by a label so color is never the only cue.

Usage: python -m src.plot_phase2
"""
import json
import sqlite3

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
from plotly.subplots import make_subplots  # noqa: E402

from . import config  # noqa: E402
from .analyze_temporal import TEST_SLICE  # noqa: E402

OUT = config.ROOT / "reports" / "figures" / "phase2"
STATS_CSV = config.ROOT / "reports" / "data" / "temporal_novel_stats.csv"

# reference palette (light mode), validated: adjacent CVD dE >= 9.1
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
SURFACE, INK, INK2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, AXIS, NEUTRAL = "#e1e0d9", "#c3c2b7", "#d8d7d0"

LEVEL_LABELS = {"word": "word (25-word bins)", "passage": "passage (10 sentences)",
                "scene": "scene", "page": "page (original edition)"}

MARKER_GROUPS = [  # (label, categories, color) -- bottom to top on the timeline
    # Weeks 9-10: grouped by the cue taxonomy's tiers. Positional cues (time
    # of day, meals, seasons) and sequence words are too dense to read as
    # ticks and are left off the timeline.
    ("forward movement", {"forward_jump", "duration", "biographical", "travel"}, BLUE),
    ("retrospective / recollection", {"retrospective", "recollection"}, ORANGE),
    ("date / clock / year / holiday", {"calendar_date", "clock_time", "year", "holiday"}, AQUA),
    ("iterative (habitual)", {"frequency"}, YELLOW),
]

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "axes.titlecolor": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False,
    "font.family": ["Segoe UI", "DejaVu Sans", "sans-serif"], "font.size": 9,
    "axes.titlesize": 10, "axes.titleweight": "bold", "legend.frameon": False,
})


# --- data ----------------------------------------------------------------------

def _novel(conn, filename):
    nid, title, year, author = conn.execute(
        "SELECT id, title, year, author FROM novels WHERE filename = ?", (filename,)).fetchone()
    units = pd.read_sql_query(
        "SELECT level, start_word, end_word, retrospection_z, prospection, retrospection "
        "FROM granularity_units WHERE novel_id = ? ORDER BY level, start_word", conn, params=(nid,))
    events = pd.read_sql_query(
        """SELECT te.event_type, te.subtype, te.confidence, te.detail, gc.word_position
           FROM temporal_events te JOIN granularity_comparison gc ON gc.event_id = te.id
           WHERE te.novel_id = ?""", conn, params=(nid,))
    total = int(units.loc[units.level == "word", "end_word"].max())
    units["x"] = 100 * units.start_word / total
    units["x_end"] = 100 * units.end_word / total
    events["x"] = 100 * events.word_position / total
    return {"id": nid, "title": title, "year": year, "author": author,
            "units": units, "events": events, "total": total, "stem": filename[:-4]}


def _rolling(series, window):
    s = pd.Series(series, dtype=float)
    return s.rolling(window, min_periods=max(2, window // 3), center=True).mean().to_numpy()


def _density(events, kind, total, bins=100):
    """Events of one kind per 1,000 words, in `bins` equal slices of the novel."""
    edges = np.linspace(0, 100, bins + 1)
    counts, _ = np.histogram(events.loc[events.event_type == kind, "x"], bins=edges)
    words_per_bin = total / bins
    return (edges[:-1] + edges[1:]) / 2, 1000 * counts / words_per_bin


def _marker_rows(events):
    out = []
    m = events[events.event_type == "explicit_marker"]
    for _, row in m.iterrows():
        cats = set(json.loads(row["detail"])["categories"])
        for i, (label, group, color) in enumerate(MARKER_GROUPS):
            if cats & group:
                out.append((row["x"], i, label, color))
    return out


# --- per-novel static figures ---------------------------------------------------

def granularity_png(n):
    levels = [lv for lv in ("word", "passage", "scene", "page") if (n["units"].level == lv).any()]
    hi = n["events"][(n["events"].event_type == "flashback") & (n["events"].confidence >= 0.8)]
    fig, axes = plt.subplots(len(levels), 1, figsize=(10, 1.55 * len(levels) + 1.1),
                             sharex=True, constrained_layout=True)
    for ax, lv in zip(np.atleast_1d(axes), levels):
        u = n["units"][n["units"].level == lv]
        z = u.retrospection_z.to_numpy(dtype=float)
        if len(u) > 150:
            # dense levels (word bins, passages, pages): individual units
            # faint, a rolling mean over ~500 words bold
            window = max(3, round(500 / max(1, u.end_word.sub(u.start_word).median())))
            ax.step(u.x, z, where="post", color=BLUE, lw=0.4, alpha=0.3)
            ax.plot(u.x, _rolling(z, window), color=BLUE, lw=2)
        else:
            ax.step(u.x, z, where="post", color=BLUE, lw=2)
        for x in hi.x:
            ax.axvline(x, color=ORANGE, lw=0.9, alpha=0.8)
        ax.axhline(1.0, color=MUTED, lw=0.8)
        ax.text(100.5, 1.0, "z = 1\nvisible", color=MUTED, fontsize=7, va="center")
        ax.set_ylabel(LEVEL_LABELS[lv], rotation=0, ha="right", va="center", fontsize=8)
        lo, top = np.nanpercentile(z, 1), np.nanpercentile(z, 99.5)
        ax.set_ylim(min(-1.5, lo), max(3, top))
    ax.set_xlim(0, 100)
    ax.set_xlabel("position in novel (% of words)")
    fig.suptitle(f"{n['title']} ({n['year']}) - retrospection, in standard deviations, at "
                 f"{len(levels)} granularities", x=0.01, ha="left", fontsize=11, fontweight="bold")
    fig.text(0.01, -0.03, f"Orange lines: the {len(hi)} high-confidence flashbacks (>= 0.8). "
             "Retrospection = past-perfect share of verb constructions, z-scored within each level.\n"
             "Faint line: individual units. Bold line: rolling mean over ~500 words (scenes are "
             "drawn as units). A unit at or above z = 1 stands out; below it, an event is washed out.",
             fontsize=8, color=INK2, ha="left")
    fig.savefig(OUT / f"{n['stem']}_granularity.png", dpi=140, bbox_inches="tight")
    plt.close(fig)


def timeline_png(n):
    ev = n["events"]
    fig, (a_sc, a_fb, a_mk) = plt.subplots(
        3, 1, figsize=(10, 4.6), sharex=True, constrained_layout=True,
        gridspec_kw={"height_ratios": [0.6, 1.6, 1.4]})

    # scenes: alternating neutral bands, asterisk-break openings in blue
    sc = n["units"][n["units"].level == "scene"].reset_index(drop=True)
    for i, r in sc.iterrows():
        a_sc.barh(0, r.x_end - r.x, left=r.x, height=0.8,
                  color=NEUTRAL if i % 2 else "#ecebe6", edgecolor=SURFACE, linewidth=1)
    for x in ev[(ev.event_type == "scene_boundary") & (ev.subtype == "asterisk_break")].x:
        a_sc.plot([x, x], [-0.4, 0.4], color=BLUE, lw=2)
    a_sc.set_yticks([0], [f"{len(sc)} scenes"])
    a_sc.grid(False)

    # flashback / flash-forward density
    for kind, color, label in [("flashback", BLUE, "flashbacks"),
                               ("flashforward", ORANGE, "flash-forwards")]:
        x, d = _density(ev, kind, n["total"])
        a_fb.plot(x, d, color=color, lw=2, label=f"{label} per 1,000 words")
    hi = ev[(ev.event_type == "flashback") & (ev.confidence >= 0.8)]
    a_fb.plot(hi.x, np.zeros(len(hi)), linestyle="none", marker="^", ms=8,
              color=BLUE, markeredgecolor=SURFACE, markeredgewidth=1.5,
              label="high-confidence flashback")
    a_fb.set_ylabel("per 1,000\nwords", rotation=0, ha="right", va="center", fontsize=8)
    a_fb.legend(loc="upper left", fontsize=8, ncol=3)

    # temporal markers: one row per group, labeled, so color is never the only cue
    rows = _marker_rows(ev)
    for i, (label, _, color) in enumerate(MARKER_GROUPS):
        xs = [x for x, row, _, _ in rows if row == i]
        a_mk.plot(xs, np.full(len(xs), i), linestyle="none", marker="o", ms=5, color=color,
                  markeredgecolor=SURFACE, markeredgewidth=1)
    a_mk.set_yticks(range(len(MARKER_GROUPS)),
                    [f"{lab} ({sum(1 for r in rows if r[1] == i)})"
                     for i, (lab, _, _) in enumerate(MARKER_GROUPS)])
    a_mk.set_ylim(-0.6, len(MARKER_GROUPS) - 0.4)
    a_mk.set_xlim(0, 100)
    a_mk.set_xlabel("position in novel (% of words)")
    fig.suptitle(f"{n['title']} ({n['year']}) - temporal event timeline",
                 x=0.01, ha="left", fontsize=11, fontweight="bold")
    fig.savefig(OUT / f"{n['stem']}_timeline.png", dpi=140, bbox_inches="tight")
    plt.close(fig)


# --- per-novel interactive figure ----------------------------------------------

def interactive_html(n):
    levels = [lv for lv in ("word", "passage", "scene", "page") if (n["units"].level == lv).any()]
    rows = len(levels) + 2
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.025,
                        subplot_titles=[f"retrospection z - {LEVEL_LABELS[lv]}" for lv in levels]
                        + ["flashback / flash-forward density (per 1,000 words)", "temporal markers"])
    ev = n["events"]
    hi = ev[(ev.event_type == "flashback") & (ev.confidence >= 0.8)]
    for r, lv in enumerate(levels, 1):
        u = n["units"][n["units"].level == lv]
        y = _rolling(u.retrospection_z, 20) if lv == "word" else u.retrospection_z
        fig.add_trace(go.Scatter(
            x=u.x, y=y, mode="lines", line=dict(color=BLUE, width=2, shape="hv" if lv != "word" else None),
            name=lv, showlegend=False,
            hovertemplate=f"{lv}<br>position %{{x:.1f}}%<br>z %{{y:.2f}}<extra></extra>"), row=r, col=1)
        fig.add_hline(y=1, line=dict(color=MUTED, width=1), row=r, col=1)
        for x in hi.x:
            fig.add_vline(x=x, line=dict(color=ORANGE, width=1), opacity=0.7, row=r, col=1)
    for kind, color, label in [("flashback", BLUE, "flashbacks"), ("flashforward", ORANGE, "flash-forwards")]:
        x, d = _density(ev, kind, n["total"])
        fig.add_trace(go.Scatter(x=x, y=d, mode="lines", line=dict(color=color, width=2), name=label,
                                 hovertemplate=f"{label}<br>%{{x:.1f}}%: %{{y:.2f}} per 1k words<extra></extra>"),
                      row=rows - 1, col=1)
    mk = _marker_rows(ev)
    for i, (label, _, color) in enumerate(MARKER_GROUPS):
        xs = [x for x, row, _, _ in mk if row == i]
        fig.add_trace(go.Scatter(x=xs, y=[label] * len(xs), mode="markers", name=label,
                                 marker=dict(color=color, size=8, line=dict(color=SURFACE, width=2)),
                                 hovertemplate=f"{label} at %{{x:.1f}}%<extra></extra>"), row=rows, col=1)
    fig.update_layout(title=f"{n['title']} ({n['year']}) - Phase 2 temporal analysis",
                      height=170 * rows + 120, template="simple_white",
                      paper_bgcolor=SURFACE, plot_bgcolor=SURFACE, hovermode="x unified",
                      legend=dict(orientation="h", y=-0.04),
                      font=dict(family="Segoe UI, system-ui, sans-serif", color=INK2))
    fig.update_xaxes(showgrid=True, gridcolor=GRID, range=[0, 100])
    fig.update_yaxes(showgrid=True, gridcolor=GRID)
    fig.update_xaxes(title_text="position in novel (% of words)", row=rows, col=1)
    (OUT / "interactive").mkdir(exist_ok=True)
    fig.write_html(OUT / "interactive" / f"{n['stem']}.html", include_plotlyjs="cdn")


# --- corpus figures --------------------------------------------------------------

def corpus_survival_png(conn):
    sigs = [("retrospection", "flashbacks", BLUE), ("prospection", "flash-forwards", ORANGE),
            ("marker_density", "temporal markers", AQUA), ("tense_churn", "tense shifts", YELLOW)]
    levels = ["word", "passage", "scene"]
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(10, 3.8), constrained_layout=True,
                                  gridspec_kw={"width_ratios": [1.6, 1]})
    ends = []
    for sig, label, color in sigs:
        vals = [100 * conn.execute(f"SELECT AVG(visible_at_{lv}) FROM granularity_comparison "
                                   "WHERE signal = ?", (sig,)).fetchone()[0] for lv in levels]
        ax.plot(range(3), vals, color=color, lw=2, marker="o", ms=8,
                markeredgecolor=SURFACE, markeredgewidth=2, label=label)
        ends.append([vals[-1], f"{label} {vals[-1]:.0f}%"])
    # end labels, nudged apart so close values don't collide
    ends.sort()
    for i in range(1, len(ends)):
        ends[i][0] = max(ends[i][0], ends[i - 1][0] + 5)
    for y, text in ends:
        ax.text(2.1, y, text, color=INK2, fontsize=8, va="center")
    ax.set_xticks(range(3), ["word\n(25 words)", "passage\n(10 sentences)", "scene\n(median ~2,800 words)"])
    ax.set_xlim(-0.2, 2.9)
    ax.set_ylim(0, 100)
    ax.set_ylabel("events still visible (%)")
    ax.set_title("All 91 novels: how much survives aggregation", loc="left")
    ax.legend(loc="upper right", fontsize=8)

    # the paginated novels, where all four levels can be compared on the same events
    lv4 = ["word", "passage", "page", "scene"]
    row = conn.execute(
        f"""SELECT {', '.join(f'AVG(visible_at_{lv})' for lv in lv4)}, COUNT(*)
            FROM granularity_comparison WHERE signal = 'retrospection'
              AND visible_at_page IS NOT NULL""").fetchone()
    ax2.bar(range(4), [100 * v for v in row[:4]], color=BLUE, width=0.6, edgecolor=SURFACE, linewidth=2)
    for i, v in enumerate(row[:4]):
        ax2.text(i, 100 * v + 2, f"{100 * v:.0f}%", ha="center", fontsize=8, color=INK2)
    ax2.set_xticks(range(4), ["word", "passage", "page", "scene"])
    ax2.set_ylim(0, 100)
    ax2.set_title(f"Paginated novels: flashbacks (n = {row[4]:,})", loc="left")
    fig.savefig(OUT / "corpus_granularity_survival.png", dpi=140, bbox_inches="tight")
    plt.close(fig)


def _trend_panels(df, metrics, fname, title):
    fig, axes = plt.subplots(2, 2, figsize=(10, 6.2), constrained_layout=True)
    for ax, (col, label) in zip(axes.flat, metrics):
        ax.plot(df.year, df[col], linestyle="none", marker="o", ms=5, color=MUTED, alpha=0.7,
                markeredgecolor=SURFACE, markeredgewidth=1)
        dec = df.groupby("decade")[col].median()
        mids = [int(d[:4]) + 5 for d in dec.index]
        ax.plot(mids, dec.values, color=BLUE, lw=2, marker="o", ms=6,
                markeredgecolor=SURFACE, markeredgewidth=1.5, label="decade median")
        ax.set_title(label, loc="left", fontsize=9)
        ax.set_xlim(1797, 1903)
        top = df[col].quantile(0.98)
        if df[col].max() > 1.6 * top:  # a few extreme novels would flatten the rest
            ceiling = top * 1.35
            ax.set_ylim(bottom=min(0, df[col].min()), top=ceiling)
            above = df[df[col] > ceiling].sort_values(col, ascending=False)
            names = ", ".join(f"{t[:24]} ({v:.0f})" for t, v in zip(above.title, above[col]))
            ax.text(0.01, 0.97, f"above the axis: {names}", transform=ax.transAxes, ha="left",
                    va="top", fontsize=7, color=MUTED)
    axes.flat[1].legend(loc="upper right", fontsize=8)
    fig.suptitle(title, x=0.01, ha="left", fontsize=11, fontweight="bold")
    fig.text(0.01, -0.02, "Gray dots: one novel each (n = 91). Blue: decade median (robust to the "
             "few extreme novels).", fontsize=8, color=INK2)
    fig.savefig(OUT / fname, dpi=140, bbox_inches="tight")
    plt.close(fig)


def corpus_confound_png(df):
    """Why per-sentence measures can't carry a century trend: past-perfect
    share of *sentences* tracks sentence length, not retrospection."""
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 3.8), constrained_layout=True)
    a1.plot(df.mean_sentence_words, df.past_perfect_share, linestyle="none", marker="o", ms=6,
            color=BLUE, alpha=0.8, markeredgecolor=SURFACE, markeredgewidth=1)
    a1.set_xlabel("mean sentence length (words)")
    a1.set_title("Past-perfect share of sentences tracks sentence length", loc="left", fontsize=9)
    a2.plot(df.mean_sentence_words, df.retrospection_per_verb, linestyle="none", marker="o", ms=6,
            color=BLUE, alpha=0.8, markeredgecolor=SURFACE, markeredgewidth=1)
    a2.set_xlabel("mean sentence length (words)")
    a2.set_title("Past-perfect share of verbs mostly doesn't", loc="left", fontsize=9)
    # the 1819 semicolon-chained outlier (128 words/sentence) would squash
    # the other 90 novels into a third of the axis -- name it instead
    out = df.loc[df.mean_sentence_words.idxmax()]
    for ax in (a1, a2):
        ax.set_xlim(10, 60)
        ax.text(0.99, 0.03, f"off scale: {out.title} ({out.year}),\n"
                f"{out.mean_sentence_words:.0f} words/sentence", transform=ax.transAxes,
                ha="right", va="bottom", fontsize=7, color=MUTED)
    fig.suptitle("The sentence-length confound (one dot per novel, n = 91)", x=0.01, ha="left",
                 fontsize=11, fontweight="bold")
    fig.savefig(OUT / "corpus_confound.png", dpi=140, bbox_inches="tight")
    plt.close(fig)


def corpus_gender_png(df):
    metrics = [("retrospection_per_verb", "past-perfect share of verbs"),
               ("flashbacks_hi_per_10k_words", "cue-marked flashbacks per 10k words"),
               ("frequency_per_10k", "iterative (habitual) cues per 10k words *"),
               ("seasonal_per_10k", "seasonal cues per 10k words *")]
    fig, axes = plt.subplots(1, 4, figsize=(10, 3.2), constrained_layout=True)
    rng = np.random.default_rng(7)
    for ax, (col, label) in zip(axes, metrics):
        for i, (g, name, color) in enumerate([("F", "women", ORANGE), ("M", "men", BLUE)]):
            v = df.loc[df.gender == g, col].dropna()
            ax.plot(i + rng.uniform(-0.15, 0.15, len(v)), v, linestyle="none", marker="o", ms=5,
                    color=color, alpha=0.75, markeredgecolor=SURFACE, markeredgewidth=1)
            ax.plot([i - 0.25, i + 0.25], [v.median()] * 2, color=INK, lw=2)
        ax.set_xticks([0, 1], ["women\nauthors", "men\nauthors"])
        ax.set_xlim(-0.6, 1.6)
        ax.set_title(label, loc="left", fontsize=8)
    fig.suptitle("By author gender (black bar = median)", x=0.01, ha="left",
                 fontsize=11, fontweight="bold")
    n_f, n_m = (df.gender == "F").sum(), (df.gender == "M").sum()
    fig.text(0.01, -0.07, f"{n_f} women, {n_m} men among the {len(df)} analyzed novels. * survives "
             "correction for multiple comparisons (Mann-Whitney U, Bonferroni); women's novels lead\n"
             "on iterative cues in all 10 decades and on seasonal cues in 9 of 10. The tense and "
             "flashback measures show no difference.", fontsize=8, color=INK2)
    fig.savefig(OUT / "corpus_gender.png", dpi=140, bbox_inches="tight")
    plt.close(fig)


def corpus_scene_durations_png(conn):
    """What a scene with no stated jump is: the Weeks 7-8 rule called every
    one "continuous"; the evidence-based labels say what the text shows."""
    old = 3060 / 3819  # Weeks 7-8 run: scenes labelled "continuous" for lacking a jump
    labels = {}
    for (detail,) in conn.execute("SELECT detail FROM temporal_events WHERE event_type = 'scene_boundary'"):
        lb = json.loads(detail)["duration_label"]
        labels[lb] = labels.get(lb, 0) + 1
    total = sum(labels.values())
    segs = [("jump", BLUE), ("iterative", YELLOW), ("continuous", AQUA), ("anchored", ORANGE),
            ("unmarked", NEUTRAL)]
    fig, ax = plt.subplots(figsize=(10, 2.6), constrained_layout=True)
    rows = [("Weeks 7-8 rule", [("jump", 1 - old, BLUE), ("continuous (by default)", old, NEUTRAL)]),
            ("evidence-based\n(Weeks 9-10)", [(lb, labels.get(lb, 0) / total, c) for lb, c in segs])]
    for y, (_, parts) in zip((1, 0), rows):
        left = 0
        for name, share, color in parts:
            ax.barh(y, share - 0.004, left=left, height=0.55, color=color,
                    hatch="//" if "default" in name else None, edgecolor=SURFACE, linewidth=0)
            if share > 0.05:
                ink = INK if color in (YELLOW, NEUTRAL, AQUA) else SURFACE
                ax.text(left + share / 2, y, f"{name}\n{share:.0%}", ha="center", va="center",
                        fontsize=8, color=ink)
            left += share
    ax.set_yticks([1, 0], [r[0] for r in rows])
    ax.set_xlim(0, 1)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.grid(axis="y", visible=False)
    ax.set_title(f"Scene duration labels for all {total:,} scenes: presumed vs. evidenced", loc="left")
    fig.text(0.01, -0.08, "Iterative: habitual cues, story-time span unknown but likely more than one "
             "occasion. Continuous: sequence cues, no gap stated. Anchored: placed in time\n(hour, meal, "
             "season, holiday), no movement. Unmarked (gray): no temporal cue at all.",
             fontsize=8, color=INK2)
    fig.savefig(OUT / "corpus_scene_durations.png", dpi=140, bbox_inches="tight")
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    for fn in TEST_SLICE:
        n = _novel(conn, fn)
        granularity_png(n)
        timeline_png(n)
        interactive_html(n)
        print(f"  {fn}: granularity, timeline, interactive")

    if conn.execute("SELECT COUNT(DISTINCT novel_id) FROM temporal_events").fetchone()[0] > len(TEST_SLICE):
        corpus_survival_png(conn)
        df = pd.read_csv(STATS_CSV)
        _trend_panels(df, [("mean_sentence_words", "mean sentence length (words) - the confound"),
                           ("retrospection_per_verb", "past-perfect share of verbs - no significant trend"),
                           ("retrospective_original_per_10k",
                            '"years ago", "long ago", "ever since" per 10k words - rises'),
                           ("retrospective_ross_per_10k",
                            '"formerly", "previously", "prior to" per 10k words - falls')],
                      "corpus_decade_trends.png",
                      "Retrospection across the century: the grammar holds steady, its vocabulary changes register")
        _trend_panels(df, [("abruptness_per_10k", '"suddenly" / "all at once" per 10k words'),
                           ("clock_time_per_10k", "clock times per 10k words"),
                           ("calendar_date_per_10k", "calendar dates per 10k words"),
                           ("sequence_per_10k", '"presently", "later", "afterwards" per 10k words')],
                      "corpus_decade_markers.png", "Explicit temporal markers across the century")
        corpus_confound_png(df)
        corpus_gender_png(df)
        corpus_scene_durations_png(conn)
        print("  corpus: survival, decade trends, markers, confound, gender, scene durations")
    conn.close()
    print(f"wrote figures to {OUT}")


if __name__ == "__main__":
    main()
