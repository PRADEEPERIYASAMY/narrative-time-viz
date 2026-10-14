"""Writes detected events into the temporal_events table (the SOW's
per-novel "temporal event log")."""
import json
import sqlite3


def log_event(
    conn: sqlite3.Connection, *, novel_id: int, granularity: str, event_type: str,
    sentence_id=None, division_id=None, page_id=None, subtype: str = None,
    confidence: float = None, detail: dict = None, start_char: int = None,
    end_char: int = None,
) -> int:
    cur = conn.execute(
        """INSERT INTO temporal_events
           (novel_id, sentence_id, division_id, page_id, granularity,
            event_type, subtype, confidence, detail, start_char, end_char)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (novel_id, sentence_id, division_id, page_id, granularity, event_type,
         subtype, confidence, json.dumps(detail) if detail is not None else None,
         start_char, end_char),
    )
    return cur.lastrowid
