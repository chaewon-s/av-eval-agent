# AV Evaluation AI Agent Package

`av_eval_agent`는 자연어 자율주행 평가 요청을 구조화된 시나리오 정의, 실행 계획, KPI 계획, 검증 가능한 산출물로 바꾸는 Agent prototype이다.

이 패키지는 전체 OpenCDA/CARLA 프로젝트가 아니라 **Agent 설계와 dry-run 검증에 필요한 최소 실행 단위**만 포함한다.

## Components

| Path | Role |
|---|---|
| `app/` | FastAPI gateway, LangGraph Agent, planner/validator/service modules |
| `docs/` | Agent architecture and operating documents |
| `evals/` | deterministic eval cases and runner |
| `examples/` | sample natural-language API requests |
| `mcp/` | local MCP tool server prototype |
| `n8n/` | n8n workflow JSON templates |
| `schemas/` | JSON schemas for run artifacts |
| `scripts/` | PowerShell helpers for eval/API smoke tests |

## Verify Without CARLA

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

## Start API

```powershell
powershell -ExecutionPolicy Bypass -File .\av_eval_agent\scripts\start_agent_server.ps1
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8010/health
```

Dry-run API test:

```powershell
powershell -ExecutionPolicy Bypass -File .\av_eval_agent\scripts\test_agent_api.ps1
```

The API smoke test does not run CARLA. It verifies Agent planning, run artifact creation, command planning, and dry-run behavior.

## External Simulator Boundary

Actual CARLA/OpenCDA execution requires an external simulator environment. In this trimmed repo:

- scenario classification and definition generation are fully testable
- OpenCDA command plans are generated
- missing external OpenCDA targets are recorded in `execution_plan.json`
- KPI plans are generated and can skip missing external KPI scripts safely

This lets reviewers confirm the Agent architecture and control flow without downloading heavy simulator assets.
