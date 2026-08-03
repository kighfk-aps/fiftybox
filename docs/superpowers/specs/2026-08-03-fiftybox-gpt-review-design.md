# fiftybox-gpt-review 설계

**날짜:** 2026-08-03
**상태:** 승인됨

## 목적

설계·계획 마크다운 문서를 Codex의 GPT 모델에 보내 리뷰받고, 타당한 지적만 골라
원본 문서에 반영한 뒤 커밋하는 스킬을 만든다.

두 가지 형태로 제공한다.

- **독립 스킬** `/fiftybox-gpt-review <문서경로>` — 파이프라인과 무관하게 아무 spec/plan 문서에나 실행
- **파이프라인 통합** — `/fiftybox-orchestration` Phase 4(VERIFY-DESIGN)와 `/fiftybox-plans`
  Phase 5의 opt-in 리뷰어로 codex/GPT를 선택 가능하게 (기본은 지금처럼 skip 유지)

## 배경 사실

설계 시점에 확인한 것:

- **Codex는 이 맥에서 전역 차단돼 있다.** `/opt/homebrew/bin/codex`는 2026-07-27에 설치된
  shim이고 무조건 exit 1이다. 실제 바이너리(`/opt/homebrew/Caskroom/codex/0.144.1/bin/codex`)와
  자격 증명(`~/.codex/auth.json`)은 보존돼 있다. 이 스킬을 쓰려면 shim을 걷어내야 한다.
- `brew upgrade`/`reinstall`이 심볼릭 링크를 복구하면서 shim을 되살릴 수 있다 —
  차단 여부 감지는 1회성 확인이 아니라 매 실행 프리플라이트여야 한다.
- 이 레포의 현 브랜치(`retire-codex-consolidate-skills`, 커밋 `09f5b2d`)는 하네스에서
  Codex를 걷어낸 상태다. 이 스킬은 그 결정을 **되돌리지 않는다.** 구현·탐색 경로는
  그대로 두고, 리뷰 용도로만 codex를 opt-in으로 다시 연다.
- 사용 가능한 GPT 모델 슬러그(`~/.codex/models_cache.json`, 2026-08-03 fetch):
  `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`.
  reasoning effort는 `low|medium|high|xhigh|max`(+ 5.6 계열은 `ultra`).
  캐시의 `client_version`은 0.146.0인데 설치된 cask는 0.144.1이다 — 캐시 대조를 통과해도
  바이너리가 슬러그를 거부할 수 있으므로 codex 자체의 실패도 별도로 처리해야 한다.
- `codex exec`의 유용한 플래그(0.144.1 확인):
  - 프롬프트 인자로 `-`를 주면 **stdin에서 읽는다**
  - `-o/--output-last-message <FILE>` — 최종 응답만 파일로 저장 (진행 로그와 분리)
  - `-s read-only` — 모델이 파일을 못 고치게 강제
  - `-c model_reasoning_effort=<effort>` — effort 지정
  - `--ephemeral` — 세션 파일을 디스크에 남기지 않음
  - `--ignore-user-config` — `~/.codex/config.toml`을 무시(인증은 CODEX_HOME 그대로 사용)
- `orchestrate.py`의 `run_design_review_agent()`(1663행)는 리뷰 에이전트를
  `config["explore_agent"]`로 **고정**한다. 리뷰어만 codex로 바꾸려면 플래그가 하나 필요하다.
- `phase_verify_design()`의 `reviewer_active` 판정(1706행)은 `provider AND model`을 요구한다.
  codex는 provider 개념이 없어서 이 조건을 완화해야 한다.

## 결정 사항

| 항목 | 결정 |
|---|---|
| 스킬 형태 | 새 스킬 `fiftybox-gpt-review` (SKILL.md + `scripts/gpt_review.py`) |
| 입력 | 문서 파일 경로. 대화 맥락에서 자동 추론하지 않는다 |
| 모델 선택 | 기본 `gpt-5.6-terra` / effort `high` 고정, `--model`·`--effort`로 오버라이드 |
| 반복 | 1회전 후 종료. 재리뷰는 사용자가 다시 호출 |
| 반영 주체 | Claude가 지적별 타당성을 검증해 자동 반영, 기각 항목은 이유와 함께 보고 |
| 결과물 | 원본 문서 제자리 수정 + 리뷰 로그 저장 + 자동 커밋 |
| 파이프라인 통합 | 기본 skip 유지. `--design-review-agent codex`로 opt-in |

## 아키텍처

```
/fiftybox-gpt-review <doc>
        │
        ├─ scripts/gpt_review.py         ← codex 호출 캡슐화 (결정적, 테스트 가능)
        │     preflight → 모델 검증 → codex exec → 리뷰 로그 저장 → JSON 요약
        │
        └─ Claude (SKILL.md 지시)         ← 판단이 필요한 부분만 담당
              리뷰 로그 판독 → 항목별 검증 → 문서 수정 → 반영 결과 기록 → 커밋

/fiftybox-orchestration --design-review-agent codex --design-review-model gpt-5.6-terra
        └─ orchestrate.py run_design_review_agent() → BUILTIN_AGENTS["codex"]
```

경계: 스크립트는 **판단하지 않는다**(호출·검증·저장만). Claude는 **codex를 직접 호출하지
않는다**(스크립트를 통해서만). 이 분리 덕에 실패 경로를 테스트로 못 박을 수 있다.

## 컴포넌트 1: `scripts/gpt_review.py`

```
python3 gpt_review.py --doc <path>
                     [--model gpt-5.6-terra] [--effort high]
                     [--context <path> ...] [--timeout 900] [--out docs/reviews]
```

### 동작 순서

1. **codex 프리플라이트**
   `shutil.which("codex")`로 찾은 파일을 읽어 `Codex shutout shim` 마커가 있으면 차단 상태로
   판정한다. 실행해서 판별하지 않는다(shim도 실패한 codex도 똑같이 exit 1이라 구분 불가).
   차단이면 되살리기 명령 두 줄을 그대로 출력하고 **exit 3**.
   codex가 아예 없으면 같은 exit 3에 "설치 필요" 메시지.

2. **모델 검증**
   `~/.codex/models_cache.json`의 `models[].slug`와 대조. 목록에 없으면 사용 가능한 슬러그를
   나열하고 **exit 4**. 캐시 파일이 없거나 파싱 실패면 검증을 건너뛰고 stderr 경고만 남긴 뒤
   진행한다(오프라인·신규 설치에서 막히지 않게).

3. **프롬프트 조립**
   대상 문서 본문과 `--context` 파일들을 프롬프트에 **인라인으로** 넣는다. codex가 저장소를
   뒤지게 하지 않는다 — 읽을 것만 정확히 줘야 리뷰가 재현 가능해진다.
   출력 형식 지시(아래 "리뷰 계약")를 프롬프트 앞에 붙인다.

4. **리뷰 실행**

   ```bash
   codex exec --model <slug> \
              -c model_reasoning_effort=<effort> \
              -s read-only --ephemeral --skip-git-repo-check \
              --ignore-user-config \
              -o <tmp>/review.txt -
   # 프롬프트는 stdin
   ```

   `--ignore-user-config`로 전역 `config.toml`의 `model`·`developer_instructions`(oh-my-codex
   오케스트레이션 지시문) 영향을 끊는다 — 리뷰어에게는 노이즈다. 인증은 그대로 동작한다.
   `-s read-only`는 리뷰어가 파일을 고칠 수 없다는 걸 프롬프트가 아니라 **샌드박스로** 보장한다.
   타임아웃 초과는 **exit 5**, codex 비정상 종료는 **exit 6**(stderr 마지막 부분을 함께 출력).

5. **리뷰 로그 저장**
   `<out>/YYYY-MM-DD-<doc-slug>-gpt-review.md`에 저장한다. `<doc-slug>`는 대상 문서
   파일명(확장자 제외). 같은 날 같은 문서를 다시 리뷰하면 `-2`, `-3` 접미사를 붙여
   **덮어쓰지 않는다**(1회전 규칙상 재실행은 사용자의 의도적 재리뷰이므로 이력이 남아야 한다).

   ```markdown
   # GPT Review — <doc filename>

   - 대상: <doc path>
   - 모델: <slug> (effort: <effort>)
   - 시각: <ISO8601>
   - 판정: <VERDICT>

   ## 리뷰 원문

   <codex 응답 그대로>
   ```

6. **stdout JSON**

   ```json
   {"ok": true, "docPath": "...", "reviewPath": "...",
    "model": "gpt-5.6-terra", "effort": "high", "verdict": "REVISE"}
   ```

   `verdict`는 리뷰 첫 줄에서 `APPROVED|REVISE|BLOCKED`를 파싱한다(기존 `plan-review.md`
   규약과 동일). 형식을 벗어나면 `UNKNOWN`.

### exit code

| code | 의미 |
|---|---|
| 0 | 리뷰 성공 |
| 2 | 인자 오류 (문서 없음 등) |
| 3 | codex 사용 불가 (shim 차단 / 미설치) |
| 4 | 알 수 없는 모델 슬러그 |
| 5 | 타임아웃 |
| 6 | codex 실행 실패 |

exit≠0이면 Claude는 **문서를 손대지 않고** 메시지를 그대로 보고하고 멈춘다.
반쯤 반영된 문서를 남기지 않는 것이 이 규칙의 목적이다.

## 컴포넌트 2: 리뷰 계약 (프롬프트)

GPT에게 요구하는 출력 형식:

```
첫 줄: APPROVED | REVISE | BLOCKED
이후: 지적 항목 목록. 각 항목은
  - [severity: blocking|major|minor] 한 줄 요약
  - 근거: 문서의 어느 부분이 왜 문제인지
  - 제안: 구체적으로 무엇을 어떻게 바꿀지
```

리뷰 관점(프롬프트에 고정):

- 빠진 단계, 검증되지 않은 가정
- 실패·롤백 경로 누락
- 테스트 적정성
- 인터페이스·모듈 경계의 모호함
- **다른 에이전트가 이 문서만 보고 실행 가능한가**

범위 밖(명시적으로 제외): 코드 스타일, 문서 문체, 이 문서가 다루지 않는 기능 제안.

## 컴포넌트 3: Claude의 반영 규칙 (SKILL.md)

- 항목별로 **검증 후** 반영한다. 문서에 이미 있는 내용을 못 본 지적, 이 레포의 실제 코드나
  규약과 어긋나는 지적은 기각한다. 근거를 확인하려면 해당 파일을 직접 읽는다.
- blocking 항목을 기각할 때는 반드시 이유를 보고한다. minor는 문서 의도를 흐리면 기각 가능.
- 기존 구조·문체를 유지한 채 **최소 편집**한다. 문서를 통째로 다시 쓰지 않는다.
- 판정이 `BLOCKED`면 문서를 고치지 않고 무엇이 막혔는지 보고한 뒤 사용자 판단을 기다린다.
  설계 자체를 다시 해야 하는 상황이라 자동 수정이 오히려 해롭다.
- 반영을 마치면 리뷰 로그 하단에 `## 반영 결과` 섹션을 덧붙인다:
  반영한 항목, 기각한 항목과 그 이유.

### 커밋

문서 + 리뷰 로그를 함께 스테이징해 한 커밋으로 남긴다.

```
docs: apply GPT review feedback to <doc-name>

Reviewed by <model> (<effort>) — verdict <VERDICT>
Applied: N items / Rejected: M items
```

판정이 `APPROVED`라 수정할 게 없으면 리뷰 로그만 커밋한다.

## 컴포넌트 4: 파이프라인 통합

`orchestrate.py` 변경(최소 범위, 기본 동작 불변):

1. `BUILTIN_AGENTS`에 codex 추가:

   ```python
   "codex": {"cmd": ["codex", "exec", "--model", "{model}",
                     "-s", "read-only", "--ephemeral", "--skip-git-repo-check",
                     "--ignore-user-config", "{prompt}\n{task}"]},
   ```

   `{provider}` 토큰은 쓰지 않는다 — codex에는 provider 개념이 없다.
   `--ignore-user-config`는 독립 스킬과 같은 이유(전역 `developer_instructions` 노이즈 차단)로
   붙인다. effort는 이 경로에서 지정하지 않고 codex 기본값을 쓴다 — 에이전트 템플릿에
   effort 변수가 없고, 이를 위해 템플릿 문법을 확장하는 건 이 작업 범위를 넘는다.

2. `--design-review-agent <name>` 플래그 추가. 값이 있으면 `run_design_review_agent()`가
   `config["explore_agent"]` 대신 그 에이전트를 쓴다. 미지정 시 현행 동작 그대로 —
   기존 GLM 사용법과 `--resume` 호환성이 깨지지 않는다.

3. `reviewer_active` 판정을 `(provider AND model) OR (agent AND model)`로 완화한다.
   이 한 줄이 통합의 핵심이므로 테스트로 못 박는다.

4. `fiftybox-orchestration/SKILL.md` Phase 4와 `fiftybox-plans/SKILL.md` Phase 5의
   "Codex is retired" 문구를 갱신한다. 기본은 여전히 skip, opt-in 선택지가
   GLM(`--design-review-provider zai-coding --design-review-model glm-5.2`)과
   codex(`--design-review-agent codex --design-review-model gpt-5.6-terra`) 둘로 늘어난다.

사용 예:

```bash
python3 orchestrate.py --phase verify-design \
  --design-review-agent codex --design-review-model gpt-5.6-terra ...
```

## 테스트

`gpt_review.py` 단위 — codex 호출은 PATH 앞에 세운 가짜 실행 파일로 스텁 처리한다:

- shim 감지 → exit 3, codex 미설치 → exit 3
- 미지의 모델 슬러그 → exit 4 (+ 사용 가능 목록 출력)
- 캐시 파일 없음 → 경고 후 정상 진행
- verdict 파싱: `APPROVED` / `REVISE` / `BLOCKED` / 형식 이탈 → `UNKNOWN`
- 리뷰 로그 파일명·헤더, 같은 날 재실행 시 `-2` 접미사
- codex 비정상 종료 → exit 6, 타임아웃 → exit 5

`orchestrate.py` 통합:

- `--design-review-agent codex --design-review-model gpt-5.6-terra`가 codex 커맨드를
  조립하는지 (`build_agent_cmd` 결과 검증)
- 플래그 미지정 시 기존 경로가 그대로인지 (회귀 방지)
- `--design-review-agent`만 주고 model이 없으면 리뷰가 활성화되지 않는지

설치:

- `tests/test_install.sh`에 `fiftybox-gpt-review` 설치 검증 추가

## 설치·배포

- `install.sh`에 `fiftybox-gpt-review` 블록 추가: `SKILL.md` + `scripts/*.py`를
  `~/.claude/skills/fiftybox-gpt-review/`로 복사 (기존 스킬 블록과 동일 패턴)
- `commands/fiftybox-gpt-review.md` 슬래시 커맨드 추가

## 선행 작업 (1회)

codex 차단 해제:

```bash
rm /opt/homebrew/bin/codex
ln -s /opt/homebrew/Caskroom/codex/0.144.1/bin/codex /opt/homebrew/bin/codex
```

이후 `brew upgrade`가 shim을 되살릴 수 있으나, 스크립트의 프리플라이트가 매 실행마다
감지해 exit 3으로 안내하므로 조용히 실패하지 않는다.

## 범위 밖

- 구현·탐색 경로의 Codex 복귀 (실행은 opencode-go / 로컬 모델 그대로)
- 다중 모델 교차 리뷰
- 2회전 이상의 리뷰-반영 루프
- 코드 리뷰 (이 스킬은 설계·계획 **문서** 전용)
