# 내일 확인 체크리스트

## 1. 서버 상태 확인

```powershell
docker ps
Invoke-RestMethod http://127.0.0.1:8010/health
```

서버가 꺼져 있으면:

```powershell
cd "C:\Users\User\Desktop\OpenCDA - 복사본\av_eval_agent"
.\scripts\start_agent_server.ps1
```

## 2. n8n 확인

브라우저에서 아래 주소를 엽니다.

```text
http://localhost:5678
```

workflow:

```text
AV Evaluation Agent - LangGraph Workflow
```

## 3. n8n Webhook 테스트

PowerShell 출력에서 한글이 깨져 보이면 먼저 다음 명령을 실행합니다.

```powershell
chcp 65001
```

```powershell
cd "C:\Users\User\Desktop\OpenCDA - 복사본"
curl.exe -s -X POST "http://127.0.0.1:5678/webhook/av-eval-agent" `
  -H "Content-Type: application/json; charset=utf-8" `
  --data-binary "@av_eval_agent\examples\scenario2_request_api.json"
```

## 4. 생성된 run 확인

```text
C:\Users\User\Desktop\OpenCDA - 복사본\av_eval_agent\data\runs
```

각 run 폴더에서 확인할 파일:

- `scenario_definition.json`
- `run_manifest.json`
- `agent_state.json`
- `generated_files`
- `dashboard/index.html`
- `report/evaluation_agent_plan.md`

## 5. 다음 작업

1. OpenCDA/CARLA runner 연결
2. KPI 스크립트에 run별 로그 경로 인자 연결
3. dashboard를 실제 KPI 그래프 기반으로 교체
4. n8n 승인/반복 실험 workflow 확장
