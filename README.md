# AV Evaluation Agent

Natural-language-to-evaluation workflow design for autonomous vehicle scenario testing.

This repository is intentionally trimmed to the **AV Evaluation Agent** only. It no longer contains the full OpenCDA source tree, CARLA assets, raw simulation dumps, model weights, or generated experiment outputs. A reviewer can clone this repo and verify the Agent design through deterministic evals and FastAPI dry-runs.

## What Is Included

```text
av_eval_agent/
  app/        FastAPI + LangGraph Agent prototype
  docs/       Architecture, operating spec, scenario format, n8n/MCP design docs
  evals/      20 deterministic natural-language routing/evaluation cases
  examples/   API request examples
  mcp/        Local MCP tool server prototype
  n8n/        n8n workflow JSON templates
  schemas/    JSON schemas for scenario definitions, manifests, and KPI results
  scripts/    Windows helper scripts for eval/API smoke tests
```

## Quick Verification

From a fresh clone:

```powershell
cd av-eval-agent
python -m venv .\av_eval_agent\.venv
.\av_eval_agent\.venv\Scripts\python.exe -m pip install -r .\av_eval_agent\requirements.txt
powershell -ExecutionPolicy Bypass -File .\av_eval_agent\scripts\run_agent_evals.ps1 --fail-on-fail
```

Expected result:

```text
AV Evaluation Agent eval summary
- total: 20
- pass: 20
- partial: 0
- fail: 0
```

The eval runner also writes a local report to:

```text
av_eval_agent/data/eval_reports/last_agent_eval_report.json
```

`av_eval_agent/data/` is intentionally ignored by Git so each reviewer can generate their own verification artifacts.

## FastAPI Dry-Run

Start the API:

```powershell
powershell -ExecutionPolicy Bypass -File .\av_eval_agent\scripts\start_agent_server.ps1
```

Check health:

```powershell
Invoke-RestMethod http://127.0.0.1:8010/health
```

Run a dry-run API smoke test:

```powershell
powershell -ExecutionPolicy Bypass -File .\av_eval_agent\scripts\test_agent_api.ps1
```

This verifies:

- natural-language scenario parsing
- scenario definition artifact creation
- run manifest creation
- OpenCDA/CARLA command planning without actually running CARLA
- KPI command planning / skip behavior when external KPI scripts are absent
- dry-run execution response

## Last Verified

Verified locally on 2026-06-29:

```text
Python compile check: passed
Deterministic evals: 20 pass / 0 partial / 0 fail
FastAPI health: status ok, service av-evaluation-agent
Dry-run API smoke test: prepare_status ready_for_execution, dry_run_status dry_run_prepared
```

## Scope Boundary

This repo is for **Agent design and verification**.

It does not include the full OpenCDA simulator code or CARLA runtime assets. Actual simulation execution requires an external OpenCDA/CARLA checkout and environment. The included Agent still records missing runner targets in `execution_plan.json`, so reviewers can confirm how the integration would be called without needing CARLA installed.

## Key Documents

Start here:

- [Agent architecture](av_eval_agent/docs/agent_architecture_ko.md)
- [Research-grade operating spec](av_eval_agent/docs/research_grade_agent_operating_spec_ko.md)
- [Submission architecture](av_eval_agent/docs/agent_submission_architecture_ko.md)
- [Scenario definition format](av_eval_agent/docs/scenario_definition_format_ko.md)
- [n8n node graph console](av_eval_agent/docs/n8n_node_graph_console_ko.md)
- [Codex/MCP workflow](av_eval_agent/docs/codex_agent_platform_workflow_ko.md)

Full document index:

- [av_eval_agent/docs/README.md](av_eval_agent/docs/README.md)

## Main Workflow

```text
Natural-language request
-> scenario classification
-> scenario definition JSON/table
-> validation and guardrail checks
-> OpenCDA/CARLA execution plan
-> KPI plan
-> dry-run or external simulation handoff
-> dashboard/report artifact plan
```

## Repository Hygiene

The following are intentionally excluded:

- full OpenCDA source tree
- CARLA cache/assets not required for Agent verification
- simulation logs, generated dashboards, raw data dumps
- model weights and videos
- local virtual environments
