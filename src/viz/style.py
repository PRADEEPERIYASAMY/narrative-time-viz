"""Palette and type for every Phase 3 figure -- the same validated values
as plot_phase2.py (categorical slots in fixed order: blue, orange, aqua,
yellow; adjacent CVD dE >= 9.1 on the light surface), so a scene label
means the same colour in the report figures and in the dashboard."""

BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
SURFACE, INK, INK2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, AXIS, NEUTRAL = "#e1e0d9", "#c3c2b7", "#d8d7d0"
FONT = "Segoe UI, DejaVu Sans, Arial, sans-serif"

# scene duration labels (scene_duration.DURATION_LABELS), as in
# corpus_scene_durations.png; the novel's opening scene has no boundary
# event and so no label
LABEL_COLORS = {
    "jump": BLUE,
    "iterative": YELLOW,
    "continuous": AQUA,
    "anchored": ORANGE,
    "unmarked": NEUTRAL,
    "opening": "#ecebe6",
}
LABEL_TEXT = {
    "jump": "jump: a forward jump or date advance",
    "iterative": "iterative: habitual, span > 1 occasion",
    "continuous": "continuous: sequence cues, no gap stated",
    "anchored": "anchored: placed in time, no movement",
    "unmarked": "unmarked: no temporal cue",
    "opening": "opening scene (no boundary event)",
}
