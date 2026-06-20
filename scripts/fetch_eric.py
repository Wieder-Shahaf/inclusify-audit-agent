"""Fetch additional ERIC documents via the public api.ies.ed.gov endpoint.

Appends to data/eric/academic_inclusivity_corpus(in).csv using the same schema:
chunk_id,source,doc_id,title,content_type,chunk_text,subject,year,peerreviewed,url,license

No key required. Offline-default stays — this script is a developer tool, run on
demand to expand the retrieval corpus.

Usage:
    python scripts/fetch_eric.py --queries data/eric/queries.txt --per-query 100
    python scripts/fetch_eric.py --query "gender inclusive pronoun" --rows 200 --out append
    python scripts/fetch_eric.py --query "..." --rows 50 --out /tmp/preview.csv  # write elsewhere
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.ies.ed.gov/eric/"
_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = _REPO_ROOT / "data" / "eric" / "academic_inclusivity_corpus(in).csv"
HEADER = [
    "chunk_id", "source", "doc_id", "title", "content_type", "chunk_text",
    "subject", "year", "peerreviewed", "url", "license",
]


def _http_get_json(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "inclusify-audit-agent/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        import json
        return json.loads(resp.read())


def fetch_page(query: str, *, rows: int = 100, start: int = 0) -> list[dict]:
    """Fetch one page of ERIC results."""
    params = {
        "search": query,
        "format": "json",
        "rows": str(rows),
        "start": str(start),
    }
    url = API + "?" + urllib.parse.urlencode(params)
    data = _http_get_json(url)
    return data.get("response", {}).get("docs", [])


def fetch_many(query: str, *, total: int, page_size: int = 100, pause: float = 0.3) -> list[dict]:
    """Fetch up to `total` docs for one query (paginated)."""
    out: list[dict] = []
    start = 0
    while len(out) < total:
        page = fetch_page(query, rows=min(page_size, total - len(out)), start=start)
        if not page:
            break
        out.extend(page)
        start += len(page)
        if pause:
            time.sleep(pause)
    return out


def _coerce_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, list):
        return "; ".join(str(x) for x in v)
    return str(v)


def normalize(doc: dict, *, next_chunk_id: int) -> dict[str, str]:
    """Map an ERIC API doc to the corpus CSV row schema."""
    doc_id = _coerce_str(doc.get("id", ""))
    return {
        "chunk_id": str(next_chunk_id),
        "source": "eric",
        "doc_id": doc_id,
        "title": _coerce_str(doc.get("title", "")),
        "content_type": "abstract",
        "chunk_text": _coerce_str(doc.get("description", "")),
        "subject": _coerce_str(doc.get("subject", "")),
        "year": _coerce_str(doc.get("publicationdateyear", "")),
        "peerreviewed": _coerce_str(doc.get("peerreviewed", "")),
        "url": f"https://eric.ed.gov/?id={doc_id}" if doc_id else "",
        "license": "public-domain",
    }


def existing_ids(path: Path) -> tuple[set[str], int]:
    """Return (set of doc_ids already in the corpus, next chunk_id to assign)."""
    csv.field_size_limit(2_000_000)
    if not path.exists():
        return set(), 1
    ids: set[str] = set()
    max_chunk = 0
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("doc_id"):
                ids.add(row["doc_id"])
            try:
                max_chunk = max(max_chunk, int(row.get("chunk_id", "0")))
            except ValueError:
                pass
    return ids, max_chunk + 1


def append_rows(path: Path, rows: list[dict]) -> int:
    """Append rows to the CSV. Creates with header if missing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        if new_file:
            w.writeheader()
        for r in rows:
            w.writerow(r)
    return len(rows)


def write_rows(path: Path, rows: list[dict]) -> int:
    """Overwrite path with rows (used when --out is an explicit file path)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return len(rows)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch ERIC docs via the public API.")
    p.add_argument("--query", action="append", default=[],
                   help="Query string. Repeat for multiple. Or use --queries file.")
    p.add_argument("--queries", type=Path, default=None,
                   help="File with one query per line.")
    p.add_argument("--rows", type=int, default=100,
                   help="Max docs per query (default: 100).")
    p.add_argument("--page-size", type=int, default=100)
    p.add_argument("--pause", type=float, default=0.3,
                   help="Seconds between paged requests (politeness).")
    p.add_argument("--out", default="append",
                   help="'append' (default, appends to the main corpus) or a CSV path.")
    p.add_argument("--corpus", type=Path, default=DEFAULT_OUT,
                   help="Main corpus path (for dedup + append).")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    queries: list[str] = list(args.query)
    if args.queries:
        queries.extend(
            line.strip() for line in args.queries.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
    if not queries:
        print("error: provide --query or --queries", file=sys.stderr)
        return 2

    seen, next_id = existing_ids(args.corpus)
    print(f"existing corpus: {args.corpus} -> {len(seen)} unique doc_ids, "
          f"next chunk_id={next_id}", file=sys.stderr)

    new_rows: list[dict] = []
    for q in queries:
        print(f"fetching: {q!r} (rows={args.rows})", file=sys.stderr)
        docs = fetch_many(q, total=args.rows, page_size=args.page_size, pause=args.pause)
        added = 0
        for d in docs:
            did = d.get("id", "")
            if not did or did in seen:
                continue
            row = normalize(d, next_chunk_id=next_id)
            if not row["chunk_text"].strip():
                continue
            new_rows.append(row)
            seen.add(did)
            next_id += 1
            added += 1
        print(f"  fetched={len(docs)} new={added}", file=sys.stderr)

    if not new_rows:
        print("no new rows to add", file=sys.stderr)
        return 0

    if args.out == "append":
        n = append_rows(args.corpus, new_rows)
        print(f"appended {n} rows to {args.corpus}", file=sys.stderr)
    else:
        out_path = Path(args.out)
        n = write_rows(out_path, new_rows)
        print(f"wrote {n} rows to {out_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
