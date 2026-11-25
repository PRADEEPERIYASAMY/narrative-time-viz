"""
The SOW's Phase 3 flashback map: "overlay flashback/flash-forward
annotations on the timeline with clear visual distinction".

Three rows on the novel's length:

  density     flashbacks per 1,000 words above the axis (orange, looking
              back), flash-forwards below it (blue, looking ahead), at every
              confidence level -- the texture of retrospection
  events      the high-confidence ones as discrete marks: filled if the
              flashback still stands out at the chosen scale, hollow if it
              is washed out there. This puts the project's central finding
              (most flashbacks vanish at scene scale) on each novel's own
              map, and the scale is stated, because verdicts differ between
              scales (Weeks 9-10: paragraph and passage agree at kappa 0.37)
  scenes      scene boundaries for orientation, in neutral grey so the
              orange and blue keep one meaning
"""
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .style import AXIS, BLUE, FONT, GRID, INK, INK2, MUTED, NEUTRAL, ORANGE, SURFACE

BINS = 100
SCALES = ("word", "paragraph", "passage", "scene")
SCALE_TEXT = {"word": "25-word bin", "paragraph": "the author's paragraph",
              "passage": "10-sentence passage", "scene": "scene"}


def _density(events: list, total: int) -> tuple[list, list]:
    width = total / BINS
    counts = [0] * BINS
    for e in events:
        counts[min(BINS - 1, int(e["word"] / width))] += 1
    return [100 * (i + 0.5) / BINS for i in range(BINS)], [1000 * c / width for c in counts]


def build_flashback_map(data: dict, scale: str = "scene", min_confidence: float = 0.8) -> go.Figure:
    """data: viz.data.load_flashback_map(...). scale: the scale whose
    visibility verdict fills or hollows the marks."""
    total = data["total_words"]
    events = data["flash_events"]
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.06, row_heights=[0.55, 0.33, 0.12],
                        subplot_titles=("all flashbacks (up) and flash-forwards (down), per 1,000 words",
                                        f"high-confidence events, filled if still visible at {SCALE_TEXT[scale]} "
                                        "scale", ""))

    xb, back = _density([e for e in events if e["kind"] == "flashback"], total)
    _, ahead = _density([e for e in events if e["kind"] == "flashforward"], total)
    fig.add_trace(go.Scatter(x=xb, y=back, mode="lines", line=dict(color=ORANGE, width=1.5, shape="hvh"),
                             fill="tozeroy", fillcolor="rgba(235,104,52,0.25)", name="flashbacks",
                             hovertemplate="flashbacks: %{y:.1f} per 1,000 words at %{x:.0f}%<extra></extra>"),
                  row=1, col=1)
    fig.add_trace(go.Scatter(x=xb, y=[-v for v in ahead], mode="lines",
                             line=dict(color=BLUE, width=1.5, shape="hvh"), fill="tozeroy",
                             fillcolor="rgba(42,120,214,0.25)", name="flash-forwards", customdata=ahead,
                             hovertemplate="flash-forwards: %{customdata:.1f} per 1,000 words at %{x:.0f}%"
                                           "<extra></extra>"),
                  row=1, col=1)

    for kind, lane, color, symbol in (("flashback", "flashbacks", ORANGE, "triangle-left"),
                                      ("flashforward", "flash-forwards", BLUE, "triangle-right")):
        evs = [e for e in events if e["kind"] == kind and e["confidence"] >= min_confidence]
        for visible, suffix in ((1, ""), (0, "-open"), (None, "-open")):
            group = [e for e in evs if e["visible"][scale] == visible]
            if not group:
                continue
            state = {1: "visible", 0: "washed out", None: "not measurable"}[visible]
            fig.add_trace(go.Scatter(
                x=[100 * e["word"] / total for e in group], y=[lane] * len(group), mode="markers",
                marker=dict(symbol=symbol + suffix, size=11, color=color if visible is not None else MUTED,
                            line=dict(color=color if visible is not None else MUTED, width=1.5)),
                name=f"{lane}, {state} at {scale} scale", legendgroup=kind,
                customdata=[[e["cues"], e["confidence"], e["excerpt"],
                             *("yes" if e["visible"][lv] == 1 else "no" if e["visible"][lv] == 0 else "n/a"
                               for lv in SCALES)] for e in group],
                hovertemplate=(f"<b>{lane[:-1]}</b> ({state} at {scale} scale)<br>cue: %{{customdata[0]}}; "
                               "confidence %{customdata[1]:.1f}<br>visible at word %{customdata[3]}, paragraph "
                               "%{customdata[4]}, passage %{customdata[5]}, scene %{customdata[6]}<br>"
                               "<i>%{customdata[2]}</i><extra></extra>"),
            ), row=2, col=1)

    for k, s in enumerate(data["scenes"]):
        fig.add_trace(go.Bar(
            y=["scenes"], x=[100 * s["words"] / total], base=[100 * s["start_word"] / total], orientation="h",
            marker=dict(color=NEUTRAL if k % 2 else "#ecebe6", line=dict(color=SURFACE, width=1)),
            showlegend=False, customdata=[[s["index"] + 1, s["division"] or "-", s["label"]]],
            hovertemplate="scene %{customdata[0]} (%{customdata[2]})<br>%{customdata[1]}<extra></extra>",
        ), row=3, col=1)

    hi = [e for e in events if e["kind"] == "flashback" and e["confidence"] >= min_confidence]
    measured = [e for e in hi if e["visible"][scale] is not None]
    kept = sum(e["visible"][scale] == 1 for e in measured)
    note = (f"{kept} of {len(measured)} high-confidence flashbacks still stand out at {scale} scale"
            if measured else f"{scale} scale not measurable in this novel")
    fig.update_layout(
        title=dict(text=f"{data['title']} ({data['author']}, {data['year']}): flashback map",
                   x=0.01, xanchor="left", font=dict(size=15, color=INK)),
        height=580, barmode="overlay", bargap=0.2, paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family=FONT, size=12, color=INK2), margin=dict(l=110, r=20, t=70, b=140),
        legend=dict(orientation="h", y=-0.12, x=0, font=dict(size=11)),
        hoverlabel=dict(bgcolor="white", font=dict(family=FONT, size=12), align="left"),
    )
    fig.add_annotation(x=0, y=-0.36, xref="paper", yref="paper", xanchor="left", showarrow=False,
                       font=dict(size=10, color=MUTED),
                       text=(f"{note}. Density counts every detection (confidence 0.6-1.0); events show "
                             f"confidence {min_confidence} and up. Grey hollow marks: scale not measurable."))
    for ann in fig.layout.annotations[:2]:
        ann.update(x=0, xanchor="left", font=dict(size=12, color=INK))
    fig.update_xaxes(range=[0, 100], gridcolor=GRID, linecolor=AXIS, zeroline=False, tickfont=dict(color=MUTED),
                     ticksuffix="%")
    fig.update_xaxes(title_text="position in the novel (% of words)", row=3, col=1)
    # mirrored axis: flash-forwards are drawn below zero but counted as positive
    top = max(back + ahead + [1])
    step = next(v for v in (1, 2, 5, 10, 20, 50, 100) if top / v <= 4)
    ticks = [k * step for k in range(-int(max(ahead + [0]) // step) - 1, int(max(back) // step) + 2)]
    fig.update_yaxes(gridcolor=GRID, linecolor=AXIS, tickfont=dict(color=MUTED), zeroline=True,
                     zerolinecolor=AXIS, tickvals=ticks, ticktext=[str(abs(t)) for t in ticks], row=1, col=1)
    fig.update_yaxes(categoryorder="array", categoryarray=["flash-forwards", "flashbacks"], fixedrange=True,
                     gridcolor=GRID, tickfont=dict(color=INK2), row=2, col=1)
    fig.update_yaxes(showgrid=False, tickfont=dict(color=INK2), fixedrange=True, row=3, col=1)
    return fig


def summary(data: dict, scale: str = "scene", min_confidence: float = 0.8) -> dict:
    events = data["flash_events"]
    hi = [e for e in events if e["kind"] == "flashback" and e["confidence"] >= min_confidence]
    measured = [e for e in hi if e["visible"][scale] is not None]
    return {"flashbacks": sum(e["kind"] == "flashback" for e in events),
            "flashforwards": sum(e["kind"] == "flashforward" for e in events),
            "high_confidence_flashbacks": len(hi),
            "visible_at_scale": sum(e["visible"][scale] == 1 for e in measured),
            "measured_at_scale": len(measured)}
