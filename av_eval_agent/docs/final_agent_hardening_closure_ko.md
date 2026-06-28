# Final Hardening Log

## Completed

| Item | File |
|---|---|
| async long-run route | `app/main.py` |
| sync execution guard | `app/main.py` |
| knowledge pack endpoint | `app/main.py` |
| retry/backoff helper | n8n workflow JSON |
| token gate | n8n workflow JSON |
| reproducibility metadata | `autotune_agent.py` |
| eval runner | `evals/run_agent_evals.py` |
| API smoke script | `scripts/test_agent_api.ps1` |

## Workflow Files

| File | Purpose |
|---|---|
| `n8n/av_eval_agent_workflow.template.json` | editable workflow |
| `n8n/av_eval_agent_workflow.submission_sanitized.json` | submission/demo workflow |
| `n8n/av_eval_agent_async_submit.workflow.json` | long-run submit workflow |

## Local Verification

```text
date: 2026-06-29
python compile: pass
evals: 20 pass / 0 partial / 0 fail
FastAPI health: ok
API dry-run: pass
```

## Expected API Values

| Check | Value |
|---|---|
| `/health.status` | `ok` |
| `/health.service` | `av-evaluation-agent` |
| prepare status | `ready_for_execution` |
| dry-run status | `dry_run_prepared` |

## Limits

| Item | Status |
|---|---|
| CARLA runtime | external |
| OpenCDA checkout | external |
| heavy assets | not included |
| actual simulator execution | environment dependent |

## Final State

| Area | Status |
|---|---|
| backend prototype | kept |
| dry-run verification | kept |
| eval verification | kept |
| n8n/MCP files | kept |
| full OpenCDA source | removed |
