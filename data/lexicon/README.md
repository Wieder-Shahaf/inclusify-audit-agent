# data/lexicon/

The actual bundled lexicon ships **inside the Python package** at
`src/inclusify_agent/data/inclusive_lexicon.json` so `pip install` carries it.

This directory remains for future user-supplied lexicon overrides; pass an
absolute path to `load_lexicon(path=...)` to use one.
