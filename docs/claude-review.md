# Claude Review workflow

## What it does

The **Claude Review** GitHub Action (`.github/workflows/claude-review.yml`) runs an automated code review using [Claude Code](https://code.claude.com/) in the context of this repository’s pull requests.

When it fires, the workflow:

1. Checks out the repository (full history).
2. Writes the PR diff to `/tmp/pr.diff` and title/body metadata to `/tmp/pr-meta.txt`.
3. Invokes `anthropics/claude-code-action@v1` with instructions from `.github/claude/review-prompt.md`.
4. The reviewer posts **one** comment on the PR starting with `## Review verdict: PASS` or `## Review verdict: FAIL`.

## When it runs

The workflow triggers on `pull_request` events: `opened`, `synchronize`, and `reopened`.

It runs only when the pull request’s **head branch** name starts with `cursor/` (job-level filter on `github.head_ref`). Other branches do not run this reviewer.

Concurrency is grouped per PR number; a newer run cancels an in-progress review for the same PR.

## Pipeline context

This Action replaces the previous Muse subagent reviewer for `cursor/*` implementation PRs. The pipeline is:

1. **Cursor agent** implements a spec (GB-xx) on a `cursor/` branch and opens a PR.
2. **Claude Review** (this workflow) verifies the PR against the spec’s stated acceptance criteria and repo artifacts.
3. On **PASS**, the **implementing agent** squash-merges (per orchestrator instructions). This workflow does not merge.

## One-time owner setup

Add a repository Actions secret:

| Name | Value |
|------|--------|
| `CLAUDE_CODE_OAUTH_TOKEN` | Subscription OAuth token from `claude setup-token` |

This is the **same credential** already stored in the owner’s 1Password vault for the homeops cluster—not an Anthropic API key.

Until the secret exists, workflow runs that reach the Claude step will **fail at authentication**. That red X is **expected**, not an incident: the workflow is wired correctly but cannot authenticate.

## No API key invariant

This setup intentionally uses **only** the Claude subscription OAuth token (`CLAUDE_CODE_OAUTH_TOKEN`). The workflow and docs do **not** use `ANTHROPIC_API_KEY`. That keeps billing and auth aligned with the owner’s Pro/Max subscription already used elsewhere (e.g. homeops).

## Disabling the reviewer

To turn off automated review without changing application code:

1. In GitHub: **Actions** → **Claude Review** → **⋯** → **Disable workflow**.

Or set the workflow file’s `on:` to a manual `workflow_dispatch` only in a future change. No other components need to be toggled for a temporary pause.

## Local sanity check

From the repo root:

```bash
bash scripts/check-claude-review.sh
```

This script asserts the workflow file, OAuth secret reference, branch filter, permissions block, and review prompt are present and consistent.
