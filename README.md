# AV Evaluation Agent

## Files

| Path | Contents |
|---|---|
| `av_eval_agent/app/` | FastAPI backend, LangGraph flow, service modules |
| `av_eval_agent/evals/` | 20 deterministic eval cases |
| `av_eval_agent/examples/` | API request samples |
| `av_eval_agent/mcp/` | local MCP tool server |
| `av_eval_agent/n8n/` | n8n workflow JSON |
| `av_eval_agent/schemas/` | scenario, manifest, KPI schemas |
| `av_eval_agent/scripts/` | Windows verification scripts |
| `av_eval_agent/docs/` | architecture and operation notes |

## Verify

```powershell
cd av-eval-agent
python -m venv .\av_eval_agent\.venv
.\av_eval_agent\.venv\Scripts\python.exe -m pip install -r .\av_eval_agent\requirements.txt
powershell -ExecutionPolicy Bypass -File .\av_eval_agent\scripts\run_agent_evals.ps1 --fail-on-fail
```

Expected:

```text
AV Evaluation Agent eval summary
- total: 20
- pass: 20
- partial: 0
- fail: 0
```

Local report:

```text
av_eval_agent/data/eval_reports/last_agent_eval_report.json
```

## API Dry-Run

```powershell
powershell -ExecutionPolicy Bypass -File .\av_eval_agent\scripts\start_agent_server.ps1
Invoke-RestMethod http://127.0.0.1:8010/health
powershell -ExecutionPolicy Bypass -File .\av_eval_agent\scripts\test_agent_api.ps1
```

Expected smoke-test fields:

```text
prepare_status: ready_for_execution
dry_run_status: dry_run_prepared
```

Stop server:

```powershell
powershell -ExecutionPolicy Bypass -File .\av_eval_agent\scripts\stop_agent_server.ps1
```

## Last Checked

```text
date: 2026-06-29
python compile: pass
evals: 20 pass / 0 partial / 0 fail
health: status ok, service av-evaluation-agent
api dry-run: pass
```

## Scope

Included:

- AV Evaluation Agent backend
- scenario definition flow
- dry-run execution planning
- KPI planning hooks
- eval runner
- MCP and n8n integration files

Excluded:

- full OpenCDA source tree
- CARLA runtime assets
- raw simulation dumps
- generated dashboards/reports
- model weights and videos
- local virtual environments

External simulator execution needs a separate OpenCDA/CARLA checkout.
