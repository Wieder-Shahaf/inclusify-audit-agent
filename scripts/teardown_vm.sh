#!/bin/sh
# Decommission the work-VM dev resources once we move to course resources.
# Deletes ONLY the Qdrant collections we created (scoped to QDRANT_COLLECTION or
# QDRANT_COLLECTION_PREFIX from .env) and wipes local temp artifacts.
#
# SAFETY: Qdrant may be shared infra. This script never deletes a collection that
# doesn't match our configured name/prefix, refuses to run if neither is set, and
# is DRY-RUN by default — pass --yes to actually delete.
#
# Usage:  scripts/teardown_vm.sh [--yes]
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV="$ROOT/.env"

CONFIRM=0
[ "${1:-}" = "--yes" ] && CONFIRM=1

# Load .env (KEY=VALUE lines) without executing it.
QDRANT_URL=""; QDRANT_API_KEY=""; QDRANT_COLLECTION=""; QDRANT_COLLECTION_PREFIX=""
if [ -f "$ENV" ]; then
  while IFS='=' read -r k v; do
    case "$k" in
      QDRANT_URL) QDRANT_URL=$v ;;
      QDRANT_API_KEY) QDRANT_API_KEY=$v ;;
      QDRANT_COLLECTION) QDRANT_COLLECTION=$v ;;
      QDRANT_COLLECTION_PREFIX) QDRANT_COLLECTION_PREFIX=$v ;;
    esac
  done < "$ENV"
fi

[ "$CONFIRM" -eq 1 ] && MODE="DELETE" || MODE="DRY-RUN (pass --yes to delete)"
echo "== teardown_vm.sh — $MODE =="

# ---- Remote: Qdrant collections -------------------------------------------------
if [ -z "$QDRANT_URL" ]; then
  echo "[qdrant] QDRANT_URL not set — skipping remote cleanup."
elif [ -z "$QDRANT_COLLECTION" ] && [ -z "$QDRANT_COLLECTION_PREFIX" ]; then
  echo "[qdrant] REFUSING: neither QDRANT_COLLECTION nor QDRANT_COLLECTION_PREFIX set." >&2
  echo "         Won't guess which collections are ours on shared infra. Set one in .env." >&2
  exit 2
else
  AUTH=""
  [ -n "$QDRANT_API_KEY" ] && AUTH="-H api-key:$QDRANT_API_KEY"
  # List collection names from the Qdrant REST API.
  names=$(curl -fsS $AUTH "$QDRANT_URL/collections" \
    | tr ',' '\n' | sed -n 's/.*"name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
  for n in $names; do
    match=0
    [ -n "$QDRANT_COLLECTION" ] && [ "$n" = "$QDRANT_COLLECTION" ] && match=1
    [ -n "$QDRANT_COLLECTION_PREFIX" ] && case "$n" in "$QDRANT_COLLECTION_PREFIX"*) match=1 ;; esac
    [ "$match" -eq 0 ] && continue
    if [ "$CONFIRM" -eq 1 ]; then
      curl -fsS $AUTH -X DELETE "$QDRANT_URL/collections/$n" >/dev/null && echo "[qdrant] deleted: $n"
    else
      echo "[qdrant] would delete: $n"
    fi
  done
fi

# ---- Local: temp artifacts (all gitignored, regenerable) ------------------------
for p in .chroma qdrant_storage traces logs .cache tests/cassettes; do
  t="$ROOT/$p"
  [ -e "$t" ] || continue
  if [ "$CONFIRM" -eq 1 ]; then
    rm -rf "$t" && echo "[local] removed: $p"
  else
    echo "[local] would remove: $p"
  fi
done

echo "== done =="
