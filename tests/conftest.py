"""Pin offline providers for the suite, regardless of the host shell's env.

The server builds its vector store from config; without this, a machine with a
live .env exported would run the offline suite against real providers.
"""
from __future__ import annotations

import os

os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("EMBEDDINGS_PROVIDER", "hash")
os.environ.setdefault("VECTOR_STORE", "inmemory")
