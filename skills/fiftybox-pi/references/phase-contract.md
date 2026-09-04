# Phase Contract (fiftybox-pi)

> 페이즈별 실행 주체·아티팩트·게이트·선행 조건. 엔진은 공유 `orchestrate.py`;
> 세션 = top-tier 오케스트레이터. Resume 시 "필요 세션 산출물"이 없으면 해당
> 세션 단계를 다시 수행한 뒤 계속한다.

| Phase | Name | Executor / tier | Output artifacts | Gate | 필요 세션 산출물 (resume) |
|---|---|---|---|---|---|
| 0 | SETUP | orchestrate.py — | worktree + `artifactDir` (`.omx/artifacts/orchestrate/<ts>/`) | hard: 실패 시 중단 | — |
| — | PREFLIGHT | 세션 (SKILL.md) | 세션 기록 | top-tier 확인, config resolve, 엔진 존재 | — |
| — | LANE PREFLIGHT | pi_runner smoke (free tier) | `<artifactDir>/lane-health.json` | tool-call smoke 통과 모델만 implement 투입 | artifactDir 존재 |
| 1 | EXPLORE | orchestrate.py (cheap tier 자식) | `explore-report.md` | hard | — |
| 2 | ROUTE+CLARIFY | 세션 (사용자 대화) | `route-decision.md`, `intent-summary.md`, `logs/phase-2-clarify.log` | interactive | `explore-report.md` |
| 3 | DESIGN | 세션 (top tier) | `design.md`, `logs/phase-3-design.log` | hard: implement 전 존재 필수 | `explore-report.md`, `intent-summary.md`, `route-decision.md` |
| 4 | VERIFY-DESIGN | orchestrate.py (opt-in 교차 top-tier 리뷰) | `design-review.md` | advisory (`--strict-review` 시 blocking) | Phase 3 산출물 |
| 4.5 | WRITE TESTS (Red) | 세션 (위임 금지) | `task-batches.md` (+JSON block), `test-manifest.md`, worktree 테스트 + `<artifactDir>/tests/` | hard: 테스트가 실패해야 함 (Red 확인) | `design.md` |
| 5 | IMPLEMENT (Green) | free-lane 자식 (detached) | `implement-task-N.out` (`EXIT_CODE=` sentinel) | 파일 소유권 경계, 테스트 파일 변경 금지 | `test-manifest.md` + 테스트 파일 |
| 5.5 | REVIEW GATE | 세션 | — | blocking: 테스트 Green + 스펙 대조 + 테스트 무결성 | Phase 5 산출물 |
| 6 | REVIEW+TEST | orchestrate.py (`--skip-codex-review`, LLM 없음) | `test-results.md` | 객관 테스트만. 실패 시 Phase 5 **1회** 자동 재시도 (`--is-retry --feedback`) | 모든 배치 5.5 통과 |
| 6a | DIFF REVIEW (opt-in) | diff_review_pi.py (top tier) | `<artifactDir>/reviews/<date>-<task>-pi-review.md` | advisory — exit 2–6 계약 | 작업 diff |
| 7 | COMPLETE | orchestrate.py | commit → detached merge worktree → merge main → push, `summary.json` | hard: Phase 6 `success`만 | `test-results.md` success |
| 8 | CLEANUP | orchestrate.py | `summary.json` 최종 | — | — |

## 재시도·중단 규칙

- 유일한 자동 복구: Phase 6 실패 → 해당 태스크 Phase 5 1회 재시도. 2회째 실패 시
  사용자 선택지 제시 (수동 수정 / 설계 회귀 / 커밋만 / 중단).
- `auth`/`window`/`credit` 분류 = 레인 폐쇄 (references/failure-classification.md §2).
  태스크 예산(1회)은 레인 내 모델 스왑으로 소진되지 않는다.
- 전체 무료 레인 소진 = Emergency Stop — 사용자 선택지 (유료 1회 승인 / 중단 /
  세션 top-tier 직접 구현). 자동 유료 승격 없음.
- auto-resume watcher 없음. 장기 중단은 `--resume <artifactDir>`로만 재개.
