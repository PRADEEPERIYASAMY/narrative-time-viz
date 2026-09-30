"""Shared confidence-scoring helper. Weight constants for each detector
live in that detector's own module (flashback_detector.py, etc.) -- this
just keeps the clamp logic in one place instead of duplicated per module."""


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))
