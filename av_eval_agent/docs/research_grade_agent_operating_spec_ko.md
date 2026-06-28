# Research Operation Spec

## Rules

| Rule | Status |
|---|---|
| 원본 OpenCDA 파일 직접 수정 금지 | required |
| run 단위 산출물 보존 | required |
| V2X/No V2X 공통 KPI 계약 | required |
| warning 발생 시 human review | required |
| simulator 장시간 실행은 async route | required |
| 제출 전 manifest/hash 확인 | required |

## Agents

| Agent | Output |
|---|---|
| PreflightAgent | backend/tool readiness |
| ScenarioSpecAgent | `scenario_definition.json`, `scenario_definition_form.csv` |
| ScenarioValidationAgent | validation result |
| ExperimentBuildAgent | run-local YAML/PY plan |
| SimulationRunAgent | `execution_result.json`, logs |
| KPIAgent | KPI outputs |
| FailureDiagnosisAgent | `failure_diagnosis.json` |
| RunQualityGateAgent | `quality_gate.json` |
| ResearchReadinessAgent | `research_readiness.json` |
| ReportAgent | final report |
| MemoryAgent | run comparison |
| AutoTuneAgent | tuning candidates |

## Run Layout

```text
av_eval_agent/data/runs/{run_id}/
  scenario_definition.json
  scenario_definition_form.csv
  execution_plan.json
  generated/
  logs/
  execution_result.json
  kpi/
  failure_diagnosis.json
  quality_gate.json
  research_readiness.json
  report/
  run_manifest.json
```

## KPI Contract

| Axis | KPI | Direction |
|---|---|---|
| perception | MOTA | higher |
| perception | MOTP | lower |
| control | Acceleration Variance | lower |
| control | Yaw-rate Residual RMS or Steering RMS | lower |
| traffic impact | Progress-adjusted Delay | lower |
| traffic impact | Flow Efficiency | higher |
| driving safety | min 2D TTC | higher |
| driving safety | PET | higher |
| driving safety | Required Deceleration | lower |

## Quality Gate

| Check | Pass Condition |
|---|---|
| OpenCDA execution | return code 0 |
| KPI calculation | result files created |
| scenario alignment | definition matches run plan |
| failure diagnosis | error 0, warning 0 |
| artifact manifest | required paths and hashes tracked |

## Readiness Status

| Status | Meaning |
|---|---|
| `research_ready` | all checks passed |
| `research_review_required` | warning or reviewer approval needed |
| `research_blocked` | execution, KPI, or artifact blocker |

## HITL Actions

| Action | Result |
|---|---|
| approve | keep current run |
| rerun | create new run from same definition |
| revise and rerun | feed reviewer note into scenario step |
| stop | archive run |

## Async Execution

| Route | Use |
|---|---|
| `POST /pipeline/submit` | register long run |
| `GET /pipeline/status/{run_id}` | poll status |
| `force_sync_execution=true` | local debugging only |

## Checklist

- [ ] `run_manifest.json`
- [ ] `scenario_definition.json`
- [ ] `scenario_definition_form.csv`
- [ ] run-local YAML/PY plan
- [ ] OpenCDA return code
- [ ] current data dump path
- [ ] KPI outputs
- [ ] failure diagnosis
- [ ] quality gate
- [ ] research readiness
- [ ] HITL record for warnings
- [ ] final report
- [ ] artifact hashes

## Last Check

```text
date: 2026-06-29
evals: 20 pass / 0 partial / 0 fail
api dry-run: pass
```
