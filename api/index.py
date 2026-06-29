"""Vercel ASGI entrypoint.

Vercel's Python runtime serves the module-level `app` (ASGI). vercel.json rewrites
every path here, so the FastAPI app owns both the GUI (/) and the API (/api/*) —
one deployment, same-origin, no CORS.

The package is src-layout and pure-Python, so we add src/ to the path rather than
installing it (requirements.txt covers the third-party deps).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from inclusify_agent.server import app  # noqa: E402

__all__ = ["app"]
