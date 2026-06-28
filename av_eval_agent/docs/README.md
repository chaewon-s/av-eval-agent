# AV Evaluation Agent Document Index

이 폴더에는 AV Evaluation Agent 설계와 검증에 필요한 문서만 남긴다.

## Core Design

| 문서 | 목적 |
|---|---|
| [agent_architecture_ko.md](agent_architecture_ko.md) | 전체 Agent 구조와 LangGraph/FastAPI/n8n 역할 |
| [research_grade_agent_operating_spec_ko.md](research_grade_agent_operating_spec_ko.md) | 평가기관 제출 수준의 운영 명세 |
| [agent_submission_architecture_ko.md](agent_submission_architecture_ko.md) | 제출/리뷰 관점 아키텍처 요약 |
| [scenario_definition_format_ko.md](scenario_definition_format_ko.md) | 6-layer 시나리오 정의서 포맷 |

## Operations And Workflow

| 문서 | 목적 |
|---|---|
| [codex_agent_platform_workflow_ko.md](codex_agent_platform_workflow_ko.md) | Codex + GitHub + MCP + eval 운영 방식 |
| [n8n_node_graph_console_ko.md](n8n_node_graph_console_ko.md) | n8n node graph와 console workflow |
| [n8n_agent_hardening_review_ko.md](n8n_agent_hardening_review_ko.md) | n8n/Agent hardening 검토 |
| [final_agent_hardening_closure_ko.md](final_agent_hardening_closure_ko.md) | 최종 hardening closure 기록 |

## Design Decisions

| 문서 | 목적 |
|---|---|
| [design_decisions/README.md](design_decisions/README.md) | 향후 설계 결정 기록 위치 |

## Verification

실행 검증은 문서가 아니라 아래 eval/API artifact로 수행한다.

```text
av_eval_agent/evals/eval_cases.json
av_eval_agent/evals/run_agent_evals.py
av_eval_agent/scripts/run_agent_evals.ps1
av_eval_agent/scripts/test_agent_api.ps1
```

