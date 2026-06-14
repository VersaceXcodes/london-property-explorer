#!/usr/bin/env bash
set -euo pipefail

API_BASE_URL="${1:?usage: scripts/measure.sh https://api.example.com}"
BBOX="-0.22,51.45,-0.02,51.56"
RESULTS="${2:-evals/results/performance.tsv}"
mkdir -p "$(dirname "$RESULTS")"
printf 'endpoint\trun\ttime_total_s\tsize_bytes\n' >"$RESULTS"

measure() {
  local name="$1"
  local url="$2"
  local accept="$3"
  for run in 1 2 3 4 5; do
    local output
    output=$(curl --fail --silent --show-error --output /dev/null \
      --header "Accept: $accept" \
      --write-out '%{time_total} %{size_download}' \
      "$url")
    read -r time size <<<"$output"
    printf '%s\t%s\t%s\t%s\n' "$name" "$run" "$time" "$size" >>"$RESULTS"
  done
}

measure clusters "$API_BASE_URL/api/transactions?bbox=$BBOX&zoom=11" application/json
measure points_json "$API_BASE_URL/api/transactions?bbox=$BBOX&zoom=12" application/json
measure points_binary "$API_BASE_URL/api/transactions?bbox=$BBOX&zoom=12&format=bin" application/octet-stream
printf 'Measurements written to %s\n' "$RESULTS"
