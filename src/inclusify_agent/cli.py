"""CLI entry point. Phase 6 wires `inclusify-audit audit <file>` to the graph."""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    print("inclusify-audit-agent: CLI not wired yet (Phase 6).", file=sys.stderr)
    print(f"args: {argv}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
