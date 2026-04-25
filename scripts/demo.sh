#!/usr/bin/env bash
# End-to-end demo: index a repo, make a change, run blast-radius
# Usage: ./scripts/demo.sh /path/to/target/repo
# TODO: Phase 7 — flesh out demo script
set -euo pipefail

REPO="${1:?Usage: $0 /path/to/target/repo}"

echo "==> Indexing $REPO with CodeGraphContext..."
cgc index "$REPO"

echo "==> Running blast-radius pipeline (dry run)..."
python -m blast_radius "$REPO" --dry-run

echo "==> Done. Run without --dry-run to synthesize and execute tests."
