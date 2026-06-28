# n8n Node Graph

## Workflow Files

| File | Use |
|---|---|
| `av_eval_agent_workflow.template.json` | editable base |
| `av_eval_agent_workflow.submission_sanitized.json` | review/demo workflow |
| `av_eval_agent_async_submit.workflow.json` | long-run submit workflow |

## Main Nodes

| Node | Endpoint |
|---|---|
| Webhook Start | `/webhook/av-eval-agent/start` |
| Start Run | `POST /run/start` |
| Prepare Run | `POST /run/prepare/{run_id}` |
| Execute Run | `POST /run/execute/{run_id}` |
| Status Check | `GET /run/status/{run_id}` |
| Result Fetch | `GET /run/result/{run_id}` |
| HITL Review | Slack or manual gate |

## Async Nodes

| Node | Endpoint |
|---|---|
| Async Submit | `POST /pipeline/submit` |
| Async Status | `GET /pipeline/status/{run_id}` |

## Local Backend

```powershell
powershell -ExecutionPolicy Bypass -File .\av_eval_agent\scripts\start_agent_server.ps1
Invoke-RestMethod http://127.0.0.1:8010/health
```

## Smoke Test

```powershell
powershell -ExecutionPolicy Bypass -File .\av_eval_agent\scripts\test_agent_api.ps1
```

## Console Fields

| Field | Meaning |
|---|---|
| `run_id` | run folder key |
| `status_url` | async status endpoint |
| `prepare_status` | plan generation status |
| `dry_run_status` | dry-run status |
| `execution_plan` | plan file path |
