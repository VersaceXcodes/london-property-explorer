#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL is required}"
: "${APP_READER_PASSWORD:?APP_READER_PASSWORD is required}"
OUTPUT_DIR="${1:-pipeline/output}"
TRANSACTIONS="$OUTPUT_DIR/transactions.csv"
DISTRICTS="$OUTPUT_DIR/districts.geojson"

test -f "$TRANSACTIONS" || { echo "missing $TRANSACTIONS" >&2; exit 2; }
test -f "$DISTRICTS" || { echo "missing $DISTRICTS" >&2; exit 2; }

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
"$PYTHON_BIN" scripts/load_database.py "$OUTPUT_DIR"
