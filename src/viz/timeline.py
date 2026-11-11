"""
The SOW's Phase 3 timeline view: "horizontal bar chart showing narrative
progression -- scene boundaries, durations, labeled events (flashbacks,
temporal jumps)".

One horizontal axis, the novel's own length (% of its words). Lanes, top
to bottom:

  scenes              one bar per scene, as long as its telling; coloured
                      by its evidence-based duration label (Weeks 9-10)
  story time stated   the story time a scene's cues add up to ("+2 days"):
                      a lower bound, drawn at the scene's middle
  dates & years       calendar dates, clock times, years, holidays
  forward jumps       "the next morning", "two years later"
  flash-forwards      high-confidence prospective passages
  flashbacks          high-confidence retrospective passages

So the discourse length of a scene (its bar) and the story time it covers
(its label) sit one above the other: Genette's duration, read straight off
the figure. Hover gives each scene's chapter and counts, and each event's
sentence; zoom and pan are Plotly's own.
"""
import math

import plotly.graph_objects as go

from .data import page_at
from .style import AXIS, FONT, GRID, INK, INK2, LABEL_COLORS, LABEL_TEXT, MUTED, SURFACE

LANES = ["flashbacks", "flash-forwards", "forward jumps", "dates & years", "story time stated", "scenes"]
EVENT_LANES = {  # data lane -> (axis lane, marker symbol)
    "flashback": ("flashbacks", "triangle-left"),
    "flashforward": ("flash-forwards", "triangle-right"),
    "jump": ("forward jumps", "line-ns"),
    "absolute": ("dates & years", "diamond"),
}
LABEL_ORDER = ["jump", "iterative", "continuous", "anchored", "unmarked", "opening"]


def format_days(days) -> str:
    if days is None:
        return ""
    if days >= 365:
        return f"+{days / 365:.1f} yr".replace(".0 ", " ")
    if days >= 30:
        return f"+{days / 30:.0f} mo"
    if days >= 1:
        return f"+{days:.0f} d"
    return f"+{days * 24:.0f} h"


MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _story_breakdown(s: dict) -> str:
    parts = []
    if s.get("dated_range"):
        (m1, d1), (m2, d2) = s["dated_range"]
        parts.append(f"dated span {d1} {MONTH_ABBR[m1 - 1]} - {d2} {MONTH_ABBR[m2 - 1]} "
                     f"({s['dated_span_days']} d)")
    parts += [f'"{p}" {format_days(d)}' for p, d in s.get("cue_days", [])[:4]]
    if s.get("stated_elapsed_days") and s["stated_elapsed_days"] != s["story_days"]:
        parts.append(f"(running sum of date advances: {format_days(s['stated_elapsed_days'])})")
    return "<br>".join(parts)


def _pct(word: int, total: int) -> float:
    return 100 * word / total if total else 0.0


def build_timeline(data: dict, lanes: set | None = None, label_scenes: bool | None = None) -> go.Figure:
    """data: viz.data.load_timeline(...). lanes: which event lanes to draw
    (default: all). label_scenes: print story-time labels on the figure
    (default: only when there are few enough scenes to read them)."""
    total = data["total_words"]
    lanes = set(EVENT_LANES) if lanes is None else lanes
    scenes = data["scenes"]
    fig = go.Figure()

    # scenes: one trace per duration label, so the legend names each colour
    for label in LABEL_ORDER:
        group = [s for s in scenes if s["label"] == label]
        if not group:
            continue
        fig.add_trace(go.Bar(
            y=["scenes"] * len(group), orientation="h",
            base=[_pct(s["start_word"], total) for s in group],
            x=[_pct(s["words"], total) for s in group],
            marker=dict(color=LABEL_COLORS[label], line=dict(color=SURFACE, width=1.5)),
            name=LABEL_TEXT[label], legendgroup="scenes", legendgrouptitle_text="scene duration",
            customdata=[[s["index"] + 1, s["division"] or "-", f"{s['words']:,}", s["jumps"] or 0,
                         format_days(s["story_days"]) or "none stated",
                         page_at(data["pages"], s["start_word"]) or "-"] for s in group],
            hovertemplate=("<b>scene %{customdata[0]}</b> (" + label + ")<br>%{customdata[1]}<br>"
                           "%{customdata[2]} words; %{customdata[3]} forward jump(s)<br>"
                           "story time stated: %{customdata[4]}<br>original page: %{customdata[5]}"
                           "<extra></extra>"),
        ))

    # story time stated, at each scene's midpoint; marker area ~ log(days).
    # viz.data reads it as the scene's dated span plus its quantified jump
    # cues (see _add_story_time for why not the engine's running sum)
    stated = [s for s in scenes if s["story_days"]]
    if stated:
        show_text = len(scenes) <= 45 if label_scenes is None else label_scenes
        fig.add_trace(go.Scatter(
            y=["story time stated"] * len(stated),
            x=[_pct(s["start_word"] + s["words"] / 2, total) for s in stated],
            mode="markers+text" if show_text else "markers",
            # selective labels: every value when the scenes are few, only a
            # week or more when they crowd; hover always has the number
            text=[format_days(s["story_days"]) if len(scenes) <= 20 or s["story_days"] >= 7 else ""
                  for s in stated], textposition="top center",
            textfont=dict(size=10, color=INK2),
            marker=dict(size=[6 + 3 * math.log10(1 + s["story_days"]) for s in stated],
                        color=INK2, line=dict(color=SURFACE, width=1)),
            name="story time stated (lower bound)", showlegend=False,
            customdata=[[s["index"] + 1, format_days(s["story_days"]), _story_breakdown(s)] for s in stated],
            hovertemplate=("<b>scene %{customdata[0]}</b>: at least %{customdata[1]}<br>"
                           "%{customdata[2]}<extra></extra>"),
        ))

    # labelled events
    for kind, (lane, symbol) in EVENT_LANES.items():
        if kind not in lanes:
            continue
        evs = [e for e in data["events"] if e["lane"] == kind]
        if not evs:
            continue
        fig.add_trace(go.Scatter(
            y=[lane] * len(evs), x=[_pct(e["word"], total) for e in evs], mode="markers",
            marker=dict(symbol=symbol, size=9 if symbol != "line-ns" else 12, color=INK,
                        line=dict(color=INK if symbol == "line-ns" else SURFACE, width=1.5)),
            opacity=0.8, name=lane, showlegend=False,
            customdata=[[e["label"], e["excerpt"], e["confidence"],
                         page_at(data["pages"], e["word"]) or "-"] for e in evs],
            hovertemplate=(f"<b>{lane}</b>: %{{customdata[0]}}<br>confidence %{{customdata[2]:.1f}}; "
                           "original page %{customdata[3]}<br><i>%{customdata[1]}</i><extra></extra>"),
        ))

    title = f"{data['title']} ({data['author']}, {data['year']}): narrative timeline"
    fig.update_layout(
        title=dict(text=title, x=0.01, xanchor="left", font=dict(size=15, color=INK)),
        barmode="overlay", bargap=0.35, height=430,
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE, font=dict(family=FONT, size=12, color=INK2),
        margin=dict(l=130, r=20, t=60, b=50),
        legend=dict(orientation="h", y=-0.2, x=0, font=dict(size=11), groupclick="toggleitem"),
        hoverlabel=dict(bgcolor="white", font=dict(family=FONT, size=12), align="left"),
    )
    fig.update_xaxes(range=[0, 100], title_text="position in the novel (% of words)", ticksuffix="%",
                     gridcolor=GRID, linecolor=AXIS, zeroline=False, tickfont=dict(color=MUTED))
    fig.update_yaxes(categoryorder="array", categoryarray=LANES, gridcolor=GRID, linecolor=AXIS,
                     tickfont=dict(color=INK2), fixedrange=True)
    return fig


def summary(data: dict) -> dict:
    """Counts for the dashboard's side panel."""
    scenes = data["scenes"]
    labelled = [s for s in scenes if s["label"] != "opening"]
    mix = {lb: sum(s["label"] == lb for s in labelled) for lb in LABEL_ORDER[:-1]}
    stated = [s["story_days"] for s in scenes if s["story_days"]]
    return {
        "words": data["total_words"], "scenes": len(scenes), "label_mix": mix,
        "flashbacks": sum(e["lane"] == "flashback" for e in data["events"]),
        "flashforwards": sum(e["lane"] == "flashforward" for e in data["events"]),
        "jumps": sum(e["lane"] == "jump" for e in data["events"]),
        "absolute": sum(e["lane"] == "absolute" for e in data["events"]),
        "stated_days_total": round(sum(stated), 1) if stated else 0,
        "paginated": bool(data["pages"]),
    }
