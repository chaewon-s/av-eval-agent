# n8n Hardening Review

## Completed

| Area | Check |
|---|---|
| long-run guard | sync execution suppression |
| async submit | `/pipeline/submit` workflow |
| status polling | `/pipeline/status/{run_id}` |
| token gate | optional webhook token |
| retry | backend retry/backoff |
| knowledge pack | backend endpoint first |
| reproducibility | model, temperature, seed metadata |

## Main Workflow

| Step | Status |
|---|---|
| webhook input | present |
| run start | present |
| prepare | present |
| dry-run execute | present |
| HITL branch | present |
| result fetch | present |

## Async Workflow

| Step | Status |
|---|---|
| submit | present |
| immediate response | present |
| status URL | present |
| background flag | present |

## Security

| Item | Status |
|---|---|
| webhook token | optional |
| local demo without token | allowed |
| production token | required |
| credentials in workflow JSON | not committed |

## Verification

| Check | Expected |
|---|---|
| report-only dry-run | `dry_run_prepared` |
| sync actual-run request | `sync_execution_suppressed` |
| async submit | `submitted` |
| invalid token | rejected |

## Remaining

- production secret vault
- hosted n8n credential setup
- external simulator worker queue
- CARLA host monitoring
