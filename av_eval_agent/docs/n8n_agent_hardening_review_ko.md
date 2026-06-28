# n8n Agent 워크플로우 보완 리뷰

## 1. 보완 목적

외부 코드 리뷰에서 지적된 논리 버그, 운영 안정성, 연구 제출 신뢰성 문제를 기준으로 n8n 워크플로우와 FastAPI 백엔드를 보완했다. 핵심 방향은 다음과 같다.

- n8n은 `LangGraph 자체`가 아니라 Agent API를 조율하는 orchestration layer임을 명확히 한다.
- 실패 진단, 품질 게이트, 연구 제출 준비도 판정이 실제 제출 판단에 반영되도록 한다.
- 장시간 CARLA/OpenCDA 실행은 동기 웹훅에 묶지 않고 비동기 submit 구조로 분리한다.
- Slack, 사용자 계정, credential id 같은 민감정보를 제출용 JSON에서 제거한다.
- KPI/시나리오 정의 기준은 백엔드 knowledge-pack endpoint를 단일 출처로 사용한다.

## 2. 반영 완료 항목

| 항목 | 기존 문제 | 보완 결과 |
| --- | --- | --- |
| FailureDiagnosisAgent | 실패 시 진단을 건너뛰고 성공 시 실행되는 역방향 조건 | 실패가 있을 때만 진단을 실행하고, 정상 실행은 `skipped_no_failure`로 명시 |
| RunQualityGateAgent | 품질 게이트 결과가 HumanReviewGate에서 덮어써짐 | `quality_gate_status`, `gates`, `submission_gate`, `submission_blocked` 유지 |
| ResearchReadinessAgent | 결과가 저장만 되고 제출 판단에 반영되지 않음 | `research_ready`가 아니면 `submission_gate=review_required` |
| ReportAgent | 실패 시 보고서 생성 흐름이 불명확 | 실패/경고가 있어도 감사용 보고서를 생성하고 제출 게이트는 별도 차단 |
| Slack/HITL | Slack 결과가 후속 노드에서 유실될 수 있음 | `slack_notification`, `feedback_loop`, reviewer context 보존 |
| 장시간 실행 | 동기 웹훅이 30분 이상 CARLA 실행을 기다릴 수 있음 | 메인 웹훅은 report-only guard 적용, 실제 실행은 async workflow로 분리 |
| Retry/backoff | HTTP 요청이 단발 호출 | n8n Code node의 백엔드 호출에 지수 backoff retry wrapper 적용 |
| 웹훅 인증 | 공개 POST endpoint에 인증 없음 | 선택형 `x-av-agent-token` / `auth_token` 검증 로직 추가 |
| 지식 팩 | KPI/정의서 기준이 n8n과 백엔드에 중복 | `GET /agent/knowledge-packs`를 단일 출처로 사용, 실패 시 fallback |
| 재현성 | AutoTune 모델만 기록 | model, temperature, seed, model version note를 요청/결과에 기록 |
| 민감정보 | Slack workspace, credential id, 개인 계정 export 위험 | 제출용 n8n 폴더를 정리하고 민감정보 검색 결과 없음 확인 |

## 3. 현재 n8n 구성

제출용 n8n 파일은 세 개만 유지한다.

| 파일 | 용도 |
| --- | --- |
| `av_eval_agent_workflow.template.json` | 현재 n8n에 import되는 운영 템플릿 |
| `av_eval_agent_workflow.submission_sanitized.json` | 제출용 익명화 JSON |
| `av_eval_agent_async_submit.workflow.json` | 장시간 CARLA/OpenCDA 실행용 비동기 submit workflow |

메인 workflow는 기본적으로 report-only 동기 오케스트레이션이다. `execute_simulation=true`가 들어오더라도 `force_sync_execution=true`를 명시하지 않으면 실제 실행을 억제하고 async workflow 사용을 안내한다.

```text
POST /webhook/av-eval-agent
  -> ScenarioSpecAgent
  -> Validation
  -> Build
  -> report-only long-run guard
  -> KPI/diagnosis/gates/report/HITL

POST /webhook/av-eval-agent-async
  -> token check
  -> backend health retry
  -> POST /pipeline/submit background=true
  -> run_id/status_url 즉시 반환
```

## 4. 동기 실행 보호 정책

메인 workflow는 평가기관에 Agent 구조를 보여주고 정의서, 검증, 보고서, HITL 흐름을 확인하는 용도다. 실제 CARLA/OpenCDA 실행은 오래 걸리므로 메인 workflow가 HTTP 연결을 잡고 기다리지 않는다.

메인 webhook에 `execute_simulation=true`가 들어오면 다음처럼 처리한다.

```text
request.requested_execute_simulation = true 로 기록
request.execute_simulation = false 로 억제
request.run_kpis = false 로 억제
long_run_guard.status = sync_execution_suppressed
async_webhook_path = /webhook/av-eval-agent-async 반환
```

로컬 디버깅 목적으로만 `force_sync_execution=true`를 넣으면 기존 동기 실행이 가능하다. 연구기관 제출/운영 모드에서는 async workflow를 표준 경로로 사용한다.

## 5. 인증과 보안

workflow는 선택형 token gate를 제공한다.

```text
Header: x-av-agent-token: <token>
또는 body/query: auth_token
```

n8n 변수 `AV_AGENT_WEBHOOK_TOKEN`을 설정하면 해당 토큰이 우선 적용된다. 로컬 데모 환경에서는 토큰이 없으면 `auth_required=false`로 기록된다. 외부 배포 시에는 n8n 변수 또는 API gateway에서 토큰을 반드시 설정해야 한다.

제출용 JSON에는 Slack workspace id, Slack channel id, Slack credential id, 개인 이메일, OpenAI API key가 남아 있지 않도록 확인했다.

## 6. Retry/backoff

n8n Code node의 백엔드 호출에는 다음 형태의 retry wrapper를 적용했다.

```javascript
async function requestWithRetry(options, attempts = 3, baseDelayMs = 500) {
  let lastError;
  for (let i = 0; i < attempts; i += 1) {
    try {
      return await helpers.httpRequest(options);
    } catch (error) {
      lastError = error;
      const waitMs = baseDelayMs * Math.pow(2, i);
      await new Promise(resolve => setTimeout(resolve, waitMs));
    }
  }
  throw lastError;
}
```

초기 적용 과정에서 wrapper 내부 호출까지 자기 자신으로 치환되는 재귀 문제가 있었으나, 최종 파일에서는 wrapper 내부가 `helpers.httpRequest(options)`를 직접 호출하도록 수정했다.

## 7. 재현성 기록

AutoTuneAgent 요청과 결과에는 다음 메타데이터를 남긴다.

| 항목 | 기본값 | 의미 |
| --- | --- | --- |
| `autotune_model` | `gpt-4.1-mini` | 자동 조정 제안에 사용한 모델 |
| `autotune_temperature` | `0.2` | 출력 변동성 제어값 |
| `autotune_seed` | `20260628` | 연구 실행 추적용 seed |
| `model_version_note` | 고정 메타데이터 문구 | 모델 버전/요청 조건 설명 |

주의할 점은 upstream LLM이 seed 기반 완전 결정론을 보장하지 않을 수 있다는 것이다. 따라서 본 시스템의 재현성은 token-level 재현보다 run별 입력 정의서, 생성 YAML/PY, KPI 산출물, AutoTune patch 후보, human approval 기록, 산출물 hash를 중심으로 확보한다.

## 8. 검증 결과

### 8-1. Report-only dry-run

```text
run_id = run_20260629_000026_7837ffed
success = true
quality_gate = fail
research_readiness = research_blocked
failure_diagnosis = skipped_no_failure
```

실험과 KPI를 실행하지 않은 dry-run이므로 quality/readiness가 fail 또는 blocked로 나오는 것이 정상이다. 이 상태에서 보고서는 생성되지만 제출 게이트는 통과하지 않는다.

### 8-2. 메인 webhook에 실제 실행 요청 입력

```text
run_id = run_20260629_000118_0c6b87e3
long_run_guard.status = sync_execution_suppressed
async_webhook_path = /webhook/av-eval-agent-async
```

메인 workflow가 CARLA 실행을 붙잡지 않고 async 실행 경로를 안내했다. 외부 리뷰에서 지적한 동기 웹훅 타임아웃 위험을 구조적으로 줄인 것이다.

### 8-3. Async submit workflow

```text
run_id = run_20260629_000224_afade722
mode = async_background_pipeline
status = prepared_only
status_url = http://127.0.0.1:8010/pipeline/status/run_20260629_000224_afade722
```

실행/KPI 옵션이 false였기 때문에 prepared-only가 정상이다. 실제 CARLA 실행은 async webhook에 `execute_simulation=true`, `run_kpis=true`를 넣어 요청한다.

### 8-4. Token gate

```text
failed_agent = WebhookAuthGate
success = false
error = Unauthorized scenario request
```

요청에 token이 설정되었지만 올바른 token이 제공되지 않으면 workflow가 인증 실패로 종료된다.

## 9. 남은 운영 과제

현재 구조는 연구기관 제출용 Agent 설계로 설명 가능한 수준까지 보완되었다. 다만 상시 운영 시스템으로 확장하려면 다음 항목을 별도 인프라로 추가하는 것이 좋다.

- n8n public URL 앞단 API gateway 인증
- PostgreSQL 기반 run/event 영속 DB
- CARLA worker queue 분리
- Slack native approval credential의 secret vault 관리
- 동일 시나리오 반복 실행과 통계 신뢰구간 산출
- 공식 KPI threshold 문헌 근거와 내부 기준 분리

## 10. 제출 시 설명 문장

제출 문서에는 다음처럼 설명하는 것이 가장 안전하다.

> 본 시스템에서 n8n은 AI Agent 자체가 아니라, FastAPI/LangGraph 기반 Agent backend를 호출하고 Human-in-the-loop 검토, 비동기 실행 제출, 외부 알림을 조율하는 orchestration layer이다. 실제 시나리오 정의서 생성, 검증, OpenCDA/CARLA 실행, KPI 산출, 실패 진단, 연구 제출 준비도 판정은 backend Agent endpoint에서 수행된다.

> 장시간 CARLA/OpenCDA 실행은 동기 웹훅으로 처리하지 않고, 별도 async submit workflow가 `run_id`와 `status_url`을 즉시 반환한다. 따라서 평가자는 실행 상태와 산출물을 `/pipeline/status/{run_id}`에서 추적할 수 있다.
