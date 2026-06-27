# AV Evaluation AI Agent

자연어 시나리오 요청을 받아 시나리오 정의서, OpenCDA/CARLA 실행 계획, 공통 KPI 계산 계획, 대시보드/리포트 산출물을 `run_id` 기준으로 관리하는 AI Agent MVP입니다.

## 목표

평가기관이 사용하는 절차처럼 다음 흐름을 자동화하는 것이 목표입니다.

```text
자연어 시나리오 요청
-> 시나리오 정의서 형식 자동 작성
-> OpenCDA/CARLA 실험 실행 계획 생성
-> 로그 저장
-> 공통 KPI 계산
-> 대시보드/보고서 생성
```

## 핵심 원칙

- 시나리오 정의서는 `(과-19)시나리오 정의서 (2).pdf`의 6-layer 표 형식을 따른다.
- 시나리오가 무엇이든 KPI 축은 동일하게 계산한다.
- 원본 OpenCDA 파일은 직접 수정하지 않고 run별 복사본과 manifest로 추적한다.
- n8n은 workflow orchestration, LangGraph는 Agent 판단 흐름, FastAPI는 API gateway 역할을 맡는다.

## 정의서 형식

Agent가 생성하는 정의서 형식:

```text
과-19_시나리오_정의서_6-layer_v2
```

표 컬럼:

```text
레이어 / 항목 / 요소 / 설명 / 시험 시나리오
```

자세한 설명:

```text
av_eval_agent/docs/scenario_definition_format_ko.md
```

## 공통 KPI

시나리오 1, 2 또는 향후 추가 시나리오 모두 같은 KPI contract를 사용합니다.

| 평가축 | KPI |
|---|---|
| 인지 | MOTA, MOTP |
| 교통 영향성 | Progress-adjusted Delay, Flow Efficiency |
| 주행 안전성 | Min 2D TTC, PET, Required Deceleration |
| 제어 성능 | Acceleration Variance Max, Yaw-rate Residual RMS |

공통 KPI 실행 스크립트:

```text
scripts/extract_scenario_kpis.py
```

## 서버 실행

```powershell
cd "C:\Users\User\Desktop\OpenCDA - 복사본"
powershell -ExecutionPolicy Bypass -File .\av_eval_agent\scripts\start_agent_server.ps1
```

상태 확인:

```powershell
Invoke-RestMethod http://127.0.0.1:8010/health
```

정상 응답:

```json
{
  "status": "ok",
  "service": "av-evaluation-agent"
}
```

## n8n workflow

n8n 주소:

```text
http://localhost:5678
```

workflow template:

```text
av_eval_agent/n8n/av_eval_agent_workflow.template.json
```

| 단계 | n8n webhook | FastAPI endpoint | 역할 |
|---|---|---|---|
| 1 | `/webhook/av-eval-agent/start` | `POST /run/start` | 자연어 요청을 받아 run 생성 |
| 2 | `/webhook/av-eval-agent/prepare` | `POST /run/prepare/{run_id}` | OpenCDA/KPI 실행 명령 저장 |
| 3 | `/webhook/av-eval-agent/execute` | `POST /run/execute/{run_id}` | dry-run 또는 실제 실행 |

## Codex 운영 워크플로우

이 레포는 Codex가 GitHub, 문서, 이슈, eval, MCP 도구를 묶어서 Agent 설계/운영 업무를 수행할 수 있도록 확장되어 있습니다.

| 영역 | 위치 |
|---|---|
| GitHub issue/PR 템플릿 | `.github/ISSUE_TEMPLATE`, `.github/pull_request_template.md` |
| Codex 운영 설계 문서 | `av_eval_agent/docs/codex_agent_platform_workflow_ko.md` |
| deterministic eval 20 cases | `av_eval_agent/evals/eval_cases.json` |
| eval runner | `av_eval_agent/evals/run_agent_evals.py` |
| MCP custom tools | `av_eval_agent/mcp/server.py` |
| 설계 결정 기록 | `av_eval_agent/docs/design_decisions` |

eval 실행:

```powershell
powershell -ExecutionPolicy Bypass -File .\av_eval_agent\scripts\run_agent_evals.ps1
```

MCP 도구:

```text
search_docs / create_agent_task / run_agent_eval / query_logs / get_scenario / save_design_decision
```

설정 예시는 다음 파일에 있습니다.

```text
av_eval_agent/mcp/config.example.json
```

## API 테스트

```powershell
powershell -ExecutionPolicy Bypass -File .\av_eval_agent\scripts\test_agent_api.ps1
```

이 테스트는 실제 CARLA 실험을 돌리지 않고 다음만 확인합니다.

- run 생성
- 정의서 저장
- OpenCDA 실행 계획 저장
- KPI 실행 계획 저장
- dry-run 응답 확인

## 산출물 위치

각 run은 아래 위치에 저장됩니다.

```text
C:\Users\User\Desktop\OpenCDA - 복사본\av_eval_agent\data\runs\<run_id>
```

주요 파일:

| 파일 | 의미 |
|---|---|
| `scenario_definition.json` | Agent 내부 전체 시나리오 정의 |
| `scenario_definition_form.json` | PDF 정의서 형식만 분리한 JSON |
| `scenario_definition_form.csv` | PDF 정의서 표와 같은 5열 CSV |
| `run_manifest.json` | run 상태, 산출물 경로, 실행 명령 |
| `execution_plan.json` | OpenCDA/KPI 실행 계획 |
| `generated_files/` | run별 OpenCDA PY/YAML 복사본 |
| `logs/` | OpenCDA/KPI 실행 로그 |
| `report/evaluation_agent_plan.md` | 실행 계획 보고서 |
| `dashboard/index.html` | preview dashboard |

## 현재 구현 범위

- 자연어 요청 분석
- 시나리오 1/2 자동 분류
- PDF 정의서 형식의 시나리오 표 생성
- validation warning/error 생성
- run별 산출물 폴더 생성
- OpenCDA 템플릿 파일 복사
- OpenCDA 실행 명령 계획 생성
- 공통 KPI 계산 명령 계획 생성
- n8n webhook template 제공
- dry-run API 검증

## 다음 개발 단계

- 실제 CARLA/OpenCDA 실행 완료 후 최신 로그 경로를 manifest에 자동 고정
- KPI 결과 JSON을 dashboard에 자동 반영
- 반복 실험 및 parameter sweep을 n8n loop로 확장
- 최종 평가 점수와 radar plot을 자동 생성
- 평가기관 제출용 PDF/HTML 리포트 자동 생성
