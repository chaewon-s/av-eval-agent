# AV Evaluation Agent 최종 보완 요약

## 목적

외부 검토에서 지적된 n8n 워크플로우의 논리 버그, 운영 견고성, 보안, 재현성 문제를 반영하여 연구기관 제출 설명이 가능한 Agent 구조로 보완하였다.

본 시스템에서 n8n은 AI Agent 자체가 아니라 orchestration layer이다. 실제 시나리오 정의, 검증, OpenCDA/CARLA 실행 준비, KPI 산출, 실패 진단, 보고서 생성, memory/autotune 판단은 FastAPI backend의 agent endpoint에서 수행한다.

## 반영 완료 항목

| 항목 | 반영 내용 |
| --- | --- |
| FailureDiagnosis 역방향 버그 | 실패 시에만 진단하도록 수정 |
| RunQualityGate 보존 | HumanReviewGate에서 quality gate와 research readiness 결과를 덮어쓰지 않도록 수정 |
| ResearchReadiness 게이트 | `submission_blocked`와 `submission_gate`에 반영 |
| 실패 경로 처리 | 실패 run도 실패 진단, 품질 게이트, 보고서 생성, human review로 이어지도록 정리 |
| 이름 정직성 | 제출용 workflow 이름을 n8n orchestration layer로 정리 |
| 민감정보 제거 | Slack 채널, 워크스페이스, credential id, 개인 이름, API key 패턴 제거 |
| 지식팩 단일화 | n8n 하드코딩 대신 `/agent/knowledge-packs` backend endpoint 사용, 실패 시 fallback |
| retry/backoff | n8n HTTP backend 호출에 지수 백오프 재시도 wrapper 추가 |
| webhook token gate | 선택적 `x-av-agent-token` 또는 body token 검증 구조 추가 |
| 실제 HTTP 응답 코드 | main webhook을 `responseNode` 구조로 바꾸고 `Respond to Webhook` 노드에서 401/500/200 반환 |
| 장시간 실행 분리 | sync webhook은 실제 CARLA 실행을 억제하고 async submit workflow로 유도 |
| async webhook 누락 지적 방지 | 제출용 JSON bundle에 main workflow와 async workflow를 함께 포함 |
| 재현성 메타데이터 | AutoTune model, temperature, seed, model version note를 request/run 결과에 기록 |
| fallback 문구 | AutoTune fallback 사유/기대효과를 UTF-8 한국어 문구로 정리 |

## 현재 n8n 구조

### Main workflow

파일:

`C:/Users/User/Desktop/OpenCDA - 복사본/av_eval_agent/n8n/av_eval_agent_workflow.template.json`

workflow id:

`AV_EVALUATION_AGENT_ORCHESTRATION_LAYER`

역할:

1. Webhook 요청 수신
2. 요청 정규화 및 선택적 token 검증
3. backend health/preflight 확인
4. knowledge pack 로드
5. ScenarioSpecAgent
6. ScenarioValidationAgent
7. ExperimentBuildAgent
8. SimulationRunAgent 준비 또는 long-run guard
9. KPIAgent 준비 또는 skip
10. FailureDiagnosisAgent
11. RunQualityGateAgent
12. ResearchReadinessAgent
13. ReportAgent
14. MemoryAgent
15. AutoTuneAgent
16. HumanReviewGate
17. Slack/HITL 알림 패키지 생성
18. 최종 응답 생성
19. Respond to Webhook 노드에서 실제 HTTP 상태코드 반환

### Async submit workflow

파일:

`C:/Users/User/Desktop/OpenCDA - 복사본/av_eval_agent/n8n/av_eval_agent_async_submit.workflow.json`

역할:

- 실제 CARLA/OpenCDA 실행 요청은 동기 webhook에서 붙잡지 않고 async workflow로 제출한다.
- 즉시 `run_id`와 `status_url`을 반환한다.
- 실행 상태는 `/pipeline/status/{run_id}`에서 추적한다.

### 제출용 n8n bundle

파일:

`C:/Users/User/Desktop/OpenCDA - 복사본/av_eval_agent/n8n/av_eval_agent_workflow.submission_sanitized.json`

포함 workflow:

1. `AV_EVALUATION_AGENT_ORCHESTRATION_LAYER`
2. `AV_EVAL_AGENT_ASYNC_SUBMIT`

따라서 main workflow의 `long_run_guard.async_webhook_path = /webhook/av-eval-agent-async`가 가리키는 async webhook은 별도 workflow로 제출 bundle 안에 함께 포함된다.

## 최신 검증 결과

### 0. n8n runtime 상태

```text
active workflows:
- AV_EVALUATION_AGENT_ORCHESTRATION_LAYER
- AV_EVAL_AGENT_ASYNC_SUBMIT
```

기존 LangGraph 명칭의 old id는 제출/실행 대상에서 제거하였다.

### 1. Report-only dry-run

```text
run_id = run_20260629_005713_fa538c6d
success = true
SimulationRunAgent = dry_run_prepared
KPIAgent = skipped_by_request
RunQualityGateAgent = fail
ResearchReadinessAgent = research_blocked
HTTP status = 200
```

해석:

- 실제 CARLA 실행과 KPI 산출을 끈 dry-run이므로 quality gate와 research readiness가 fail/block으로 나오는 것이 정상이다.
- 중요한 점은 보고서, quality gate, research readiness, human review package가 모두 생성된다는 것이다.

### 2. Long-run guard

```text
run_id = run_20260629_002144_90cc7217
success = true
long_run_guard.status = sync_execution_suppressed
async_webhook_path = /webhook/av-eval-agent-async
SimulationRunAgent = dry_run_prepared
KPIAgent = skipped_by_request
```

해석:

- sync webhook에 `execute_simulation=true`가 들어와도 30분 CARLA 실행을 붙잡지 않는다.
- 실제 실행은 async workflow로 보내도록 안내한다.

### 3. Async submit workflow

```text
run_id = run_20260629_005842_f3516e77
success = true
mode = async_background_pipeline
status = prepared_only
status_url = http://127.0.0.1:8010/pipeline/status/run_20260629_005842_f3516e77
```

해석:

- async workflow가 정상 응답한다.
- 이번 검증은 prepared-only이므로 실제 CARLA 실행은 수행하지 않았다.
- 실제 실행 시에는 async webhook에 `execute_simulation=true`, `run_kpis=true`를 넣어 호출한다.

### 4. Webhook token gate

```text
failed_agent = WebhookAuthGate
success = false
error = Unauthorized scenario request
HTTP status = 401
human_review.status = skipped_auth_failure
slack_notification.status = skipped_auth_failure
feedback_loop.status = skipped_auth_failure
```

해석:

- 요청에 token이 필요하도록 설정했는데 올바른 token이 없으면 workflow가 인증 실패로 종료된다.
- main webhook은 `responseNode`와 `Respond to Webhook` 노드를 사용하므로 JSON 필드뿐 아니라 실제 HTTP status도 401로 반환한다.
- 운영 배포 시에는 n8n public URL 앞단에 API gateway나 reverse proxy 인증을 추가하는 것이 좋다.

## 제출 시 설명해야 할 한계

| 한계 | 설명 |
| --- | --- |
| n8n은 Agent 본체가 아님 | n8n은 orchestration layer이고 실제 agent intelligence는 backend endpoint에 있음 |
| 제출용 기본 모드는 report-only | 장시간 CARLA 실행은 sync webhook이 아니라 async workflow에서 수행 |
| async workflow는 별도 workflow | 제출용 bundle에는 함께 포함하지만 n8n 화면에서는 별도 workflow로 관리 |
| token gate는 선택형 | 실제 외부 배포 시 API gateway, secret vault, HTTPS 적용 필요 |
| AutoTune seed는 추적용 | LLM의 완전한 token-level determinism을 보장한다기보다 run 재현성 메타데이터로 기록 |
| Slack credential은 제출 JSON에 포함하지 않음 | credential은 n8n runtime에서 별도 연결해야 함 |

## 연구기관 제출용 설명 문장

본 시스템은 자연어 시나리오 요구사항을 정의서 JSON으로 구조화하고, 검증 Agent가 필수값, 단위, 물리 조건을 점검한 뒤 OpenCDA/CARLA 실행 파일과 KPI 산출 계획을 생성하는 자율주행 평가 Agent이다. n8n은 각 Agent endpoint를 연결하는 orchestration layer로 사용되며, FastAPI backend가 ScenarioSpec, Validation, ExperimentBuild, SimulationRun, KPI, Report, Memory, AutoTune 역할을 수행한다. 장시간 CARLA 실행은 async workflow로 분리하여 `run_id`와 `status_url`을 즉시 반환하고, 실행 후 KPI와 보고서를 추적 가능하게 저장한다.

## 실제 CARLA 실행 호출 원칙

동기 webhook:

```text
POST http://127.0.0.1:5678/webhook/av-eval-agent
```

용도:

- report-only
- 정의서 생성
- 검증
- 실행 준비
- human review package 생성

비동기 webhook:

```text
POST http://127.0.0.1:5678/webhook/av-eval-agent-async
```

실제 실행 요청 예:

```json
{
  "scenario_request": "시나리오 1을 정의서 기준으로 생성하고 CARLA/OpenCDA에서 실행한 뒤 KPI를 계산해줘.",
  "scenario_id": "scenario_1",
  "execute_simulation": true,
  "run_kpis": true,
  "record": true,
  "review_required": true
}
```

상태 확인:

```text
GET http://127.0.0.1:8010/pipeline/status/{run_id}
```

## 최종 판단

현재 상태는 단순 데모형 workflow가 아니라, 평가기관 제출용으로 설명 가능한 연구형 Agent orchestration 구조이다. 다만 실제 운영 배포를 위해서는 외부 인증, persistent DB, CARLA worker queue, Slack credential vault, 반복 실험 통계 검증을 추가하는 것이 다음 단계이다.
