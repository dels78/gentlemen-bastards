#!/usr/bin/env bash
# Assert Claude Review workflow and prompt meet GB-03 invariants.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKFLOW="${REPO_ROOT}/.github/workflows/claude-review.yml"
PROMPT="${REPO_ROOT}/.github/claude/review-prompt.md"

failures=0

assert() {
  local name="$1"
  local ok="$2"
  if [[ "$ok" == "1" ]]; then
    echo "PASS: $name"
  else
    echo "FAIL: $name"
    failures=$((failures + 1))
  fi
}

[[ -f "$WORKFLOW" ]] && ok_wf=1 || ok_wf=0
assert "workflow file exists" "$ok_wf"

if [[ -f "$WORKFLOW" ]]; then
  content="$(cat "$WORKFLOW")"
  grep -q 'secrets\.CLAUDE_CODE_OAUTH_TOKEN' <<<"$content" && ok_oauth=1 || ok_oauth=0
  assert "workflow references secrets.CLAUDE_CODE_OAUTH_TOKEN" "$ok_oauth"

  grep -q 'ANTHROPIC_API_KEY' <<<"$content" && ok_no_api=0 || ok_no_api=1
  assert "workflow does NOT contain ANTHROPIC_API_KEY" "$ok_no_api"

  grep -q "cursor/" <<<"$content" && ok_cursor=1 || ok_cursor=0
  assert "workflow contains cursor/ branch filter" "$ok_cursor"

  grep -q '^permissions:' <<<"$content" && ok_perm=1 || ok_perm=0
  assert "workflow declares permissions: block" "$ok_perm"
fi

[[ -f "$PROMPT" ]] && ok_prompt_file=1 || ok_prompt_file=0
assert "review prompt file exists" "$ok_prompt_file"

if [[ -f "$PROMPT" ]]; then
  grep -q 'Review verdict' <<<"$(cat "$PROMPT")" && ok_verdict=1 || ok_verdict=0
  assert "review prompt contains Review verdict" "$ok_verdict"
fi

if [[ "$failures" -eq 0 ]]; then
  echo "All assertions passed."
  exit 0
else
  echo "$failures assertion(s) failed."
  exit 1
fi
