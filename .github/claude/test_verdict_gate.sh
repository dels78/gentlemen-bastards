#!/usr/bin/env bash
# Feed verdict_gate.sh a PASS sample, a FAIL sample, a FAIL sample with
# leading blank lines, and a sample where FAIL appears only later.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GATE="${ROOT}/.github/claude/verdict_gate.sh"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

failures=0

run_case() {
  local name="$1"
  local expect="$2"
  local file="$3"
  local output status lines

  set +e
  output="$(bash "$GATE" "$file" 2>&1)"
  status=$?
  set -e

  if [[ "$expect" -eq 0 ]]; then
    if [[ "$status" -eq 0 && -z "$output" ]]; then
      echo "PASS: $name"
    else
      echo "FAIL: $name (exit ${status}, output: ${output})"
      failures=$((failures + 1))
    fi
    return
  fi

  lines="$(printf '%s\n' "$output" | grep -c . || true)"
  if [[ "$status" -ne 0 && "$lines" -eq 1 ]]; then
    echo "PASS: $name"
    echo "  reason: ${output}"
  else
    echo "FAIL: $name (exit ${status}, lines ${lines}, output: ${output})"
    failures=$((failures + 1))
  fi
}

cat > "$tmp/pass.md" <<'EOF'
## Review verdict: PASS

Evidence: the change matches the spec.
EOF

cat > "$tmp/fail.md" <<'EOF'
## Review verdict: FAIL

Findings: blocker.
EOF

# Empty lines and one whitespace-only line before the verdict.
printf '\n\n \t\n\n## Review verdict: FAIL\n\nFindings: blocker.\n' > "$tmp/fail-leading-blank.md"

cat > "$tmp/fail-later.md" <<'EOF'
## Review verdict: PASS

The notes below mention a FAIL that is not the first line.
## Review verdict: FAIL
This later line must not fail the check.
EOF

run_case "PASS sample" 0 "$tmp/pass.md"
run_case "FAIL sample" 1 "$tmp/fail.md"
run_case "FAIL sample with leading blank lines" 1 "$tmp/fail-leading-blank.md"
run_case "FAIL only later in the text" 0 "$tmp/fail-later.md"

if [[ "$failures" -eq 0 ]]; then
  echo "All verdict gate cases passed."
  exit 0
fi
echo "${failures} case(s) failed."
exit 1
