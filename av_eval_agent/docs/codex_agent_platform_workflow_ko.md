# Codex 기반 AI Agent 설계/운영 워크플로우

## 결론

이 레포는 이제 단순한 OpenCDA 코드 보조 환경이 아니라, Codex가 다음 흐름을 반복할 수 있는 AI Agent 설계/운영 플랫폼 형태로 확장한다.

```text
문서 검색
-> Agent 설계안/작업 분해
-> GitHub issue/PR 단위 구현
-> eval 실행
-> 실험 로그/결과 조회
-> 설계 결정 기록
```

## 연결 구성

| 영역 | 이 레포에서의 구현 | 목적 |
|---|---|---|
| GitHub | `.github/ISSUE_TEMPLATE`, PR template | Agent 작업을 PR-sized issue로 쪼개고 리뷰 가능하게 관리 |
| 문서 저장소 | `av_eval_agent/docs`, `docs`, `search_docs` | 요구사항, 설계안, 정의서 기준, 실험 절차를 Codex가 검색 |
| 이슈 관리 | GitHub issue template, MCP `create_agent_task` | 설계안을 바로 작업 단위로 변환 |
| 평가/실험 로그 | `av_eval_agent/evals`, `data/experiment_db`, `query_logs` | Agent 판단 품질과 실험 결과를 재현 가능하게 확인 |
| MCP 커스텀 툴 | `av_eval_agent/mcp/server.py` | Codex가 문서 검색, eval 실행, 로그 조회, 설계 결정 저장을 도구 호출로 수행 |

## Agent 컴포넌트 기준

```text
AV Evaluation Agent
 ├─ Planner
 │   ├─ 자연어 요청 이해
 │   ├─ scenario_id / scenario_type 분류
 │   └─ OpenCDA 실행 계획 생성
 ├─ Tool Executor
 │   ├─ OpenCDA/CARLA runner
 │   ├─ KPI runner
 │   └─ MCP tool server
 ├─ Memory
 │   ├─ run_manifest.json
 │   ├─ experiment_db/runs_index.json
 │   └─ experiment_db/events.jsonl
 ├─ Evaluator
 │   ├─ 공통 KPI contract
 │   ├─ deterministic eval cases
 │   └─ scenario alignment review
 └─ Guardrail
     ├─ approval gate
     ├─ dry-run default
     └─ human-in-the-loop mismatch review
```

## MCP 툴

| Tool | 사용 예 |
|---|---|
| `search_docs` | "scenario definition format 찾아줘" |
| `create_agent_task` | "Memory 구현 작업을 GitHub issue 초안으로 만들어줘" |
| `run_agent_eval` | "현재 Agent 분류 eval 돌려줘" |
| `query_logs` | "최근 run 실패 이벤트 보여줘" |
| `get_scenario` | "run_id 기준 scenario_definition 가져와줘" |
| `save_design_decision` | "KPI contract를 시나리오와 분리한다는 결정을 기록해줘" |

## Eval 기준

기본 eval은 `av_eval_agent/evals/eval_cases.json`의 20개 케이스를 사용한다.

```powershell
powershell -ExecutionPolicy Bypass -File .\av_eval_agent\scripts\run_agent_evals.ps1
```

판정은 세 단계다.

| 판정 | 의미 |
|---|---|
| `pass` | 기대한 시나리오 분류, 실행 의도, 감지값, validation 상태가 모두 맞음 |
| `partial` | 핵심 분류는 맞지만 일부 보조 값이 어긋남 |
| `fail` | 핵심 분류 또는 다수 기준이 실패 |

## 작업 흐름

1. `search_docs`로 관련 설계/요구사항/기준 문서를 찾는다.
2. `create_agent_task` 또는 GitHub issue template으로 작업을 만든다.
3. 구현은 PR 단위로 진행하고 PR template의 Agent workflow impact를 체크한다.
4. `run_agent_eval` 또는 `run_agent_evals.ps1`로 deterministic eval을 실행한다.
5. 실험 run은 `query_logs`, `get_scenario`, FastAPI `/pipeline/status/{run_id}`로 추적한다.
6. 중요한 설계 판단은 `save_design_decision`으로 기록한다.

## 다음 확장

- Notion/Google Drive/Confluence 문서를 export 또는 connector로 받아 `search_docs` 대상에 포함한다.
- GitHub connector 인증이 가능한 환경에서는 `create_agent_task` 초안을 실제 issue 생성으로 교체한다.
- LangSmith/Langfuse 같은 trace 도구를 붙여 prompt, tool call, 실패 원인을 저장한다.
- MCP 서버를 공식 Python MCP SDK 기반으로 교체해 배포 안정성을 높인다.

