# PERSO-816: Herald `loop_health.py` execution

Linear **PERSO-816** adds `dist/herald/scripts/loop_health.py`, run deterministically before Herald composes a digest (see `bots/herald/INSTRUCTIONS.md`).

## How Hermes runs it (same as `gate.py`)

1. Hermes lays `dist/herald/scripts/*` into the Herald profile home as `<home>/scripts/`.
2. Before a Herald model run, INSTRUCTIONS require `python3 scripts/loop_health.py` from that home (cron gate uses the same pattern for `scripts/gate.py`).
3. `loop_health.py` imports `McpClient`, `load_token`, and `extract_items` from sibling `scripts/gate.py` — the same stdlib streamable-HTTP client the wake gate uses.

## Token and MCP endpoint

| Item | Value |
|------|--------|
| Profile home directory name | `herald` (derived from dist layout) |
| Token env var | `MCP_SERVICE_TOKEN_HERALD` in `<home>/.env` |
| MCP URL | `http://personal-mcp.personal-mcp.svc.cluster.local:80/mcp` (constant in `gate.py`; matches `dist/herald/config.yaml` `mcp_servers.personal-mcp.url`) |
| Auth header | `Authorization: Bearer ${MCP_SERVICE_TOKEN_HERALD}` (config.yaml; gate.py reads the resolved value from `.env`) |

## personal-mcp scope (herald subject)

From `dels78/personal-mcp` → `src/auth/tool_scopes.json`, subject `herald` has `group:artifacts` and `group:runs`, which include `artifacts_list` and `runs_list`. The store does not restrict `unprocessed_for` to the caller's role — Herald may query `unprocessed_for: coordinator`.

## Tool calls issued

```text
artifacts_list(type="question", unprocessed_for="coordinator", limit=500)
runs_list(role="coordinator", limit=500, since=<oldest_question_created_at − 2h>)
```

`runs_list` in personal-mcp sorts by `started_at` ascending and returns the oldest *N* rows (`list_runs` in `src/tools/artifacts.py`). Without `since`, a `limit` of 100 only sees ancient Coordinator runs. `loop_health.py` passes `since` from the oldest waiting Question (minus two hours) so recent finishes stay in the window.

Payload shapes match `ArtifactStore.list_artifacts` / `list_runs` in personal-mcp `src/tools/artifacts.py` (see `generator/fixtures/personal_mcp_perso816_payloads.json` and `generator/test_personal_mcp_payload_contract.py`).

## Dry-run in repo

Unit tests execute the **rendered** `dist/herald/scripts/loop_health.py` with a fake `McpClient` that records tool names and arguments (no cluster required). `bots/validate.py` checks Herald's rendered `config.yaml` includes both tools.