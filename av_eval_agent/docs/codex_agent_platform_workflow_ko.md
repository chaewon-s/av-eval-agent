# Codex Workflow

## Stack

| Area | Tool |
|---|---|
| source | GitHub |
| docs | repository markdown |
| issues | GitHub Issues |
| eval | `av_eval_agent/evals` |
| workflow | n8n |
| tool bridge | MCP |

## Agent Components

| Component | Repo Area |
|---|---|
| Planner | `app/graph.py`, scenario services |
| Tool Executor | `opencda_runner.py`, `kpi_runner.py` |
| Memory | `experiment_history.py`, run manifests |
| Evaluator | `evals/`, KPI services |
| Guardrail | validation, approval gate, quality gate |
| Integrations | `mcp/`, `n8n/` |

## MCP Tools

| Tool | Use |
|---|---|
| `search_docs` | docs lookup |
| `create_agent_task` | issue draft |
| `run_agent_eval` | eval execution |
| `query_logs` | run lookup |
| `get_scenario` | scenario lookup |
| `save_design_decision` | decision log |

## Eval

| Item | Value |
|---|---|
| cases | 20 |
| file | `av_eval_agent/evals/eval_cases.json` |
| runner | `av_eval_agent/evals/run_agent_evals.py` |
| command | `powershell -ExecutionPolicy Bypass -File .\av_eval_agent\scripts\run_agent_evals.ps1 --fail-on-fail` |

## Work Loop

```text
docs/request
-> issue
-> code/docs change
-> eval or smoke test
-> commit
-> push
```

## Issue Types

| Type | Template |
|---|---|
| Agent task | `.github/ISSUE_TEMPLATE/agent_task.yml` |
| Eval failure | `.github/ISSUE_TEMPLATE/eval_failure.yml` |

## Branch Rule

```text
codex/<short-task-name>
```
