# 로컬 모델 설정 분리 설계

**날짜:** 2026-06-13  
**목표:** 맥미니 로컬 GPU 모델 설정을 공개 GitHub 리포에서 격리

---

## 문제

`.gitignore`의 `skills/fiftybox-local*/` 패턴은 디렉토리만 커버한다.
`skills/fiftybox-local.md`, `skills/fiftybox-local-execute.md` 같은 평면 `.md` 파일은 패턴 밖이라
`git add .` 한 번에 실수로 공개될 수 있다.

---

## 설계

### 변경 1: `.gitignore` 패턴 보완

```diff
  commands/fiftybox-local*.md
  skills/fiftybox-local*/
+ skills/fiftybox-local*.md
```

`skills/fiftybox-local*.md` 추가로 평면 파일까지 커버한다.

### 변경 2: `fiftybox-local/SKILL.md` 모델 설정 업데이트

탐색(Phase 1)을 현재 Gemma 4 26B에서 9B 모델로 교체하고,  
구현(Phase 5)은 기존 27B 기본값을 유지·명시한다.

| 단계 | 현재 | 변경 후 |
|------|------|---------|
| Phase 1 EXPLORE | Gemma 4 26B A4B | 9B 모델 |
| Phase 5 IMPLEMENT (기본) | Qwen3 27B | 27B 모델 (유지) |
| Phase 5 IMPLEMENT (대형) | Qwen3 35B | 27B 모델로 통일 |
| Phase 6/7 (스크립트) | 해당 없음 | 해당 없음 |

Phase 6 REVIEW+TEST, Phase 7 COMPLETE는 `orchestrate.py` 스크립트로 실행되므로
별도 모델 설정이 필요 없다.

### 변경 3: `select_remote_model.sh`에 `9b` 별칭 추가

`fiftybox-local/scripts/select_remote_model.sh`가 `gemma4`, `27b`, `35b` 별칭을 지원하는 것처럼
`9b` 별칭을 추가해 `FIFTYBOX_EXPLORE_MODEL_CHOICE=9b`가 동작하게 한다.

---

## 보장

- `git push` 후 GitHub에 로컬 모델 IP, 스크립트 경로, 모델 ID가 노출되지 않는다.
- `git add .` 실수에도 `skills/fiftybox-local*.md`가 스테이지되지 않는다.
- 맥미니에서 `/fiftybox-local`를 실행하면 탐색은 9B, 구현은 27B로 동작한다.

---

## 범위 외

- `select_remote_model.sh`가 9B 모델 컨테이너를 시작하는 실제 스크립트 경로는
  구현 단계에서 확인한다 (사용자가 서버 스크립트를 이미 보유하고 있다고 가정).
- Phase 3 DESIGN(Opus), Phase 5.5 CLAUDE REVIEW GATE(Claude 직접 실행)는 이 설계에서 변경하지 않는다.
