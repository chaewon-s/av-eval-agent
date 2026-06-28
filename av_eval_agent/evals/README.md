# Evals

## Run

```powershell
powershell -ExecutionPolicy Bypass -File .\av_eval_agent\scripts\run_agent_evals.ps1 --fail-on-fail
```

## Cases

```text
eval_cases.json
```

Coverage:

- scenario 1 / scenario 2
- custom scenario fallback
- Korean and English requests
- V2X / no V2X
- sensor conditions
- speed values
- execution intent
- dashboard intent
- KPI intent

## Result

```text
av_eval_agent/data/eval_reports/last_agent_eval_report.json
```

## Status

| Status | Meaning |
|---|---|
| `pass` | all checks matched |
| `partial` | scenario matched, some secondary checks missed |
| `fail` | critical scenario check failed |
