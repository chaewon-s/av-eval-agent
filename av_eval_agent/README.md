# AV Evaluation Agent Package

## Components

| Path | Role |
|---|---|
| `app/` | FastAPI gateway, LangGraph graph, service layer |
| `docs/` | architecture and operation notes |
| `evals/` | fixed eval cases and runner |
| `examples/` | sample request payloads |
| `mcp/` | MCP stdio server |
| `n8n/` | workflow templates |
| `schemas/` | JSON schemas |
| `scripts/` | source helper scripts |
| `deploy_scripts/` | deployment helper scripts |

## Install

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy_scripts\install_windows.ps1
```

## Run

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy_scripts\start_backend.ps1
powershell -ExecutionPolicy Bypass -File .\deploy_scripts\start_n8n_docker.ps1
powershell -ExecutionPolicy Bypass -File .\deploy_scripts\import_n8n_workflows.ps1
```

## Check

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy_scripts\check_health.ps1
```

## Sample Request

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy_scripts\run_sample_request.ps1 -Scenario scenario2
```

## Eval

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File .\scripts\run_agent_evals.ps1 --fail-on-fail
```

Expected:

```text
total: 20
pass: 20
partial: 0
fail: 0
```

## External Boundary

| Included | External |
|---|---|
| scenario classification | CARLA runtime |
| scenario JSON/table generation | OpenCDA checkout |
| run manifest | simulator assets |
| command plan | raw simulation dumps |
| KPI/report plan | long-running simulator worker |
