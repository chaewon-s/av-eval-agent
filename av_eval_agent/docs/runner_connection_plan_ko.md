# OpenCDA/CARLA Runner 연결 계획

## 1. 현재 상태

현재 Agent는 실행 계획과 산출물 폴더를 생성합니다. 실제 CARLA/OpenCDA 실행은 아직 worker로 완전히 연결하지 않았습니다.

## 2. 연결 목표

`run_manifest.json`에 기록된 `generated_files` 복사본을 대상으로 OpenCDA를 실행하고, 결과 로그를 같은 run 폴더 아래에 저장합니다.

## 3. 실행 정책

- CARLA 서버가 먼저 실행되어 있어야 합니다.
- 실행 대상은 `av_eval_agent/data/runs/{run_id}/generated_files` 안의 복사본입니다.
- 원본 `opencda/scenario_testing` 파일은 실행 중 수정하지 않습니다.
- 실행 로그는 `av_eval_agent/data/runs/{run_id}/logs` 아래에 저장합니다.

## 4. 다음 구현 항목

1. run_manifest에서 실행 대상 scenario 파일 선택
2. `run_opencda_0914.ps1` 호출 인자 정리
3. 실행 stdout/stderr를 run별 로그로 저장
4. 완료 후 KPI script 자동 호출
5. dashboard/report에 결과 경로 반영
