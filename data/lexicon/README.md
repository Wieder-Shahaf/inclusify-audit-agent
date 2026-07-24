# data/lexicon/

The bundled lexicon ships **inside the Python package** at
`src/inclusify_agent/data/inclusive_lexicon.json` so `pip install` carries it. This
directory holds the *inputs* that build it, plus provenance.

Pass an absolute path to `load_lexicon(path=...)` / `scan_document(text, lexicon_path=...)`
to use a different lexicon file (used by tests with custom fixtures).

## Regenerating the lexicon

```
python scripts/build_lexicon.py                       # fetches all sources live, caches raw copies
python scripts/build_lexicon.py --offline-cache data/lexicon/cache/   # rebuild from the cache, no network
```

Both modes produce byte-identical output (verified 2026-07-24) given the same cache
contents. `data/lexicon/cache/` is gitignored — it's a reproducibility convenience
(and records the exact retext-equality commit sha), not a source of truth; the true
provenance is the table below plus the `source` field on every entry in the built JSON.

## Provenance (built 2026-07-24, `scripts/build_lexicon.py`)

| Source | License | What it is | Raw terms fetched | Final entries (post-dedup) |
|---|---|---|---:|---:|
| [retext-equality](https://github.com/retextjs/retext-equality) `data/en/*.yml` @ commit [`192deddf`](https://github.com/retextjs/retext-equality/commit/192deddf13bc2823540b0d9a0a6e17fb6d995bcd) | MIT | 9 YAML rule files (gender, ablist, lgbtq, race, condescending, suicide, misc, press, slogans) | 906 | 906 |
| [Inclusive Naming Initiative](https://inclusivenaming.org/word-lists/) word-list index (tiers 1-3 only; tier 0 "no change" excluded) | CC-BY | Tech/CS terms (master/slave, whitelist, sanity check, grandfathered, hallucinate...) | 19 | 11 |
| [Tiny Heap / marionbartl/affixed_words](https://github.com/marionbartl/affixed_words) `words/replacements+plural-final.csv` ("Final List") | CC0 | Gendered-occupation affix pairs (`-man/-men/-woman/-boy/-girl` forms) | 692 | 575 |
| Curated: [APA bias-free language guidelines](https://apastyle.apa.org/style-grammar-guidelines/bias-free-language) (`gender`, `disability` sub-pages, fetched via Wayback Machine snapshots — the live site sits behind bot-protection that blocks a plain `curl`) | cite-and-curate (fair-use excerpting; not redistributing the guide itself) | Gendered occupational titles, "opposite sex" framing, disability person-first phrasing | 20 | 13 |
| Curated: [NCDJ Disability Language Style Guide](https://ncdj.org/style-guide/) | cite-and-curate | ~40 disability-language terms with NCDJ's own recommendation | 43 | 21 |
| Curated: [GLAAD Media Reference Guide](https://www.glaad.org/reference/terms) ("Terms" + "Trans Terms" pages, fetched via Wayback Machine snapshots — same bot-protection issue) | cite-and-curate | LGBTQ terminology, "Terms to Avoid" / "Best Practice" pairs | 35 | 13 |
| Legacy v1 lexicon (`data/lexicon/legacy_v1_lexicon.json`, frozen snapshot of the pre-R2 bundled 44 terms) | n/a (project-authored) | Safety net so no pre-R2 term is lost even where no external source happens to also cover it | 44 | 8 |
| **Total** | | | **1,759** | **1,547** |

`legacy_v1_lexicon.json` is a permanent, checked-in snapshot (not the build output —
`build_lexicon.py` reads it as one more merge input, never from its own regenerated
output, so reruns stay stable). The 8 legacy terms that needed the safety net (i.e.
no 2026 external source happened to also cover them) are the idiom-like phrases:
`man-hours`, `low man on the totem pole`, `spirit animal`, `pow-wow`, `indian giver`,
`gypped`, `third-world`, `exotic`.

**Merge precedence on term collision** (case-insensitive; first-listed source wins
category + alternatives, notes/conditions from later sources are appended, never
dropped): `retext-equality > Inclusive Naming Initiative > Tiny Heap occupations >
curated APA/NCDJ/GLAAD > legacy v1`.

**retext-equality file → lexicon category map** (documented in `scripts/build_lexicon.py`'s
docstring too):

| retext-equality file | lexicon category |
|---|---|
| `gender.yml` | `gendered` |
| `ablist.yml` | `ableist` |
| `lgbtq.yml` | `outdated` |
| `race.yml` | `potentially-offensive` |
| `condescending.yml` | `potentially-offensive` |
| `suicide.yml` | `potentially-offensive` |
| `misc.yml` | `exclusionary` |
| `press.yml` | `biased` |
| `slogans.yml` | `biased` |

Legacy category remap: `culturally-insensitive → potentially-offensive`,
`ableist-loaded → ableist` (with a `condition` noting the colloquial/metaphorical use).

**Final entries by category:** gendered 1135 · ableist 226 · potentially-offensive 113 ·
outdated 54 · exclusionary 13 · biased 6 · factually-incorrect 0 (this category is
inherently a sentence-level judgment call — see `classify_span.py`'s prompt — not a
lexicon trigger word; no source here produces one, honestly).

## Files in this directory

- `curated_apa.csv`, `curated_ncdj.csv`, `curated_glaad.csv` — hand-curated, columns
  `term,category,alternatives|pipe-separated,note,condition,source_url`. Every row was
  read directly off the cited page; alternatives are the page's own recommended
  replacement(s). Rows with no direct replacement (e.g. reclaimed slurs the source
  says only to avoid) leave `alternatives` empty and explain why in `note`/`condition`.
- `legacy_v1_lexicon.json` — frozen snapshot of the pre-R2 44-term bundled lexicon.
- `cache/` — gitignored raw-fetch cache for `--offline-cache` reruns.
