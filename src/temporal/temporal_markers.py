"""
Explicit temporal-marker phrase detection -- literal (case-insensitive,
whole-word) phrase matching, not a trained classifier.

Each phrase is assigned a category describing what it signals about story
time, because different detectors need different subsets:

  forward_jump   story time skips ahead ("years later", "the next day")
  retrospective  points back to an earlier time ("long ago", "ever since")
  simultaneity   a parallel strand at the same time ("meanwhile")
  time_of_day    a time-of-day anchor ("at dawn")
  anchor         a reference point, no direction ("by now", "that same day")
  abruptness     a sudden onset within continuous time ("suddenly")

The categories were introduced in Weeks 5-6, after this module first ran
against real text: 104 of 229 hits across the 5-novel test slice were
"suddenly", which marks an abrupt event, not a skip in story time. Counting
it as a jump overstated scene duration (one Dracula chapter showed 11
"jumps") and fed noise into the flashback cue signal. scene_duration.py now
counts only forward_jump phrases; flashback_detector.py reads only
retrospective (flashback) or forward_jump (flash-forward) phrases as cues.

Absolute time references (Weeks 7-8) are a second, pattern-based family:

  calendar_date  "3 May", "1st of May", "May 3rd"  -> normalized (month, day)
  clock_time     "8:35 P. M.", "ten o'clock", "half-past nine"

Added after the Weeks 5-6 run showed the phrase list caught none of
Dracula's 191 dates and 60 clock times. Formats were taken from the real
text first (Dracula's diary headers read "3 May.-I found..."); month names
are matched case-sensitively so the modal verb "may" never counts.

Weeks 9-10: the phrase list moved out of this file into cue_taxonomy.csv, a
controlled vocabulary that can be edited without touching code. It merges
the list above with Shawna Ross's supplemental taxonomy (built from her
narratological schema after Genette and Rimmon-Kenan), each row audited
against the corpus: a row is "active", "covered" (a broader pattern matches
it), or "excluded" (with the reason and hit count in its notes). New
categories: sequence, recollection, duration, meal, seasonal, holiday,
biographical, travel, frequency. Spelled-out dates ("the fifteenth of July")
and years ("in the year 1756", the withheld "17--") join the absolute
family. Every category belongs to one tier (CATEGORY_TIER), so no sentence
or scene is presumed continuous merely for lacking a jump.
"""
import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

TAXONOMY_PATH = Path(__file__).with_name("cue_taxonomy.csv")

# what each category says about story time
CATEGORY_TIER = {
    "calendar_date": "absolute", "clock_time": "absolute", "year": "absolute", "holiday": "absolute",
    "forward_jump": "movement", "retrospective": "movement", "recollection": "movement",
    "duration": "movement", "biographical": "movement", "travel": "movement",
    "time_of_day": "position", "meal": "position", "seasonal": "position",
    "simultaneity": "position", "anchor": "position",
    "sequence": "order",
    "frequency": "iterative",
    "abruptness": "not_temporal",
}

_NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
            "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
            "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "hundred": 100,
            "next": 1, "following": 1}
_UNIT_DAYS = {"hour": 1 / 24, "morning": 1, "day": 1, "evening": 1, "night": 1, "afternoon": 1,
              "week": 7, "fortnight": 14, "month": 30, "twelvemonth": 365, "year": 365,
              "spring": 91, "summer": 91, "autumn": 91, "winter": 91, "season": 91}
_EFFECT = re.compile(r"^\+(\d+) (\w+?)s?$")
def delta_days(story_time_effect: str, surface: str):
    """Story time a cue states, in days, or None if it states none. The
    taxonomy gives either a fixed effect ("+1 day") or "parsed", meaning the
    quantity is read from the matched text: a unit word with a number up to
    two words before it ("two years later" -> 730, "three long weeks" ->
    21). Vague quantities ("some days later", "several years") give None."""
    m = _EFFECT.match(story_time_effect)
    if m:
        return int(m.group(1)) * _UNIT_DAYS.get(m.group(2), 0) or None
    if story_time_effect != "parsed":
        return None
    words = re.findall(r"[a-z]+", surface.lower())
    for i, w in enumerate(words):
        unit = w if w in _UNIT_DAYS else w[:-1] if w[:-1] in _UNIT_DAYS else None
        if unit is None:
            continue
        for j in (i - 1, i - 2):
            if j >= 0 and words[j] in _NUMBERS:
                return round(_NUMBERS[words[j]] * _UNIT_DAYS[unit], 2)
        return None
    return None


@dataclass(frozen=True)
class Cue:
    pattern: str
    match: str              # phrase | phrase_cs | regex | regex_cs
    category: str
    confidence: float
    story_time_effect: str
    duration_modifier: str  # "multi-unit" for iterative cues, else ""


def _load_taxonomy(path: Path = TAXONOMY_PATH) -> list[Cue]:
    with open(path, encoding="utf-8") as f:
        return [Cue(r["pattern"], r["match"], r["category"], float(r["confidence"]),
                    r["story_time_effect"], r["duration_modifier"])
                for r in csv.DictReader(f) if r["status"] == "active"]


CUES = _load_taxonomy()


def _cue_regex(cue: Cue) -> str:
    if cue.match.startswith("regex"):
        body = cue.pattern
    else:  # whole-word literal; straight and curly apostrophes alike
        body = r"\b" + re.escape(cue.pattern).replace("’", "'").replace("'", "['’]") + r"\b"
    return body if cue.match.endswith("_cs") else f"(?i:{body})"


# One alternation per pass keeps matching fast on 570,000 sentences.
# Literal phrases go longest-first so "the next morning at the inn" beats
# "the next morning"; each regex row is a named group so a match knows its
# row. Overlaps between the two passes are settled in find_marker_spans.
_LITERALS = sorted((c for c in CUES if not c.match.startswith("regex")), key=lambda c: -len(c.pattern))
_LITERAL_RE = re.compile("|".join(f"(?P<l{i}>{_cue_regex(c)})" for i, c in enumerate(_LITERALS)))
_REGEXES = [c for c in CUES if c.match.startswith("regex")]
_REGEX_RE = re.compile("|".join(f"(?P<r{i}>{_cue_regex(c)})" for i, c in enumerate(_REGEXES)))
_ROW = {**{f"l{i}": c for i, c in enumerate(_LITERALS)}, **{f"r{i}": c for i, c in enumerate(_REGEXES)}}

MARKER_CATEGORY = {c.pattern.lower(): c.category for c in _LITERALS}


@dataclass(frozen=True)
class Marker:
    surface: str          # the matched text, lowercased
    category: str
    start: int            # char offset within the searched text
    confidence: float
    delta_days: float | None = None   # story time the cue states, if any
    duration_modifier: str = ""       # "multi-unit": span unknown, likely > 1 unit


def _matches(text: str):
    for pattern in (_LITERAL_RE, _REGEX_RE):
        for m in pattern.finditer(text):
            # lastgroup is the innermost named group closed last -- for the
            # "day after day" row that is its backreference group, so walk
            # the row groups instead
            name = next(k for k, v in m.groupdict().items() if v is not None and k in _ROW)
            yield m.start(), m.end(), _ROW[name]


def find_marker_spans(text: str) -> list[Marker]:
    """Every taxonomy cue in the text, in order. Where two cues overlap the
    longer one wins ("two years later" over "years later"), so each stretch
    of text counts once."""
    found = sorted(_matches(text), key=lambda t: (t[0], -(t[1] - t[0])))
    out, end = [], -1
    for start, stop, cue in found:
        if start < end:
            continue
        surface = text[start:stop].lower()
        out.append(Marker(surface, cue.category, start, cue.confidence,
                          delta_days(cue.story_time_effect, surface), cue.duration_modifier))
        end = stop
    return out


def find_markers(text: str) -> list[str]:
    """Every matched cue's text (lowercased), in order of appearance. A
    sentence can match more than once."""
    return [m.surface for m in find_marker_spans(text)]


@lru_cache(maxsize=4096)
def category_of(phrase: str) -> str | None:
    if phrase.lower() in MARKER_CATEGORY:
        return MARKER_CATEGORY[phrase.lower()]
    found = find_marker_spans(phrase)
    return found[0].category if len(found) == 1 and found[0].surface == phrase.lower() else None


def phrases_in(phrases: list[str], category) -> list[str]:
    """The subset of already-matched phrases belonging to a category (or to
    any of a tuple of categories)."""
    cats = (category,) if isinstance(category, str) else tuple(category)
    return [p for p in phrases if category_of(p) in cats]


# --- absolute time references -----------------------------------------------

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
_MONTH = "|".join(MONTHS)
_ORD = r"(?:st|nd|rd|th)?"
_HOUR_WORD = "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"

_ORDINALS = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth",
             "tenth", "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth",
             "seventeenth", "eighteenth", "nineteenth", "twentieth"]
_ORDINAL_DAY = {w: i + 1 for i, w in enumerate(_ORDINALS)}
_ORDINAL_DAY.update({f"twenty{sep}{w}": 20 + i + 1 for i, w in enumerate(_ORDINALS[:9]) for sep in ("-", " ")})
_ORDINAL_DAY.update({"thirtieth": 30, "thirty-first": 31, "thirty first": 31})
_ORD_WORD = "|".join(sorted(_ORDINAL_DAY, key=len, reverse=True))

# case-sensitive on purpose: "May" the month, never "may" the verb
_DAY_MONTH = re.compile(rf"\b(?P<day>[0-3]?\d){_ORD}\.? (?:of )?(?P<month>{_MONTH})\b")
_MONTH_DAY = re.compile(rf"\b(?P<month>{_MONTH}),? (?P<day>[0-3]?\d){_ORD}\b(?![\d\-—_*])")
# spelled out, as period prose usually has it: "the fifteenth of July",
# "the twenty-fifth November", "July the fifth"
_WORD_DAY_MONTH = re.compile(rf"\b(?i:the) (?P<day>(?i:{_ORD_WORD})) (?:of )?(?P<month>{_MONTH})\b")
_MONTH_WORD_DAY = re.compile(rf"\b(?P<month>{_MONTH}),? the (?P<day>(?i:{_ORD_WORD}))\b")
_CLOCK = re.compile(
    rf"\b(?:[01]?\d|2[0-3])[:.][0-5]\d\b(?:\s?[ap]\.\s?m\.)?"
    rf"|\b(?:\d{{1,2}}|{_HOUR_WORD}) o['’]clock\b"
    rf"|\b(?:half|a quarter)[- ](?:past|to) (?:\d{{1,2}}|{_HOUR_WORD})\b",
    re.IGNORECASE,
)
# a stated year: "in the year 1756", "A.D. 1660", "in 1773," -- a bare
# four-digit number needs one of these frames, so sums and counts don't
# qualify. Plus the period's withheld year, "17--" / "18—".
_YEAR = re.compile(
    r"\b(?:[Tt]he year|A\.\s?D\.)\s*(?:of our Lord\s*)?(?P<y1>1\d{3}|20\d\d)\b"
    r"|\b(?:[Ii]n|of|since|until|till) (?P<y2>1[5-9]\d\d|20\d\d)(?=\s*[,.;:)!?])"
    rf"|\b(?:{_MONTH}),? (?P<y3>1[5-9]\d\d)\b"
    r"|\b1[5-9](?:-{2,}|—+|_{2,}|\*{2,})"
)


@dataclass(frozen=True)
class TimeRef:
    surface: str      # the matched text, lowercased
    category: str     # "calendar_date", "clock_time", or "year"
    start: int        # char offset within the searched text
    month_day: tuple | None = None   # (month 1-12, day) for calendar dates
    year: int | None = None          # for a stated year; None when withheld ("17--")


def find_time_refs(text: str) -> list[TimeRef]:
    """Calendar dates, clock times, and years, in order of appearance."""
    refs = []
    for pattern in (_DAY_MONTH, _MONTH_DAY, _WORD_DAY_MONTH, _MONTH_WORD_DAY):
        for m in pattern.finditer(text):
            d = m.group("day").lower()
            day = int(d) if d.isdigit() else _ORDINAL_DAY[d]
            if 1 <= day <= 31:
                refs.append(TimeRef(m.group(0).lower(), "calendar_date", m.start(),
                                    (MONTHS.index(m.group("month")) + 1, day)))
    for m in _CLOCK.finditer(text):
        refs.append(TimeRef(m.group(0).lower(), "clock_time", m.start()))
    for m in _YEAR.finditer(text):
        y = m.group("y1") or m.group("y2") or m.group("y3")
        refs.append(TimeRef(m.group(0).lower(), "year", m.start(), year=int(y) if y else None))
    return sorted(refs, key=lambda r: r.start)
