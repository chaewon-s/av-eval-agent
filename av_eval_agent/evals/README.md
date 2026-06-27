# AV Evaluation Agent Evals

이 폴더는 Agent가 자연어 요청을 `scenario_id`, `scenario_type`, 실행 의도, KPI/대시보드 의도, 감지 값으로 안정적으로 구조화하는지 확인하는 최소 eval 세트입니다.

## 실행

```powershell
powershell -ExecutionPolicy Bypass -File .\av_eval_agent\scripts\run_agent_evals.ps1
```

실패가 있으면 non-zero exit code를 내고 싶을 때:

```powershell
powershell -ExecutionPolicy Bypass -File .\av_eval_agent\scripts\run_agent_evals.ps1 --fail-on-fail
```

결과 JSON은 기본적으로 아래에 저장됩니다.

```text
av_eval_agent/data/eval_reports/last_agent_eval_report.json
```

## 판정 기준

- `pass`: 기대값과 검증 오류 여부가 모두 맞음
- `partial`: 핵심 시나리오 분류는 맞지만 일부 감지값 또는 의도 플래그가 어긋남
- `fail`: 핵심 시나리오 분류가 틀리거나 대부분의 기대값이 어긋남

20개 케이스는 시나리오 1/2, custom 후보, 한국어/영어 요청, V2X, 센서 조건, 날씨, 실행/대시보드/KPI 의도를 섞어서 구성했습니다.

