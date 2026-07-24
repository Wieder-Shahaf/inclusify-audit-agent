"""Precompute `GET /api/agent_info`'s `prompt_examples` (PRD §8: a Vercel cold
start shouldn't re-run the audit pipeline on every request).

Run: python scripts/gen_examples.py
Writes: src/inclusify_agent/data/agent_info_examples.json (committed).

Runs against whatever provider env is set (LLM_PROVIDER etc.) -- defaults to the
offline-first MockLLM (config.py's default), so committing here is safe with zero
keys. R7 reruns this against the live course stack once keys are available.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from inclusify_agent.server.app import _EXAMPLE_PROMPTS, execute_prompt  # noqa: E402

_OUT = (
    Path(__file__).resolve().parents[1]
    / "src" / "inclusify_agent" / "data" / "agent_info_examples.json"
)


def main() -> None:
    out = []
    for p in _EXAMPLE_PROMPTS:
        r = execute_prompt(p)
        out.append({"prompt": p, "full_response": r["response"], "steps": r["steps"]})
    _OUT.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"wrote {_OUT} ({_OUT.stat().st_size} bytes, {len(out)} examples)")


if __name__ == "__main__":
    main()
