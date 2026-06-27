# 현재 구현 완료 상태 요약

## 완료된 항목

- FastAPI 기반 Agent 서버 실행 확인
- 자연어 입력을 받는 통합 pipeline endpoint 추가
- LangGraph Scenario Agent 기반 시나리오 분류 및 정의서 JSON 생성
- 정의서 JSON, CSV, 실행계획, KPI 계획, dashboard preview, report 생성
- 시나리오 1/2 자동 분류
- 시나리오 2 가로 도로 실행 파일을 현재 복사본 프로젝트 기준으로 정리
- SimulationRunAgent 설계 반영
  - OpenCDA/CARLA 실행 명령 생성
  - stdout/stderr 로그 저장 경로 생성
  - `data_dumping` 최신 폴더 추적
  - 로그 실패 패턴 탐지
  - KPI 계산 가능 여부 분류
- 공통 KPI contract 반영
  - 인지: MOTA, MOTP
  - 교통 영향성: Progress-adjusted Delay, Flow Efficiency
  - 주행안전성: min 2D TTC, PET, Required Deceleration
  - 제어 성능: Acceleration Variance Max, Yaw-rate Residual RMS
- 실험 이력 DB 추가
  - `av_eval_agent/data/experiment_db/events.jsonl`
  - `av_eval_agent/data/experiment_db/runs_index.json`
- 최종 결과 publisher 추가
  - `final_run_report.md`
  - `final_index.html`
- n8n 연결은 나중에 붙일 수 있도록 API 구조 정리

## 현재 실행 중인 서비스

```text
FastAPI Agent Server: http://127.0.0.1:8010
API Docs: http://127.0.0.1:8010/docs
```

## 새로 검증한 pipeline run 예시

```text
run_20260627_172023_6e4ce363
```

상태:

```text
prepared_only
```

의미:

- 자연어 요청을 분석해 실행계획까지 생성 완료
- 실제 CARLA/OpenCDA 실험은 아직 실행하지 않음
- n8n 또는 사용자 명령으로 이후 실행 가능

주요 확인 URL:

```text
http://127.0.0.1:8010/pipeline/status/run_20260627_172023_6e4ce363
http://127.0.0.1:8010/run/status/run_20260627_172023_6e4ce363
http://127.0.0.1:8010/run/result/run_20260627_172023_6e4ce363
```

## 생성된 주요 파일

```text
av_eval_agent/data/runs/run_20260627_172023_6e4ce363/
```

- `scenario_definition.json`
- `scenario_definition_form.json`
- `scenario_definition_form.csv`
- `execution_plan.json`
- `run_manifest.json`
- `agent_state.json`
- `experiment_plan.json`
- `kpi_plan.json`
- `dashboard/index.html`
- `report/evaluation_agent_plan.md`

## 다음 개발 단계

1. `execute_simulation=true` 조건에서 CARLA/OpenCDA 실제 실행 검증
2. 실행 후 `data_dumping` 최신 폴더가 정확히 pin 되는지 확인
3. KPI 계산이 최신 로그 기준으로 이어지는지 확인
4. 최종 dashboard/report publisher 결과 확인
5. n8n에서 `/pipeline/submit` 호출, status polling, 결과 링크 전달 연결

## n8n 연결 시점

n8n은 현재 backend가 안정화된 뒤 붙이는 것이 좋습니다.

지금은 FastAPI/LangGraph가 실험 자동화의 실제 두뇌이고, n8n은 이후 사용자 입력 UI, 승인 플로우, 반복 실행, 알림, 결과 링크 전달을 담당하는 외부 자동화 계층으로 붙입니다.
