# AV Evaluation Agent Package

## Components

| Path | Role |
|---|---|
| `app/` | FastAPI gateway, LangGraph graph, service layer |
| `docs/` | design and operation notes |
| `evals/` | fixed eval cases and runner |
| `examples/` | sample API payloads |
| `mcp/` | MCP stdio server |
| `n8n/` | workflow templates |
| `schemas/` | JSON schemas |
| `scripts/` | PowerShell helpers |

## Eval

```powershell
cd <repo-root>
python -m venv .\av_eval_agent\.venv
.\av_eval_agent\.venv\Scripts\python.exe -m pip install -r .\av_eval_agent\requirements.txt
powershell -ExecutionPolicy Bypass -File .\av_eval_agent\scripts\run_agent_evals.ps1 --fail-on-fail
```

Expected:

```text
total: 20
pass: 20
partial: 0
fail: 0
```

## API

```powershell
powershell -ExecutionPolicy Bypass -File .\av_eval_agent\scripts\start_agent_server.ps1
Invoke-RestMethod http://127.0.0.1:8010/health
powershell -ExecutionPolicy Bypass -File .\av_eval_agent\scripts\test_agent_api.ps1
```

## External Boundary

| Item | Status |
|---|---|
| scenario classification | local |
| scenario JSON/table generation | local |
| run manifest | local |
| OpenCDA command plan | local |
| KPI command plan | local |
| CARLA/OpenCDA runtime | external |
| heavy simulator assets | external |
