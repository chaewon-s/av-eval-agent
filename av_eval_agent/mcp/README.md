# MCP Tools

## Tools

| Tool | Output |
|---|---|
| `search_docs` | matching doc snippets |
| `create_agent_task` | GitHub issue draft markdown |
| `run_agent_eval` | eval summary |
| `query_logs` | run history and manifest data |
| `get_scenario` | scenario definition |
| `save_design_decision` | markdown decision record |

## Config Example

```text
config.example.json
```

Replace:

```text
<project-root>
```

## Smoke Test

```powershell
$msg = '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
$msg | & "C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" .\av_eval_agent\mcp\server.py
```
