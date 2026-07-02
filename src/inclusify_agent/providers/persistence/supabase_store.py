"""Supabase-backed run logging (the course primary DB).

Lazy-imports the supabase client so the offline default never pulls it in. Insert
failures are swallowed (logging is best-effort, never breaks /api/execute).

Expected table (SQL):
    create table audit_runs (
        id bigint generated always as identity primary key,
        created_at timestamptz default now(),
        prompt text, status text, response text, step_count int, steps jsonb
    );
    -- Supabase enables RLS by default; with the publishable (anon) key the
    -- insert needs a policy (insert-only is enough — we write returning=minimal):
    --   create policy "anon_insert_audit_runs" on audit_runs
    --       for insert to anon with check (true);
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
    ) -> None:
        try:
            # returning="minimal": fire-and-forget write — also lets an
            # insert-only RLS policy suffice (no select needed on the row).
            self._client.table(self._table).insert({
                "prompt": prompt,
                "status": status,
                "response": response,
                "step_count": len(steps),
                "steps": steps,
            }, returning="minimal").execute()
        except Exception as e:  # best-effort; never break the response
            print(f"[supabase] log_run failed: {type(e).__name__}: {e}", file=sys.stderr)
