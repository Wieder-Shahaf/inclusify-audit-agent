"""Pure guard functions for the v2 pipeline's [0] GUARDS stage (PRD §4/§5, BUILD_PLAN R1).

Server wiring — actually rejecting a request before `chunk.parse()` runs — lands in a
later phase (R4+); R1 only ships the functions themselves.
"""
from __future__ import annotations

import os

# Calibrated to Vercel's 300 s function cap (course spec): audits are sequential
# (~10 s/window) + investigations ~1.2 s/candidate effective at 5 concurrent lanes.
# 10 windows covers the PRD's largest use case (12-page paper = 9-10 windows) and
# keeps a realistically dense run near ~230 s. Raise via AGENT_MAX_WINDOWS where
# there is no serverless timeout (local Docker).
DEFAULT_MAX_WINDOWS = 10


def is_probably_english(text: str) -> bool:
    """True if, among the text's alphabetic characters, the Latin-letter ratio is >= 0.5.

    Empty text or text with no alphabetic characters at all -> False. English-only
    scope (PRD §1): non-Latin-dominant input gets a clean human-readable rejection.
    """
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    latin = sum(1 for c in letters if "a" <= c.lower() <= "z")
    return (latin / len(letters)) >= 0.5


def max_windows() -> int:
    """Window-count cap (PRD §4 guard [0]). Callers compare `len(windows) > max_windows()`
    themselves — no `window_count()` wrapper needed for a one-line `len()` call."""
    return int(os.environ.get("AGENT_MAX_WINDOWS", str(DEFAULT_MAX_WINDOWS)))
