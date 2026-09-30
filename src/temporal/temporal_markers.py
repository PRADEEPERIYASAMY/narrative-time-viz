"""
Explicit temporal-marker phrase detection -- literal (case-insensitive)
phrase matching, not a trained classifier.

Seed list combines the 13 phrases already validated against the Phase 1
corpus (reports/weeks-01-02.md's "Deeper extraction" section: 3,001 hits
corpus-wide from just these) with additional SOW-aligned phrases ("that
same day," "not long after," etc.) not previously tested against the
corpus -- treat the latter as untested until this module actually runs and
reports counts.
"""
import re

# validated against the Phase 1 corpus (reports/weeks-01-02.md)
_VALIDATED_PHRASES = [
    "years later", "months later", "days later", "weeks later",
    "at dawn", "at dusk", "in the meantime", "meanwhile",
    "the following day", "the next day", "years before", "long ago", "years ago",
]

# additional phrases, not yet validated against this corpus
_ADDITIONAL_PHRASES = [
    "that same day", "not long after", "some time later", "by now",
    "until now", "from then on", "ever since", "in those days",
    "it was not until", "before long", "all at once", "suddenly",
]

MARKER_PHRASES = _VALIDATED_PHRASES + _ADDITIONAL_PHRASES

_PATTERN = re.compile(
    "|".join(re.escape(p) for p in sorted(MARKER_PHRASES, key=len, reverse=True)),
    re.IGNORECASE,
)


def find_markers(text: str) -> list[str]:
    """Return every matched phrase (lowercased), in order of appearance.
    A sentence can match more than once (e.g. two different phrases)."""
    return [m.group(0).lower() for m in _PATTERN.finditer(text)]
