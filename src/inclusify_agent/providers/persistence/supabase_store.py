"""Supabase-backed run logging (the course primary DB).

Lazy-imports the supabase client so the offline default never pulls it in. Insert
failures are swallowed (logging is best-effort, never breaks /api/execute).

Expected table (SQL):
    create table audit_runs (
        id bigint generated always as identity primary key,
        created_at timestamptz default now(),
        prompt text, status text, response text, step_count int, steps jsonb,
        tokens_in int, tokens_out int
    );
    -- tokens_in/tokens_out (course req #1c budget ledger): populated when the LLM
    -- provider exposes usage() (OpenAICompatLLM; MockLLM never does) -- omitted from
    -- the row entirely when None, so the columns can be added to an existing table
    -- at any time without a backfill.
    -- Supabase enables RLS by default; with the publishable (anon) key the
    -- insert needs a policy (insert-only is enough — we write returning=minimal):
    --   create policy "anon_insert_audit_runs" on audit_runs
    --       for insert to anon with check (true);
    --   (pending: this policy has not been added yet -- inserts 403 until it is;
    --   see docs/NEEDS_KEYS.md.)
"""
from __future__ import annotations

import sys
from typing import Any


class SupabasePersistence:
    name = "supabase"

    def __init__(self, url: str, key: str, table: str = "audit_runs") -> None:
        if not url or not key:
            raise ValueError("SupabasePersistence requires url and key")
        try:
            from supabase import create_client
        except ImportError as e:
            raise RuntimeError(
                "supabase not installed. Install with: pip install '.[live]'"
            ) from e
        self._client = create_client(url, key)
        self._table = table

    def log_run(
        self, *, prompt: str, status: str, response: str | None,
        steps: list[dict[str, Any]],
        tokens_in: int | None = None, tokens_out: int | None = None,
    ) -> None:
        try:
            row: dict[str, Any] = {
                "prompt": prompt,
                "status": status,
                "response": response,
                "step_count": len(steps),
                "steps": steps,
            }
            if tokens_in is not None:
                row["tokens_in"] = tokens_in
            if tokens_out is not None:
                row["tokens_out"] = tokens_out
            # returning="minimal": fire-and-forget write — also lets an
            # insert-only RLS policy suffice (no select needed on the row).
            self._client.table(self._table).insert(row, returning="minimal").execute()
        except Exception as e:  # best-effort; never break the response
            print(f"[supabase] log_run failed: {type(e).__name__}: {e}", file=sys.stderr)
