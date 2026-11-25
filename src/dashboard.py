"""
Phase 3 interactive dashboard (SOW: "select a novel -> see visualizations
-> zoom/pan -> export").

    python -m src.dashboard            # then open http://127.0.0.1:8050
    python -m src.dashboard --port 8060

Three views, one tab each, for any of the 91 analyzed novels:

  timeline        scenes as told, coloured by duration label, the story
                  time their cues state, and labelled events (Weeks 9-10)
  pace & density  story time per 1,000 words, scene by scene, with the
                  density of time cues and of iterative narration (Weeks 11-12)
  flashback map   flashbacks and flash-forwards, density and events, each
                  event filled or hollow by whether it survives at a chosen
                  scale (Weeks 11-12)

Zoom and pan are Plotly's (drag to zoom, double-click to reset); the camera
icon saves an SVG, and the export buttons save the current view as SVG,
PDF, or PNG at publication size. A link can open a given novel and view
directly, for teaching: /?novel=1862.txt&view=flashbacks. (The SOW's
optional side-by-side comparative view was dropped at the Weeks 11-12
supervisor meeting.)

Reads corpus.db read-only, so it can run while the engine is writing.
"""
import argparse
from urllib.parse import parse_qs

from dash import Dash, Input, Output, State, ctx, dcc, html

from .viz import data, flashback_map, pace, timeline
from .viz.style import FONT, INK, INK2, MUTED, SURFACE

VIEWS = {"timeline": "Timeline", "pace": "Pace & density", "flashbacks": "Flashback map"}
EXPORT_SIZE = {"timeline": dict(width=1400, height=460), "pace": dict(width=1400, height=600),
               "flashbacks": dict(width=1400, height=600)}
LANE_OPTIONS = [("flashback", "flashbacks"), ("flashforward", "flash-forwards"),
                ("jump", "forward jumps"), ("absolute", "dates & years")]
SCALE_OPTIONS = [("word", "word"), ("paragraph", "paragraph"), ("passage", "passage"), ("scene", "scene")]
NOTES = {
    "timeline": "Story time stated is a lower bound: the scene's dated span plus jump cues with a stated "
                "quantity. Cues inside reported speech count too, so read it with the hover's breakdown.",
    "pace": "Pace is story time over discourse time. Above the dotted median the telling runs faster than "
            "usual for this novel (summary), below it slower (scene). Scenes that state no story time are "
            "left blank, not drawn as zero.",
    "flashbacks": "Filled marks still stand out at the chosen scale; hollow marks are washed out there. "
                  "Paragraph scale exists only in the 64 novels whose paragraphs survive.",
}

conn = data.connect()
NOVELS = data.list_novels(conn)


def _label(n: dict) -> str:
    return f"{n['title']} ({n['author']}, {n['year']})"


def _stat(value, caption):
    return html.Div([html.Div(value, style={"fontSize": "22px", "fontWeight": 600, "color": INK}),
                     html.Div(caption, style={"fontSize": "12px", "color": MUTED})],
                    style={"marginRight": "28px"})


def _control(label, component):
    return html.Div([html.Label(label), component])


app = Dash(__name__, title="Narrative time")
app.layout = html.Div(style={"fontFamily": FONT, "background": SURFACE, "padding": "18px 24px",
                             "color": INK2, "minHeight": "100vh"}, children=[
    dcc.Location(id="url"),
    html.H2("Narrative time in the nineteenth-century novel", style={"color": INK, "margin": "0 0 4px"}),
    html.Div("HUM19UK, 91 novels. Pick a novel and a view; drag to zoom, double-click to reset, hover for "
             "the sentences behind every mark.", style={"marginBottom": "14px"}),
    html.Div(style={"display": "flex", "gap": "18px", "flexWrap": "wrap", "alignItems": "end"}, children=[
        _control("Novel", dcc.Dropdown(id="novel", options=[{"label": _label(n), "value": n["filename"]}
                                                            for n in NOVELS],
                                       value="1847.txt", clearable=False, style={"width": "460px"})),
        _control("Flashback confidence", dcc.RadioItems(
            id="confidence", options=[{"label": " 0.8 and up", "value": 0.8},
                                      {"label": " 1.0 only (all three signals)", "value": 1.0}],
            value=0.8, inline=True, inputStyle={"marginLeft": "10px"})),
    ]),
    dcc.Tabs(id="view", value="timeline", style={"marginTop": "14px"},
             children=[dcc.Tab(label=t, value=v) for v, t in VIEWS.items()]),
    html.Div(style={"display": "flex", "gap": "18px", "flexWrap": "wrap", "margin": "12px 0 0"}, children=[
        html.Div(id="lanes-box", children=_control("Timeline events", dcc.Checklist(
            id="lanes", options=[{"label": f" {t}", "value": v} for v, t in LANE_OPTIONS],
            value=[v for v, _ in LANE_OPTIONS], inline=True, inputStyle={"marginLeft": "10px"}))),
        html.Div(id="scale-box", children=_control("Survives at which scale?", dcc.RadioItems(
            id="scale", options=[{"label": f" {t}", "value": v} for v, t in SCALE_OPTIONS],
            value="scene", inline=True, inputStyle={"marginLeft": "10px"}))),
    ]),
    html.Div(id="stats", style={"display": "flex", "margin": "14px 0 4px"}),
    dcc.Graph(id="figure", config={"displaylogo": False, "toImageButtonOptions": {"format": "svg"}}),
    html.Div(style={"display": "flex", "gap": "10px", "alignItems": "center"}, children=[
        html.Span("Export this view at publication size:"),
        *[html.Button(fmt.upper(), id=f"export-{fmt}", n_clicks=0) for fmt in ("svg", "pdf", "png")],
        dcc.Download(id="download"),
    ]),
    html.Div(id="note", style={"marginTop": "14px", "fontSize": "12px", "color": MUTED, "maxWidth": "980px"}),
])


@app.callback(Output("novel", "value"), Output("view", "value"), Input("url", "search"))
def from_url(search):
    """?novel=<file>&view=<timeline|pace|flashbacks> opens that novel and view."""
    q = parse_qs((search or "").lstrip("?"))
    novel = q.get("novel", ["1847.txt"])[0]
    view = q.get("view", ["timeline"])[0]
    known = {n["filename"] for n in NOVELS}
    return (novel if novel in known else "1847.txt"), (view if view in VIEWS else "timeline")


def _figure(view, filename, confidence, lanes, scale):
    if view == "pace":
        d = data.load_pace(conn, filename)
        s = pace.summary(d)
        stats = [_stat(f"{s['timed_scenes']} / {s['scenes']}", "scenes stating a story time"),
                 _stat(f"{s['median_pace']:.2g}" if s["median_pace"] else "-", "median story days per 1,000 words")]
        if s["fastest"]:
            stats.append(_stat(f"{s['fastest'][2]:.3g}", f"fastest: scene {s['fastest'][0]}"))
            stats.append(_stat(f"{s['slowest'][2]:.2g}", f"slowest: scene {s['slowest'][0]}"))
        return pace.build_pace(d), stats
    if view == "flashbacks":
        d = data.load_flashback_map(conn, filename)
        if scale == "paragraph" and not d["has_paragraphs"]:
            scale = "passage"
        s = flashback_map.summary(d, scale, confidence)
        stats = [_stat(s["flashbacks"], "flashbacks (all confidence)"),
                 _stat(s["flashforwards"], "flash-forwards"),
                 _stat(s["high_confidence_flashbacks"], f"flashbacks, conf. ≥ {confidence}"),
                 _stat(f"{s['visible_at_scale']} / {s['measured_at_scale']}", f"of those, visible at {scale} scale")]
        return flashback_map.build_flashback_map(d, scale, confidence), stats
    d = data.load_timeline(conn, filename, min_confidence=confidence)
    s = timeline.summary(d)
    mix = s["label_mix"]
    stats = [_stat(f"{s['words']:,}", "words"), _stat(s["scenes"], "scenes"),
             _stat(f"{mix['jump']}/{mix['iterative']}/{mix['continuous']}/{mix['anchored']}/{mix['unmarked']}",
                   "jump / iterative / continuous / anchored / unmarked"),
             _stat(s["flashbacks"], f"flashbacks (conf. ≥ {confidence})"),
             _stat(s["jumps"], "forward jumps"), _stat(s["absolute"], "dates, years, clock times")]
    return timeline.build_timeline(d, lanes=set(lanes)), stats


@app.callback(Output("figure", "figure"), Output("stats", "children"), Output("note", "children"),
              Output("lanes-box", "style"), Output("scale-box", "style"),
              Input("view", "value"), Input("novel", "value"), Input("confidence", "value"),
              Input("lanes", "value"), Input("scale", "value"))
def update(view, filename, confidence, lanes, scale):
    fig, stats = _figure(view, filename, confidence, lanes, scale)
    show = {"display": "block"}
    hide = {"display": "none"}
    return (fig, stats, NOTES[view] + " Heuristic detections, not ground truth.",
            show if view == "timeline" else hide, show if view == "flashbacks" else hide)


@app.callback(Output("download", "data"),
              Input("export-svg", "n_clicks"), Input("export-pdf", "n_clicks"), Input("export-png", "n_clicks"),
              State("view", "value"), State("novel", "value"), State("confidence", "value"),
              State("lanes", "value"), State("scale", "value"), prevent_initial_call=True)
def export(_svg, _pdf, _png, view, filename, confidence, lanes, scale):
    fmt = ctx.triggered_id.split("-")[1]
    fig, _ = _figure(view, filename, confidence, lanes, scale)
    body = fig.to_image(format=fmt, **EXPORT_SIZE[view], scale=2 if fmt == "png" else 1)
    return dcc.send_bytes(body, f"{filename.removesuffix('.txt')}_{view}.{fmt}")


def main():
    parser = argparse.ArgumentParser(description="Run the narrative-time dashboard")
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    app.run(port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
