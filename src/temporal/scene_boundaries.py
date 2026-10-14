"""
Scene boundary detection from formatting cues.

Primary signal: the "* * * * *" asterisk break. Confirmed in Weeks 3-4 to be
a real convention in 32/100 novels (224 occurrences) and to survive
preprocess.py's cleaning intact, so it's read straight from the stored
`cleaned_text` -- no re-parsing of raw files. Blank-line runs are NOT used:
every instance checked turned out to be chapter-tag whitespace or verse
formatting, not a within-chapter scene break.

Fallback: a division (chapter/volume) with no asterisk break is treated as
one scene. A novel with no divisions at all (1817.txt, 1835.txt) is treated
as a single division spanning the whole text, so it gets exactly one scene.
"""
import re

SCENE_BREAK_PATTERN = re.compile(r"^[ \t]*\*(?:[ \t]*\*){2,}[ \t]*$", re.MULTILINE)


def find_scene_breaks(cleaned_text: str) -> list[int]:
    """Character offsets (into cleaned_text) of each asterisk scene break."""
    return [m.start() for m in SCENE_BREAK_PATTERN.finditer(cleaned_text)]


def compute_scenes(cleaned_text: str, division_starts: list[tuple]) -> list[dict]:
    """division_starts: [(division_id, start_char), ...] sorted by start_char,
    or [] for a novel with no divisions.

    Returns scene spans in reading order, each tagged with how it was found:
        {"division_id", "start_char", "end_char", "source"}
    where source is "asterisk_break" (scene opened by a break inside its
    division) or "division" (scene opened by the division itself).
    """
    breaks = find_scene_breaks(cleaned_text)
    if not division_starts:
        division_starts = [(None, 0)]

    scenes = []
    for i, (div_id, d_start) in enumerate(division_starts):
        d_end = division_starts[i + 1][1] if i + 1 < len(division_starts) else len(cleaned_text)
        cursor, source = d_start, "division"
        for b in (b for b in breaks if d_start <= b < d_end):
            scenes.append({"division_id": div_id, "start_char": cursor, "end_char": b, "source": source})
            cursor, source = b, "asterisk_break"
        scenes.append({"division_id": div_id, "start_char": cursor, "end_char": d_end, "source": source})
    return scenes
