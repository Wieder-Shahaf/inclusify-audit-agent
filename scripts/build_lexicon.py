#!/usr/bin/env python3
"""Sourced build script for the v2 inclusive-language lexicon (BUILD_PLAN.md R2).

Merges five inputs into ``src/inclusify_agent/data/inclusive_lexicon.json``:

1. **retext-equality** (MIT) -- the 9 YAML rule files under ``data/en/`` in
   https://github.com/retextjs/retext-equality, fetched at a resolved commit sha
   (recorded per-entry in ``source`` for reproducibility).
2. **Inclusive Naming Initiative** (CC-BY) -- the tiered tech-term word list published
   as JSON at https://inclusivenaming.org/word-lists/index.json.
3. **Tiny Heap / marionbartl/affixed_words** (CC0) -- gendered-occupation affix pairs,
   https://github.com/marionbartl/affixed_words, ``words/replacements+plural-final.csv``
   (the repo's own "Final List", per its README round 1-4 pipeline). This is the
   dataset our Assignment 2 cites as "Tiny Heap"; the actual upstream repo is
   marionbartl/affixed_words.
4. **Hand-curated CSVs** (``data/lexicon/curated_{apa,ncdj,glaad}.csv``) -- terms
   actually present on the APA bias-free-language guide, the NCDJ Disability
   Language Style Guide, and the GLAAD Media Reference Guide, read directly off
   those pages (see data/lexicon/README.md for exact URLs and dates).
5. **Legacy v1 lexicon** (the 44 hand-written terms previously bundled) -- kept as a
   safety net so every legacy term survives the rebuild even where no external
   source happens to also cover it.

retext-equality file -> lexicon category map (per BUILD_PLAN R2 / project spec)::

    gender.yml        -> gendered
    ablist.yml        -> ableist
    lgbtq.yml         -> outdated
    race.yml          -> potentially-offensive
    condescending.yml -> potentially-offensive
    suicide.yml       -> potentially-offensive
    misc.yml          -> exclusionary
    press.yml         -> biased
    slogans.yml       -> biased

Merge precedence on term collision (case-insensitive; first-listed source wins
category + alternatives, notes/conditions concatenate)::

    retext-equality > Inclusive Naming Initiative > Tiny Heap occupations
        > curated CSVs > legacy v1 lexicon

Usage::

    python scripts/build_lexicon.py [--offline-cache DIR]

Without ``--offline-cache``: fetches every network source fresh and writes raw
copies into ``data/lexicon/cache/`` (gitignored) so a later run can reproduce this
exact output offline. With ``--offline-cache DIR``: reads previously-cached raw
files from DIR instead of touching the network at all.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import urllib.request
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
LEXICON_DIR = REPO_ROOT / "data" / "lexicon"
# A frozen, checked-in snapshot of the pre-R2 44-term lexicon -- the safety-net input.
# Deliberately NOT the output path: OUT_JSON gets overwritten on every run, so reading
# the safety net from there would make run N+1 treat run N's full output as "legacy",
# which is harmless but silently defeats the point of a fixed safety net.
LEGACY_SNAPSHOT_JSON = LEXICON_DIR / "legacy_v1_lexicon.json"
# The bundled artifact this script regenerates.
OUT_JSON = REPO_ROOT / "src" / "inclusify_agent" / "data" / "inclusive_lexicon.json"

ALLOWED_CATEGORIES = {
    "gendered", "exclusionary", "ableist", "outdated",
    "factually-incorrect", "potentially-offensive", "biased",
}

Entry = dict[str, Any]

# ---------------------------------------------------------------------------
# 1. retext-equality
# ---------------------------------------------------------------------------

RETEXT_REPO_API = "https://api.github.com/repos/retextjs/retext-equality"
RETEXT_RAW_TMPL = "https://raw.githubusercontent.com/retextjs/retext-equality/{sha}/data/en/{name}.yml"
RETEXT_FILE_CATEGORY = {
    "gender": "gendered",
    "ablist": "ableist",
    "lgbtq": "outdated",
    "race": "potentially-offensive",
    "condescending": "potentially-offensive",
    "suicide": "potentially-offensive",
    "misc": "exclusionary",
    "press": "biased",
    "slogans": "biased",
}


def _http_get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "inclusify-audit-agent/build_lexicon"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https URLs, not user input)
        return resp.read()


def _retext_rule_to_entries(
    rule: dict, category: str, filename: str, source_tag: str,
) -> list[Entry]:
    inconsiderate = rule.get("inconsiderate", [])
    if isinstance(inconsiderate, dict):
        terms = list(inconsiderate.keys())
    elif isinstance(inconsiderate, str):
        terms = [inconsiderate]
    else:
        terms = list(inconsiderate or [])

    considerate = rule.get("considerate", [])
    if isinstance(considerate, str):
        alternatives = [considerate]
    else:
        alternatives = [str(a) for a in (considerate or [])]

    note = str(rule.get("note", "") or "")
    nested_source = rule.get("source")
    if nested_source:
        note = f"{note} (see also: {nested_source})".strip()
    condition = str(rule.get("condition", "") or "")

    out: list[Entry] = []
    for term in terms:
        term = str(term).strip().lower()
        # retext's own engine supports a `*` wildcard token mid-phrase (e.g. slogans.yml's
        # "make * great again"); we do literal substring/word-boundary matching, so a term
        # containing one can't be turned into a real match -- skip rather than fabricate a match.
        if not term or "*" in term:
            continue
        out.append({
            "term": term,
            "category": category,
            "alternatives": list(alternatives),
            "note": note,
            "condition": condition,
            "source": f"retext-equality/data/en/{filename}.yml {source_tag}",
        })
    return out


def fetch_retext_equality(cache_dir: Path, offline: bool) -> list[Entry]:
    out_dir = cache_dir / "retext-equality"
    sha_file = out_dir / "COMMIT_SHA.txt"
    if offline:
        sha = sha_file.read_text(encoding="utf-8").strip()
    else:
        sha = json.loads(_http_get(f"{RETEXT_REPO_API}/commits/main"))["sha"]
        out_dir.mkdir(parents=True, exist_ok=True)
        sha_file.write_text(sha, encoding="utf-8")
    source_tag = f"@ {sha[:12]} (MIT)"

    entries: list[Entry] = []
    for name, category in RETEXT_FILE_CATEGORY.items():
        path = out_dir / f"{name}.yml"
        if offline:
            text = path.read_text(encoding="utf-8")
        else:
            text = _http_get(RETEXT_RAW_TMPL.format(sha=sha, name=name)).decode("utf-8")
            out_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        rules = yaml.safe_load(text) or []
        for rule in rules:
            entries.extend(_retext_rule_to_entries(rule, category, name, source_tag))
    return entries


# ---------------------------------------------------------------------------
# 2. Inclusive Naming Initiative
# ---------------------------------------------------------------------------

INI_INDEX_URL = "https://inclusivenaming.org/word-lists/index.json"
# A handful of INI slugs bundle two literal words or use a URL-safe hyphen where
# real prose uses a space; everything else is used as-is (e.g. "man-hour" really is
# written with a hyphen).
INI_TERM_OVERRIDES = {
    "blackhat-whitehat": ["blackhat", "whitehat"],
    "master-slave": ["master/slave", "master-slave"],
    "sanity-check": ["sanity check"],
}
# retext-equality's race.yml already flags "master"/"masters" for the same computing
# sense; sanity-check and cripple read more as ableist than a bare "exclusionary" bucket.
INI_CATEGORY_OVERRIDE = {
    "sanity-check": "ableist",
    "cripple": "ableist",
}


def fetch_ini(cache_dir: Path, offline: bool) -> list[Entry]:
    path = cache_dir / "inclusive-naming-initiative" / "index.json"
    if offline:
        text = path.read_text(encoding="utf-8")
    else:
        text = _http_get(INI_INDEX_URL).decode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    rows = json.loads(text)["data"]

    entries: list[Entry] = []
    for row in rows:
        tier = str(row.get("tier", "0"))
        if tier == "0":
            continue  # INI's own "no change recommended" bucket -- not a term to flag
        slug = str(row["term"]).strip().lower()
        if not slug:
            continue
        raw_alts = [
            a.strip() for a in row.get("recommended_replacements", [])
            if a and a.strip().lower() != "none"
        ]
        # A few "replacements" are prose guidance, not real replacement words
        # (e.g. totem-pole's "Do not use in phrases such as..."); keep only short,
        # word-like entries as alternatives and fold anything else into the note.
        alternatives = [
            a.replace("*", "") for a in raw_alts
            if len(a) <= 60 and not a.lower().startswith(("do not", "consider", "use with"))
        ]
        note = str(row.get("recommendation", "") or "")
        if not alternatives and raw_alts:
            note = f"{note} Guidance: {'; '.join(raw_alts)}".strip()
        category = INI_CATEGORY_OVERRIDE.get(slug, "exclusionary")
        term_page = row.get("term_page", INI_INDEX_URL)
        for term in INI_TERM_OVERRIDES.get(slug, [slug]):
            entries.append({
                "term": term,
                "category": category,
                "alternatives": list(alternatives),
                "note": note,
                "condition": "",
                "source": f"Inclusive Naming Initiative (CC-BY) {term_page}",
            })
    return entries


# ---------------------------------------------------------------------------
# 3. Tiny Heap / marionbartl/affixed_words gendered-occupation pairs
# ---------------------------------------------------------------------------

# Cited by our Assignment 2 as "Tiny Heap"; the actual upstream repo is
# marionbartl/affixed_words. "words/replacements+plural-final.csv" is the repo's own
# "Final List" -- the output of its round 1-4 extraction/verification/replacement
# pipeline (see the repo README).
AFFIXED_WORDS_URL = (
    "https://raw.githubusercontent.com/marionbartl/affixed_words/main/"
    "words/replacements+plural-final.csv"
)
AFFIXED_WORDS_SOURCE = (
    "Tiny Heap / marionbartl/affixed_words (CC0) words/replacements+plural-final.csv"
)


def fetch_occupations(cache_dir: Path, offline: bool) -> list[Entry]:
    path = cache_dir / "affixed_words" / "replacements_plural_final.csv"
    if offline:
        text = path.read_text(encoding="utf-8")
    else:
        text = _http_get(AFFIXED_WORDS_URL).decode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    entries: list[Entry] = []
    for row in csv.DictReader(io.StringIO(text)):
        term = row["word"].strip().lower()
        if not term:
            continue
        replacement = row["replacement"].strip()
        entries.append({
            "term": term,
            "category": "gendered",
            "alternatives": [replacement] if replacement else [],
            "note": f"gender-marked {row['affix_type']} (affix group: {row['category']})",
            "condition": "",
            "source": AFFIXED_WORDS_SOURCE,
        })
    return entries


# ---------------------------------------------------------------------------
# 4. Hand-curated CSVs (APA / NCDJ / GLAAD)
# ---------------------------------------------------------------------------

def load_curated_csv(path: Path) -> list[Entry]:
    entries: list[Entry] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            term = row["term"].strip().lower()
            if not term:
                continue
            alt_field = row.get("alternatives", "") or ""
            alternatives = [a.strip() for a in alt_field.split("|") if a.strip()]
            entries.append({
                "term": term,
                "category": row["category"].strip(),
                "alternatives": alternatives,
                "note": (row.get("note") or "").strip(),
                "condition": (row.get("condition") or "").strip(),
                "source": (row.get("source_url") or "").strip(),
            })
    return entries


# ---------------------------------------------------------------------------
# 5. Legacy v1 lexicon (safety net)
# ---------------------------------------------------------------------------

# Pre-v2 category names that don't match the 7 PRD categories.
LEGACY_CATEGORY_MAP = {
    "culturally-insensitive": "potentially-offensive",
    "ableist-loaded": "ableist",
}


def load_legacy(path: Path) -> list[Entry]:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries: list[Entry] = []
    for e in data["entries"]:
        category = e["category"]
        condition = ""
        if category == "ableist-loaded":
            condition = "when used colloquially/metaphorically, not to describe a disability"
        category = LEGACY_CATEGORY_MAP.get(category, category)
        entries.append({
            "term": e["term"].strip().lower(),
            "category": category,
            "alternatives": list(e.get("alternatives", [])),
            "note": e.get("note", ""),
            "condition": condition,
            "source": "inclusify-audit-agent v1 bundled lexicon (legacy, pre-R2)",
        })
    return entries


# ---------------------------------------------------------------------------
# Merge (pure -- no I/O; this is what the determinism test exercises directly)
# ---------------------------------------------------------------------------

def merge_entries(*sources: list[Entry]) -> list[Entry]:
    """Dedupe by lowercased term across ordered sources.

    First-listed source wins category + alternatives on collision; notes and
    conditions from later sources are appended rather than dropped. Pure and
    order-preserving, so calling it twice on the same inputs yields identical output.
    """
    merged: dict[str, Entry] = {}
    order: list[str] = []
    for source_list in sources:
        for raw in source_list:
            term = raw["term"].strip().lower()
            if not term:
                continue
            if term not in merged:
                merged[term] = dict(raw, term=term, alternatives=list(raw["alternatives"]))
                order.append(term)
                continue
            existing = merged[term]
            if not existing["alternatives"] and raw["alternatives"]:
                existing["alternatives"] = list(raw["alternatives"])
            for field in ("note", "condition"):
                addition = raw.get(field) or ""
                if addition and addition not in (existing.get(field) or ""):
                    if existing.get(field):
                        existing[field] = f"{existing[field]}; {addition}"
                    else:
                        existing[field] = addition
    return [merged[t] for t in order]


def _serialize(e: Entry) -> Entry:
    out: Entry = {
        "term": e["term"], "category": e["category"], "alternatives": list(e["alternatives"]),
    }
    if e.get("note"):
        out["note"] = e["note"]
    if e.get("condition"):
        out["condition"] = e["condition"]
    out["source"] = e.get("source", "")
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def build(cache_dir: Path, offline: bool) -> tuple[list[Entry], dict[str, int]]:
    retext = fetch_retext_equality(cache_dir, offline)
    ini = fetch_ini(cache_dir, offline)
    occupations = fetch_occupations(cache_dir, offline)
    curated_apa = load_curated_csv(LEXICON_DIR / "curated_apa.csv")
    curated_ncdj = load_curated_csv(LEXICON_DIR / "curated_ncdj.csv")
    curated_glaad = load_curated_csv(LEXICON_DIR / "curated_glaad.csv")
    legacy = load_legacy(LEGACY_SNAPSHOT_JSON)

    raw_counts = {
        "retext-equality": len(retext),
        "inclusive-naming-initiative": len(ini),
        "tiny-heap-occupations": len(occupations),
        "curated-apa": len(curated_apa),
        "curated-ncdj": len(curated_ncdj),
        "curated-glaad": len(curated_glaad),
        "legacy-v1": len(legacy),
    }

    merged = merge_entries(
        retext, ini, occupations, curated_apa, curated_ncdj, curated_glaad, legacy,
    )

    for e in merged:
        assert e["category"] in ALLOWED_CATEGORIES, f"{e['term']!r}: bad category {e['category']!r}"
        assert e["term"], "empty term slipped through"
        assert e["alternatives"] or e["note"] or e["condition"], (
            f"{e['term']!r} has no alternatives, note, or condition -- schema requires one"
        )

    return merged, raw_counts


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--offline-cache", type=Path, default=None,
        help="Read previously-cached raw source files from this dir instead of the network.",
    )
    args = parser.parse_args()

    cache_dir = args.offline_cache if args.offline_cache is not None else (LEXICON_DIR / "cache")
    offline = args.offline_cache is not None

    merged, raw_counts = build(cache_dir, offline)

    payload = {
        "_source": (
            "Sourced v2 lexicon build (scripts/build_lexicon.py) -- retext-equality (MIT) + "
            "Inclusive Naming Initiative (CC-BY) + Tiny Heap/affixed_words (CC0) + curated "
            "APA/NCDJ/GLAAD CSVs + legacy v1 terms. Full provenance: data/lexicon/README.md."
        ),
        "_format": {
            "term": "the surface form to flag (case-insensitive, word-boundary matched)",
            "category": "one of: gendered | exclusionary | ableist | outdated | "
                         "factually-incorrect | potentially-offensive | biased",
            "alternatives": "list of inclusive replacements (empty ok if note/condition explains)",
            "note": "optional context for the rewrite",
            "condition": "optional: when this rule applies (e.g. 'when referring to a person')",
            "source": "provenance for this entry",
        },
        "entries": [_serialize(e) for e in merged],
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    by_category: dict[str, int] = {}
    for e in merged:
        by_category[e["category"]] = by_category.get(e["category"], 0) + 1

    print(f"Wrote {len(merged)} entries to {OUT_JSON.relative_to(REPO_ROOT)}")
    print("\nRaw (pre-merge) counts by source:")
    for name, count in raw_counts.items():
        print(f"  {name:30s} {count}")
    print(f"\nFinal merged/deduped total: {len(merged)}")
    print("\nBy category:")
    for cat, count in sorted(by_category.items(), key=lambda kv: -kv[1]):
        print(f"  {cat:24s} {count}")


if __name__ == "__main__":
    main()
