# Claude Review workflow

## What it does

The **Claude Review** GitHub Action (`.github/workflows/claude-review.yml`) runs an automated code review using [Claude Code](https://code.claude.com/) in the context of this repository’s pull requests.

When it fires, the workflow:

1. Checks out the repository (full history).
2. Writes the PR diff to `/tmp/pr.diff` and title/body metadata to `/tmp/pr-meta.txt`.
3. Invokes `anthropics/claude-code-action@v1` with instructions from `.github/claude/review-prompt.md`.
4. The reviewer posts **one** comment on the PR starting with `## Review verdict: PASS` or `## Review verdict: FAIL`.

## Where it runs

The review job runs **only** on a **self-hosted** runner labeled `claude-review` in the owner’s cluster. It never runs on GitHub-hosted runners; no GitHub Actions metered minutes are consumed. GitHub remains the trigger and PR surface only.

## When it runs

The workflow triggers on `pull_request` events: `opened`, `synchronize`, and `reopened`.

It runs only when **both** of the following are true:

- The pull request’s **head branch** name starts with `cursor/` (job-level filter on `github.head_ref`).
- The repository variable `CLAUDE_REVIEW_ENABLED` is set to `true`.

If either condition fails, the job is **skipped** entirely (no queue, no runner time).

Concurrency is grouped per PR number; a newer run cancels an in-progress review for the same PR.

## Pipeline context

This Action replaces the previous Muse subagent reviewer for `cursor/*` implementation PRs. The pipeline is:

1. **Cursor agent** implements a spec (GB-xx) on a `cursor/` branch and opens a PR.
2. **Claude Review** (this workflow) verifies the PR against the spec’s stated acceptance criteria and repo artifacts.
3. On **PASS**, the **implementing agent** squash-merges (per orchestrator instructions). This workflow does not merge.

## Enabling the reviewer (owner)

Until **both** prerequisites below are in place, review jobs are skipped—nothing runs on a runner.

1. **Secret** — add repository Actions secret `CLAUDE_CODE_OAUTH_TOKEN` (subscription OAuth token from `claude setup-token`). This is the **same credential** already stored in the owner’s 1Password vault for the homeops cluster—not an Anthropic API key.
2. **Runner** — register a self-hosted runner on the owner’s cluster with labels `self-hosted` and `claude-review` (GitHub’s default `self-hosted` label plus the custom `claude-review` label required by the workflow).
3. **Variable** — in the repository, set Actions variable `CLAUDE_REVIEW_ENABLED` to `true` (Settings → Secrets and variables → Actions → Variables).

After all three are configured, eligible `cursor/*` PRs will schedule the review job on the cluster runner.

## No API key invariant

This setup intentionally uses **only** the Claude subscription OAuth token (`CLAUDE_CODE_OAUTH_TOKEN`). The workflow and docs do **not** use `ANTHROPIC_API_KEY`. That keeps billing and auth aligned with the owner’s Pro/Max subscription already used elsewhere (e.g. homeops).

## Disabling the reviewer

To turn off automated review without changing application code:

1. Set repository variable `CLAUDE_REVIEW_ENABLED` to `false`, or delete the variable. Review jobs are then skipped.
2. Or in GitHub: **Actions** → **Claude Review** → **⋯** → **Disable workflow**.

Or set the workflow file’s `on:` to a manual `workflow_dispatch` only in a future change. No other components need to be toggled for a temporary pause.

## Local sanity check

From the repo root:

```bash
bash scripts/check-claude-review.sh
```

This script asserts the workflow file, OAuth secret reference, branch filter, permissions block, self-hosted `runs-on`, enable gate variable, and review prompt are present and consistent.
