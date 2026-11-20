#!/usr/bin/env bash
# Exit non-zero when the first non-empty line of a review file is exactly
# "## Review verdict: FAIL". Blank and whitespace-only lines do not count.
# Any other first line, including a FAIL that appears only later, exits 0.
set -euo pipefail

if [[ $# -ne 1 || ! -f "$1" ]]; then
  echo "verdict_gate: usage: verdict_gate.sh <review-file>" >&2
  exit 2
fi

first=""
while IFS= read -r line || [[ -n "$line" ]]; do
  if [[ -n "${line//[[:space:]]/}" ]]; then
    first="$line"
    break
  fi
done < "$1"

if [[ "$first" == "## Review verdict: FAIL" ]]; then
  echo "review check failed: first non-empty line is '## Review verdict: FAIL'"
  exit 1
fi
