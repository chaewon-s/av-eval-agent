# n8n + LangGraph 기반 AV 평가 Agent Workflow

## 결론

n8n은 지금 바로 핵심 로직에 넣기보다, 나중에 붙이는 외부 오케스트레이션 계층으로 두는 것이 맞습니다.

현재 핵심은 FastAPI + LangGraph Agent가 아래 흐름을 단독으로 안정적으로 수행하는 것입니다.

```text
사용자 자연어 입력
  -> LangGraph Scenario Agent
  -> 정의서 JSON 생성
  -> 검증 Agent
  -> YAML/PY 생성 또는 기존 시나리오 파일 선택
  -> 실험 실행 Queue 등록
  -> CARLA/OpenCDA Runner
  -> 로그/영상/센서데이터 저장
  -> KPI 계산
  -> 대시보드/보고서 생성
  -> 실험 이력 DB 저장
```

이 흐름이 안정화되면 n8n은 사용자가 편하게 입력하고, 실행 상태를 기다리고, 결과 링크를 전달하는 자동화 도구로 붙입니다.

## 역할 분담

| 구성요소 | 역할 |
|---|---|
| FastAPI | 외부에서 호출 가능한 API 제공 |
| LangGraph Scenario Agent | 자연어 요청을 시나리오 정의서 JSON과 실행계획으로 변환 |
| Validation Agent | 정의서 필수값, 속도, 위치, V2X 조건, 파일 존재 여부 검증 |
| YAML/PY Generator | 시나리오에 맞는 YAML/PY 사본 생성 또는 기존 파일 선택 |
| SimulationRunAgent | CARLA/OpenCDA 실행, 로그 저장, 실패 감지, data_dumping 폴더 추적 |
| KPI Runner | 모든 시나리오에 동일한 KPI 계산 기준 적용 |
| Result Publisher | 대시보드와 보고서 생성 |
| Experiment History DB | run_id 기준 실험 이력 저장 |
| n8n | 나중에 Webhook, 알림, 반복 실행, 승인 플로우 담당 |

## 현재 구현된 핵심 API

```text
GET  /health
POST /pipeline/submit
GET  /pipeline/status/{run_id}
GET  /pipeline/history
POST /run/start
POST /run/execute/{run_id}
GET  /run/status/{run_id}
GET  /run/result/{run_id}
GET  /run/list
```

## n8n에서 나중에 붙일 흐름

```text
1. n8n Chat 또는 Webhook Trigger
   사용자가 자연어로 시나리오 요청

2. HTTP Request
   POST http://host.docker.internal:8010/pipeline/submit

3. Wait / Polling
   GET http://host.docker.internal:8010/pipeline/status/{run_id}

4. IF node
   status가 finished / failed / human_review_required인지 분기

5. 결과 전달
   dashboard, report, run_manifest 링크를 사용자에게 전달
```

## n8n에서 호출할 예시 Body

```json
{
  "user_request": "시나리오2 고속도로 cut-out 상황을 정의서 형식으로 채우고 실험 준비해줘. KPI는 공통 기준으로 계산 준비.",
  "execute_simulation": false,
  "run_kpis": false,
  "apply_ml": false,
  "record": false,
  "background": true
}
```

실험까지 바로 돌리고 싶을 때는 `execute_simulation`과 `run_kpis`를 `true`로 바꿉니다.

## 현재 단계에서 n8n을 뒤로 미루는 이유

1. 평가기관용 시스템의 핵심 신뢰성은 n8n이 아니라 KPI 계산, 로그 추적, 실험 재현성입니다.
2. LangGraph/FastAPI 파이프라인이 먼저 안정화되어야 n8n이 단순하고 견고해집니다.
3. CARLA/OpenCDA 실행은 오래 걸리고 실패 가능성이 있으므로, 먼저 backend에서 실패 감지와 이력 저장이 잘 되어야 합니다.
4. n8n은 이후에 승인, 알림, 반복 실행, 결과 공유를 자동화하는 계층으로 붙이는 편이 구조가 명확합니다.

## 현재 권장 개발 순서

1. FastAPI/LangGraph 단독 pipeline 완성
2. SimulationRunAgent의 실패 감지와 data_dumping 추적 검증
3. KPI Runner가 시나리오 1, 2 모두에서 동일 기준으로 동작하는지 검증
4. Result Publisher가 대시보드/보고서를 자동 생성하는지 검증
5. n8n Webhook으로 `/pipeline/submit` 호출 연결
6. n8n에서 status polling과 결과 링크 전달 연결
