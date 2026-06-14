#!/usr/bin/env bash
set -euo pipefail

API_BASE_URL="${1:?usage: scripts/smoke.sh https://api.example.com}"

curl --fail --silent --show-error --max-time 10 "$API_BASE_URL/api/health" | grep -q '"status":"ok"'
curl --fail --silent --show-error --max-time 10 "$API_BASE_URL/api/capabilities" | python3 -m json.tool >/dev/null
curl --fail --silent --show-error --max-time 15 "$API_BASE_URL/api/meta" | python3 -m json.tool >/dev/null

printf 'Smoke checks passed for %s\n' "$API_BASE_URL"

