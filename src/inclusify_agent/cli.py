"""Inclusify audit CLI.

Usage:
    python -m inclusify_agent.cli audit <input.txt> [--provider mock|openai_compat|azure]
                                          [--format json|markdown]
                                          [--store chroma|inmemory|qdrant]
                                          [--max-iters N]
                                          [--output PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import config
from .agent import run_audit
from .providers.vectorstore import InMemoryStore
from .report import render, to_markdown, validate


def _cmd_audit(args: argparse.Namespace) -> int:
    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
    if args.store:
        os.environ["VECTOR_STORE"] = args.store

    text = Path(args.input).read_text(encoding="utf-8")
    embedder = config.build_embeddings()
    # Use a small in-memory seed store by default to avoid needing a pre-built Chroma.
    # In production: Phase 5 ingest fills .chroma/ and VECTOR_STORE=chroma uses it.
    if args.store == "inmemory" or args.store is None:
        store = InMemoryStore(dim=embedder.dim)
    else:
        store = config.build_vector_store(dim=embedder.dim)

    llm = config.build_llm()
    final = run_audit(
        text, llm=llm, embedder=embedder, store=store, max_iters=args.max_iters,
    )
    report = render(final)
    validate(report)

    if args.format == "markdown":
        out = to_markdown(report)
    else:
        out = json.dumps(report, indent=2, default=str)

    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(out)
        if not out.endswith("\n"):
            sys.stdout.write("\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="inclusify-audit")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_audit = sub.add_parser("audit", help="Audit a document for non-inclusive language.")
    p_audit.add_argument("input", help="Path to the input .txt file.")
    p_audit.add_argument("--provider", choices=("mock", "openai_compat", "azure"), default=None)
    p_audit.add_argument("--store", choices=("chroma", "inmemory", "qdrant"), default=None)
    p_audit.add_argument("--format", choices=("json", "markdown"), default="json")
    p_audit.add_argument("--output", "-o", default=None,
                         help="Write to a file instead of stdout.")
    p_audit.add_argument("--max-iters", type=int, default=None)
    p_audit.set_defaults(func=_cmd_audit)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
