# 개발 가이드

## 1. 로컬 서버 실행

```powershell
cd "C:\Users\User\Desktop\OpenCDA - 복사본\av_eval_agent"
.\scripts\start_agent_server.ps1
```

## 2. API 단독 테스트

```powershell
cd "C:\Users\User\Desktop\OpenCDA - 복사본\av_eval_agent"
.\scripts\test_agent_api.ps1
```

## 3. n8n Webhook 테스트

```powershell
cd "C:\Users\User\Desktop\OpenCDA - 복사본"
curl.exe -s -X POST "http://127.0.0.1:5678/webhook/av-eval-agent" `
  -H "Content-Type: application/json; charset=utf-8" `
  --data-binary "@av_eval_agent\examples\scenario2_request_api.json"
```

## 4. 코드 위치

| 파일 | 역할 |
| --- | --- |
| `app/graph.py` | LangGraph Agent 상태 머신 |
| `app/main.py` | FastAPI endpoint |
| `app/services/artifact_store.py` | run 산출물 저장 |
| `app/services/opencda_runner.py` | OpenCDA 실행 연결 준비 |
| `app/services/kpi_runner.py` | KPI 스크립트 실행 연결 준비 |
| `n8n/av_eval_agent_workflow.template.json` | n8n workflow 템플릿 |

## 5. 개발 원칙

- 새 실험은 항상 새 `run_id`를 만든다.
- 원본 시나리오 파일은 수정하지 않는다.
- 실험 파일 수정은 `generated_files` 복사본에서만 수행한다.
- KPI 계산은 run별 로그 경로를 인자로 받도록 점진적으로 통일한다.
