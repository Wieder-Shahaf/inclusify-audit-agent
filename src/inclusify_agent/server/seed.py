"""Tiny in-memory RAG seed for the offline API demo.

The default offline store is empty, so retrieve_citation returns nothing and every
flag is routed to ask_user (no rewrite). Seeding a handful of authoritative snippets
that mention the common trigger terms lets hash-embedding cosine clear the 0.3 floor,
so the offline /api/execute exercises the full pipeline incl. RewriteComposer.

ponytail: 6 canned snippets, not the 40MB ERIC corpus. Run `inclusify-agent.ingest`
for the real corpus; this is just enough to make the keyless demo show all modules.
"""
from __future__ import annotations

from typing import Any

# (id, text, source-url) — each snippet name-drops the terms it grounds.
SEEDS: list[tuple[str, str, str]] = [
    ("seed_gendered",
     "Gendered job titles such as 'chairman' exclude non-male readers. Inclusive style "
     "guides recommend gender-neutral alternatives like 'chairperson' or 'chair', and "
     "replacing generic 'he'/'his' with 'they'/'their'.",
     "https://www.apa.org/about/apa/equity-diversity-inclusion/language-guidelines"),
    ("seed_manpower",
     "Terms like 'manpower' and 'man-made' embed a male default. Recommended inclusive "
     "substitutions include 'workforce', 'staffing', 'labor', and 'human-made'.",
     "https://consciousstyleguide.com/gender-sex-sexuality/"),
    ("seed_exclusionary",
     "Technical metaphors such as 'blacklist'/'whitelist' and 'master'/'slave' carry "
     "exclusionary connotations. Inclusive replacements are 'blocklist'/'allowlist' and "
     "'primary'/'replica'.",
     "https://inclusivenaming.org/word-lists/tier-1/"),
    ("seed_freshmen",
     "'Freshmen' assumes a male norm for new students. Inclusive academic style prefers "
     "'first-year students' or 'first-years'.",
     "https://www.eric.ed.gov/?id=inclusive-academic-language"),
    ("seed_ableist",
     "Ableist language such as 'lame', 'crazy', or 'sanity check' should be replaced with "
     "specific, non-stigmatizing terms like 'flawed', 'surprising', or 'quick check'.",
     "https://ncdj.org/style-guide/"),
    ("seed_identity",
     "Outdated identity terminology — 'homosexuals' as a noun, 'transgendered', 'sexual "
     "preference' — should be updated to 'gay/lesbian people', 'transgender', and 'sexual "
     "orientation'.",
     "https://www.glaad.org/reference/terms"),
]


def seed_store(store: Any, embedder: Any) -> None:
    """Embed and upsert the canned snippets into an (empty) vector store."""
    ids = [s[0] for s in SEEDS]
    texts = [s[1] for s in SEEDS]
    metas = [{"url": s[2], "source": "seed"} for s in SEEDS]
    store.add(ids, embedder.embed(texts), texts, metas)
