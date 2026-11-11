"""
Phase 3 interactive dashboard (SOW: "select a novel -> see visualizations
-> zoom/pan -> export").

    python -m src.dashboard            # then open http://127.0.0.1:8050
    python -m src.dashboard --port 8060

Weeks 9-10 delivers the first of the SOW's three views, the timeline,
for any of the 91 analyzed novels: scene bars coloured by duration label,
the story time their cues state, and the labelled events. Zoom and pan are
Plotly's (drag to zoom, double-click to reset); the camera icon saves an
SVG, and the export buttons save SVG, PDF, or PNG at publication size. The
pace/density plot and the flashback map join it as further tabs in Weeks
11-12.

Reads corpus.db read-only, so it can run while the engine is writing.
"""
import argparse

from dash import Dash, Input, Output, State, dcc, html

from .viz import data, timeline
from .viz.style import FONT, INK, INK2, MUTED, SURFACE

EXPORT_SIZE = dict(width=1400, height=460, scale=2)
LANE_OPTIONS = [("flashback", "flashbacks"), ("flashforward", "flash-forwards"),
                ("jump", "forward jumps"), ("absolute", "dates & years")]

conn = data.connect()
NOVELS = data.list_novels(conn)


def _label(n: dict) -> str:
    return f"{n['title']} ({n['author']}, {n['year']})"


def _stat(value, caption):
    return html.Div([html.Div(value, style={"fontSize": "22px", "fontWeight": 600, "color": INK}),
                     html.Div(caption, style={"fontSize": "12px", "color": MUTED})],
                    style={"marginRight": "28px"})


app = Dash(__name__, title="Narrative time")
app.layout = html.Div(style={"fontFamily": FONT, "background": SURFACE, "padding": "18px 24px",
                             "color": INK2, "minHeight": "100vh"}, children=[
    html.H2("Narrative time in the nineteenth-century novel", style={"color": INK, "margin": "0 0 4px"}),
    html.Div("HUM19UK, 91 novels. Timeline view: scenes as told, the story time their cues state, "
             "and the temporal events within them.", style={"marginBottom": "14px"}),
    html.Div(style={"display": "flex", "gap": "18px", "flexWrap": "wrap", "alignItems": "end"}, children=[
        html.Div([html.Label("Novel"),
                  dcc.Dropdown(id="novel", options=[{"label": _label(n), "value": n["filename"]} for n in NOVELS],
                               value="1847.txt", clearable=False, style={"width": "460px"})]),
        html.Div([html.Label("Events shown"),
                  dcc.Checklist(id="lanes", options=[{"label": f" {t}", "value": v} for v, t in LANE_OPTIONS],
                                value=[v for v, _ in LANE_OPTIONS], inline=True,
                                inputStyle={"marginLeft": "10px"})]),
        html.Div([html.Label("Flashback confidence"),
                  dcc.RadioItems(id="confidence", options=[{"label": " 0.8 and up (discrete events)", "value": 0.8},
                                                           {"label": " 1.0 only (all three signals)", "value": 1.0}],
                                 value=0.8, inline=True, inputStyle={"marginLeft": "10px"})]),
    ]),
    html.Div(id="stats", style={"display": "flex", "margin": "16px 0 4px"}),
    dcc.Graph(id="timeline", config={"displaylogo": False, "toImageButtonOptions":
                                     {"format": "svg", "filename": "timeline", **EXPORT_SIZE}}),
    html.Div(style={"display": "flex", "gap": "10px", "alignItems": "center"}, children=[
        html.Span("Export at publication size:"),
        *[html.Button(fmt.upper(), id=f"export-{fmt}", n_clicks=0) for fmt in ("svg", "pdf", "png")],
        dcc.Download(id="download"),
    ]),
    html.Div(style={"marginTop": "14px", "fontSize": "12px", "color": MUTED, "maxWidth": "980px"}, children=[
        "Story time stated is a lower bound: the scene's dated span plus jump cues with a stated "
        "quantity. Cues inside reported speech count too, so read it with the hover's breakdown. "
        "Heuristic detections, not ground truth.",
    ]),
])


@app.callback(Output("timeline", "figure"), Output("stats", "children"),
              Input("novel", "value"), Input("lanes", "value"), Input("confidence", "value"))
def update(filename, lanes, confidence):
    d = data.load_timeline(conn, filename, min_confidence=confidence)
    s = timeline.summary(d)
    mix = s["label_mix"]
    stats = [_stat(f"{s['words']:,}", "words"), _stat(s["scenes"], "scenes"),
             _stat(f"{mix['jump']}/{mix['iterative']}/{mix['continuous']}/{mix['anchored']}/{mix['unmarked']}",
                   "jump / iterative / continuous / anchored / unmarked"),
             _stat(s["flashbacks"], f"flashbacks (conf. ≥ {confidence})"),
             _stat(s["jumps"], "forward jumps"), _stat(s["absolute"], "dates, years, clock times")]
    return timeline.build_timeline(d, lanes=set(lanes)), stats


@app.callback(Output("download", "data"),
              Input("export-svg", "n_clicks"), Input("export-pdf", "n_clicks"), Input("export-png", "n_clicks"),
              State("novel", "value"), State("lanes", "value"), State("confidence", "value"),
              prevent_initial_call=True)
def export(_svg, _pdf, _png, filename, lanes, confidence):
    from dash import ctx
    fmt = ctx.triggered_id.split("-")[1]
    fig = timeline.build_timeline(data.load_timeline(conn, filename, min_confidence=confidence), lanes=set(lanes))
    body = fig.to_image(format=fmt, **EXPORT_SIZE)
    return dcc.send_bytes(body, f"{filename.removesuffix('.txt')}_timeline.{fmt}")


def main():
    parser = argparse.ArgumentParser(description="Run the narrative-time dashboard")
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    app.run(port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
