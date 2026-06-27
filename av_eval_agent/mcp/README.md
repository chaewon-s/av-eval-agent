# AV Evaluation Agent MCP Tools

이 폴더는 Codex/ChatGPT가 AV 평가 Agent를 단순 코드 레포가 아니라 운영 도구처럼 다루기 위한 MCP 도구 서버 골격입니다.

## 제공 도구

| Tool | 역할 |
|---|---|
| `search_docs` | `av_eval_agent/docs`, `README`, `docs` 문서 검색 |
| `create_agent_task` | Agent 작업을 GitHub issue 초안 Markdown으로 생성 |
| `run_agent_eval` | 20개 deterministic eval case 실행 |
| `query_logs` | run history, event log, manifest 조회 |
| `get_scenario` | run_id 또는 scenario_id 기준 시나리오 정의 조회 |
| `save_design_decision` | 설계 결정 기록을 `docs/design_decisions`에 저장 |

## Codex MCP 설정 예시

`config.example.json`의 `<project-root>`를 실제 경로로 바꿔 MCP 설정에 추가합니다.

```json
{
  "mcpServers": {
    "av-eval-agent": {
      "command": "C:\\Users\\User\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe",
      "args": [
        "C:\\Users\\User\\Desktop\\OpenCDA - 복사본\\av_eval_agent\\mcp\\server.py"
      ],
      "env": {
        "PYTHONPATH": "C:\\Users\\User\\Desktop\\OpenCDA - 복사본\\av_eval_agent\\.venv\\Lib\\site-packages"
      }
    }
  }
}
```

## 로컬 smoke test

```powershell
$msg = '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
$msg | & "C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" .\av_eval_agent\mcp\server.py
```

이 서버는 외부 `mcp` Python 패키지 없이 stdio JSON-RPC로 동작하도록 작성했습니다. 나중에 MCP SDK를 설치하면 현재 tool handler들을 SDK 서버에 그대로 연결하면 됩니다.

