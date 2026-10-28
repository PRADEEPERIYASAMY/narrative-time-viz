"""Writes detected events into the temporal_events table (the SOW's
per-novel "temporal event log")."""
import json
import sqlite3


def log_event(
    conn: sqlite3.Connection, *, novel_id: int, granularity: str, event_type: str,
    sentence_id=None, division_id=None, page_id=None, subtype: str = None,
    confidence: float = None, detail: dict = None, start_char: int = None,
    end_char: int = None, duration_modifier: str = None,
) -> int:
    """duration_modifier: "multi-unit" when the event's story-time span is
    unknown but likely more than one occasion (iterative / habitual cues)."""
    cur = conn.execute(
        """INSERT INTO temporal_events
           (novel_id, sentence_id, division_id, page_id, granularity,
            event_type, subtype, confidence, detail, start_char, end_char,
            duration_modifier)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (novel_id, sentence_id, division_id, page_id, granularity, event_type,
         subtype, confidence, json.dumps(detail) if detail is not None else None,
         start_char, end_char, duration_modifier),
    )
    return cur.lastrowid
