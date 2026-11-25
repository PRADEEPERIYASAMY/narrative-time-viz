"""
The SOW's Phase 3 pace/density plot: "where does narrative time accelerate
or slow? (narrative seconds per page vs. story time per page)".

Pace is the ratio Genette calls speed: story time over discourse time. The
discourse side is measured in words (1,000 words is about three printed
pages, or four minutes of reading); the story side is the time a scene's
cues state (viz.data: its dated span plus quantified jumps). Three rows
share the novel's length as their axis:

  pace                  story days per 1,000 words, one step per scene,
                        log scale. Above the novel's median the telling
                        runs faster than usual (summary); below it, slower
                        (scene). Scenes that state no story time are left
                        blank rather than drawn as zero.
  time cues             temporal cues per 1,000 words, per 10-sentence
                        passage, smoothed: where the text marks time
  iterative narration   habitual cues per 1,000 words, smoothed: where the
                        telling compresses many occasions into one
                        (Genette's iterative, a different kind of speed)
"""
import math
import statistics

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .style import AXIS, BLUE, FONT, GRID, INK, INK2, LABEL_COLORS, LABEL_TEXT, MUTED, SURFACE, YELLOW
from .timeline import LABEL_ORDER, format_days

SMOOTH_PASSAGES = 9  # rolling window, about 1,800 words


def _rolling(values: list, window: int) -> list:
    out, half = [], window // 2
    for i in range(len(values)):
        chunk = [v for v in values[max(0, i - half):i + half + 1] if v is not None]
        out.append(sum(chunk) / len(chunk) if chunk else None)
    return out


def _days_text(days: float) -> str:
    if days >= 1:
        return f"{days:.2g} day" + ("" if round(days, 1) == 1 else "s")
    return f"{24 * days:.2g} hours"


LOG_TICKS = [(0.01, "15 min"), (0.1, "2.4 h"), (1, "1 day"), (10, "10 days"), (100, "100 days"),
             (1000, "3 years")]


def _pct(word: int, total: int) -> float:
    return 100 * word / total if total else 0.0


def build_pace(data: dict) -> go.Figure:
    """data: viz.data.load_pace(...)."""
    total = data["total_words"]
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.07, row_heights=[0.56, 0.22, 0.22],
                        subplot_titles=("pace: story days per 1,000 words (log scale)",
                                        "time cues per 1,000 words", "iterative (habitual) cues per 1,000 words"))

    timed = [s for s in data["scenes"] if s.get("pace")]
    median = statistics.median(s["pace"] for s in timed) if timed else None
    for label in LABEL_ORDER:
        group = [s for s in timed if s["label"] == label]
        if not group:
            continue
        xs, ys, custom = [], [], []
        for s in group:
            a, b = _pct(s["start_word"], total), _pct(s["end_word"], total)
            xs += [a, b, None]
            ys += [s["pace"], s["pace"], None]
            c = [s["index"] + 1, s["division"] or "-", f"{s['words']:,}", format_days(s["story_days"]),
                 round(s["pace"], 2)]
            custom += [c, c, c]
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines", line=dict(color=LABEL_COLORS[label], width=5),
            name=LABEL_TEXT[label], legendgroup=label, customdata=custom,
            hovertemplate=("<b>scene %{customdata[0]}</b> (" + label + ")<br>%{customdata[1]}<br>"
                           "%{customdata[3]} told in %{customdata[2]} words<br>"
                           "= %{customdata[4]} story days per 1,000 words<extra></extra>"),
        ), row=1, col=1)
    if median:
        fig.add_hline(y=median, line=dict(color=MUTED, width=1, dash="dot"), row=1, col=1)
        fig.add_annotation(x=100, y=math.log10(median), xref="x", yref="y", xanchor="right", yanchor="bottom",
                           text=(f"novel's median {_days_text(median)} per 1,000 words &nbsp; "
                                 "↑ faster (summary) &nbsp; ↓ slower (scene)"),
                           showarrow=False, font=dict(size=10, color=INK2), bgcolor="rgba(252,252,251,0.85)")

    passages = data["passages"]
    mids = [_pct((p["start_word"] + p["end_word"]) / 2, total) for p in passages]
    for row, key, color, name in ((2, "marker_density", BLUE, "time cues"),
                                  (3, "iterative_density", YELLOW, "iterative cues")):
        smooth = _rolling([p[key] for p in passages], SMOOTH_PASSAGES)
        fig.add_trace(go.Scatter(
            x=mids, y=smooth, mode="lines", line=dict(color=color, width=2), fill="tozeroy",
            fillcolor="rgba(42,120,214,0.12)" if color == BLUE else "rgba(237,161,0,0.15)",
            name=name, showlegend=False,
            hovertemplate=f"{name}: %{{y:.1f}} per 1,000 words<br>at %{{x:.0f}}% of the novel<extra></extra>",
        ), row=row, col=1)

    untimed = sum(1 for s in data["scenes"] if not s.get("pace"))
    fig.update_layout(
        title=dict(text=f"{data['title']} ({data['author']}, {data['year']}): pace and density",
                   x=0.01, xanchor="left", font=dict(size=15, color=INK)),
        height=560, paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family=FONT, size=12, color=INK2), margin=dict(l=80, r=20, t=70, b=110),
        legend=dict(orientation="h", y=-0.13, x=0, font=dict(size=11), title_text="scene duration "),
        hoverlabel=dict(bgcolor="white", font=dict(family=FONT, size=12), align="left"),
    )
    fig.add_annotation(x=0, y=-0.25, xref="paper", yref="paper", xanchor="left", showarrow=False,
                       font=dict(size=10, color=MUTED),
                       text=(f"{len(timed)} of {len(data['scenes'])} scenes state a story time; the other "
                             f"{untimed} are left blank. Story time is a lower bound (dated span + quantified "
                             "jumps). Rows 2-3: per 10-sentence passage, smoothed over about 1,800 words."))
    for ann in fig.layout.annotations[:3]:
        ann.update(x=0, xanchor="left", font=dict(size=12, color=INK))
    fig.update_xaxes(range=[0, 100], gridcolor=GRID, linecolor=AXIS, zeroline=False, tickfont=dict(color=MUTED),
                     ticksuffix="%")
    fig.update_xaxes(title_text="position in the novel (% of words)", row=3, col=1)
    fig.update_yaxes(type="log", gridcolor=GRID, linecolor=AXIS, tickfont=dict(color=MUTED),
                     tickvals=[v for v, _ in LOG_TICKS], ticktext=[t for _, t in LOG_TICKS], row=1, col=1)
    fig.update_yaxes(gridcolor=GRID, linecolor=AXIS, tickfont=dict(color=MUTED), rangemode="tozero", row=2, col=1)
    fig.update_yaxes(gridcolor=GRID, linecolor=AXIS, tickfont=dict(color=MUTED), rangemode="tozero", row=3, col=1)
    return fig


def summary(data: dict) -> dict:
    timed = [s for s in data["scenes"] if s.get("pace")]
    fastest = max(timed, key=lambda s: s["pace"]) if timed else None
    slowest = min(timed, key=lambda s: s["pace"]) if timed else None
    return {"timed_scenes": len(timed), "scenes": len(data["scenes"]),
            "median_pace": round(statistics.median(s["pace"] for s in timed), 3) if timed else None,
            "fastest": fastest and (fastest["index"] + 1, fastest["division"], round(fastest["pace"], 2)),
            "slowest": slowest and (slowest["index"] + 1, slowest["division"], round(slowest["pace"], 3))}
