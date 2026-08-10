# orchestrate.py 소유권 오탐·머지 기준 수정 설계

날짜: 2026-08-10
상태: 승인됨

## 목적

`orchestrate.py`의 두 가지 결함을 고친다. 둘 다 2026-08-10 cc-execute GPT diff
리뷰 구현 중 실제로 파이프라인을 멈춰 세웠다.

1. **소유권 오탐** — Claude가 Red 페이즈에서 이미 추적 중인 테스트 파일을 수정하면,
   구현 에이전트가 그 파일을 건드리지 않았어도 implement 페이즈가
   `agent modified files outside declared ownership`으로 실패한다.
2. **stale main 푸시 실패** — 머지 기준이 로컬 `main`인데 푸시 대상은
   `origin/main`이다. 로컬 main이 뒤처져 있으면 커밋과 머지를 모두 끝낸 뒤
   마지막 push에서 non-fast-forward로 거부된다.

`orchestrate.py` 한 파일만 바꾼다. 이 스크립트는 `fiftybox-orchestration`,
`fiftybox-cc-execute`, `fiftybox-execute`, `fiftybox-free-execute` 네 스킬이
공유하므로 파급 범위가 넓다 — 기존 호출 계약을 깨지 않는 것이 제약이다.

## 조사 결과 (실측)

- 리포의 `skills/fiftybox-orchestration/scripts/orchestrate.py`와 설치본
  `~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py`는 동일하다
  (`install.sh`가 복사). 스크립트만 고치면 양쪽에 반영된다
- `changed_files(root, before_files)` (`scripts/orchestrate.py:900`)는 untracked
  파일만 `repo_snapshot(root) - before_files`로 걸러낸다. **추적 파일의 수정은
  `git diff --name-only`와 `--cached`를 그대로 쓴다** — 기준선 대비가 없다
- 그래서 실행 전부터 더러운 추적 파일은 언제나 "이번 실행이 바꾼 파일"로 보고된다.
  새로 만드는 파일은 스냅샷 시점에 untracked라 걸러지므로 문제가 없다 —
  **기존 추적 파일을 고칠 때만** 터진다
- 소유권 검사는 `_implement_sequential` (`:2050` 부근)에서
  `task_changed = changed_files(worktree, before_files)` 결과로 판정한다
- implement가 `failed`로 기록되면 `PHASE_DEPS`에 따라 `review-test`가
  `Unmet dependencies`로 막혀 파이프라인 전체가 멈춘다
- `phase_complete` (`:2586`)는 `git worktree add --detach <path> main`으로 **로컬
  main**에서 머지 워크트리를 만들고, `git push origin HEAD:main`으로 **원격**에
  민다. 두 ref가 다르다
- 머지 워크트리는 `if not merge_worktree.exists()`로 재사용된다 — 이전 실패의
  잔재가 낡은 기준 그대로 다시 쓰인다
- `phase_pi_complete`는 `git push -u origin HEAD`로 **브랜치**를 민다. 이 설계와
  무관하다
- 테스트 기반: `skills/fiftybox-orchestration/tests/test_orchestrate.py` 140개.
  `_sandbox_repo()` (`:1744`)가 이미 bare origin + clone + 워크트리를 만든다 —
  로컬 경로 원격이라 `fetch`/`push`가 네트워크 없이 실제로 동작한다
- 기존 테스트 4곳이 `changed_files`를 `fake(_root, _before)` 시그니처로 패치한다
  (`:874`, `:927`, `:995` 부근). 인자를 늘리면 함께 고쳐야 한다

## 이슈 1 — 내용 해시 기준선

`changed_files()`는 "워크트리가 지금 더러운 파일"을 반환하는데 호출부는 "이번
실행이 바꾼 파일"로 해석한다. 이 간극을 없앤다.

### `dirty_baseline(root) -> dict[str, str]` (신규)

실행 직전, HEAD와 다른 **추적 파일**의 경로 → 워킹트리 blob 해시를 기록한다.

- 경로 수집: `git diff --name-only` ∪ `git diff --cached --name-only`
- 해시: `git hash-object -- <paths>` 일괄 호출 (더러운 파일 수는 보통 한 자릿수)
- 워킹트리에 없는 경로(삭제됨)는 `MISSING` 센티널
- 깨끗한 리포는 `{}`

untracked 파일은 담지 않는다 — 그쪽은 `repo_snapshot`이 이미 처리한다.

### `changed_files(root, before_files=None, before_dirty=None)`

- 후보 = (지금 더러운 경로) **∪** (`before_dirty`의 경로)
- 각 후보의 현재 해시를 구해 기준선 값과 비교해 **다를 때만** changed로 친다.
  기준선에 없던 경로는 항상 changed
- untracked 처리는 기존과 동일: `repo_snapshot(root) - before_files`
- `before_dirty=None`이면 기존 동작 그대로 — 하위 호환

**후보에 기준선 경로를 합집합으로 넣는 이유:** 에이전트가 Claude의 Red 편집을
되돌려 파일이 HEAD와 같아지면 그 경로는 `git diff`에서 사라진다. 현재 더러운
목록만 보면 이 경우를 놓치는데, 이건 정확히 스킬이 잡으려는 TDD 위반(`cmd`가
테스트 파일을 되돌림)이다. 기준선 경로를 후보에 넣어 "더러움 → 깨끗함" 전이도
변경으로 잡는다.

### 호출부

`_implement_sequential`(`:1973`)과 `phase_implement`(`:2314`) 두 곳에서
`before_files = repo_snapshot(worktree)` 옆에 `before_dirty = dirty_baseline(worktree)`를
추가하고, 이후 `changed_files(worktree, before_files, before_dirty)`로 호출한다.
타임아웃 경로의 `timeout_changed`(`:2010`)도 같은 인자를 받는다.

### 버린 대안

**경로 집합만 빼기** — 실행 전 더러운 경로를 결과에서 제거하는 방식. 구현은
짧지만 이미 더러운 파일을 에이전트가 실제로 망가뜨려도 마스킹된다. 지금의 오탐은
없애면서 진짜 위반을 놓치므로 기각.

## 이슈 2 — 머지 기준을 푸시 대상과 일치시킨다

### ① 원격 사전 검사 — 커밋 *전*

`review_test` 게이트 직후, `git add` 이전에 넣는다. 현재는 커밋·머지를 모두 마친
뒤 push에서 거부돼 고아 머지 커밋이 남는다. 검사를 앞으로 당기면 워크트리는
손대지 않은 상태로 멈춘다.

- `git remote get-url origin` 실패 → **원격 없는 리포**. `mergeRef = "main"`,
  푸시 생략, 정상 진행
- 원격 있음 → `git fetch origin`. 실패하면 `phases.complete = "fetch_failed"`로
  **커밋 전에 중단**
- fetch 성공 → `mergeRef = "origin/main"`. 단 `git rev-parse --verify origin/main`이
  실패하면(빈 원격, 아직 main을 민 적 없음) `mergeRef = "main"`으로 떨어뜨리고
  푸시는 그대로 시도한다 — 첫 푸시 시나리오다

### ② 머지 워크트리를 `mergeRef`에서 뜬다

`git worktree add --detach <path> <mergeRef>`.

이미 존재하면(이전 실패의 잔재) 머지 진행 중이 아닐 때만
`git checkout --detach <mergeRef>`로 기준을 갱신한다. `MERGE_HEAD`가 있으면
사용자가 충돌을 해결하는 중이므로 건드리지 않고 로그만 남긴다.

### ③ 머지 성공 후 로컬 main fast-forward

머지가 성공한 뒤(원격이 있으면 푸시까지 성공한 뒤) 두 조건을 모두 만족할 때
`git branch -f main <merged>`:

- 어느 워크트리에서도 `main`이 체크아웃돼 있지 않고
  (`git worktree list --porcelain`에 `branch refs/heads/main`이 없음)
- `git merge-base --is-ancestor main <merged>`가 참 — 진짜 fast-forward

**건너뛴 경우의 처리는 원격 유무로 갈린다:**

- **원격 있음** — `origin/main`에 이미 작업이 올라갔으므로 **경고만** 남기고
  성공으로 끝낸다. 로컬 main 갱신 실패가 이미 푸시된 작업을 실패로 만들어선 안 된다
- **원격 없음** — 푸시가 없었으므로 로컬 main이 유일한 도착지다. 갱신하지 못하면
  머지 커밋은 아무 브랜치도 가리키지 않는 고아가 되고 main은 그대로다. 이때는
  `local_main_blocked`로 **실패** 처리한다. 작업 자체는 작업 브랜치에 남아 있고
  cleanup의 `git branch -d`는 머지되지 않은 브랜치를 거부하므로 유실되지 않는다

원격 없는 리포에서 머지 기준이 로컬 main이라는 점 때문에, 이 경우 FF는 거의 항상
성립한다 — 성립하지 않는 유일한 경우가 main 체크아웃 중일 때다.

### 결과 JSON

성공 출력에 필드를 더한다: `mergeRef`, `pushed`(bool), `localMainUpdated`(bool),
건너뛴 경우 `localMainSkipReason`(문자열). 기존 `status`·`mergedCommit`·
`artifactDir`은 그대로다.

### 테스트 가능하게 분리할 헬퍼

- `resolve_merge_ref(root) -> tuple[str | None, bool, str]` — (ref, pushable, error).
  ref가 `None`이면 중단
- `main_is_checked_out(root) -> bool`
- `fast_forward_local_main(root, commit) -> str | None` — `None`이면 갱신됨,
  문자열이면 건너뛴 사유
- `refresh_merge_worktree(merge_worktree, merge_ref) -> tuple[str, str]` —
  `("refreshed" | "in_progress" | "failed", detail)`. 낡은 머지 워크트리를
  `merge_ref`로 다시 detach하되 `MERGE_HEAD`가 있으면 `in_progress`로 보존한다

### 버린 대안

**푸시 거부 시 fetch + rebase 자동 재시도** — 동시 푸시 경합까지 떠안게 되고,
리베이스 실패 시 복구가 더 어렵다. 경합은 지금처럼 보고만 한다.

## 테스트

`_sandbox_repo()`를 재사용한다. bare origin이 로컬 경로라 네트워크가 필요 없다.

### 이슈 1

`dirty_baseline`:
- 추적 파일 수정 → 경로와 워킹트리 해시가 담긴다
- 스테이징된 수정 → 포함
- untracked 파일 → 제외
- 삭제된 추적 파일 → `MISSING` 센티널
- 깨끗한 리포 → `{}`

`changed_files` + `before_dirty`:
1. 실행 전부터 더럽고 그대로인 파일 → 제외 (**이번 오탐의 회귀 테스트**)
2. 더러운 파일을 추가로 수정 → 포함
3. 더러운 파일을 HEAD 내용으로 되돌림 → 포함 (합집합 케이스)
4. 깨끗한 파일을 실행 중 수정 → 포함
5. 실행 중 만든 untracked → 포함
6. 실행 전부터 있던 untracked → 제외
7. `before_dirty=None` → 기존 동작 유지

소유권 검사 통합: 기존 패치 테스트 4곳을 새 시그니처로 갱신하고, "실행 전 더러운
추적 파일이 소유권 위반을 유발하지 않는다" 테스트를 1개 추가한다.

### 이슈 2

- **stale main 회귀 테스트**: 두 번째 클론에서 origin에 커밋을 밀어 로컬 main을
  뒤처지게 만든 뒤 `phase_complete`가 rc 0을 내고 origin/main에 작업이 올라가는지.
  현재 코드로는 실패하는 시나리오다
- 원격 없는 리포 → `resolve_merge_ref`가 `("main", False, "")`, 푸시 생략, rc 0
- fetch 실패(깨진 origin URL) → 커밋 **전** 중단. 워크트리에 새 커밋이 없음을 단정
- 낡은 머지 워크트리 재사용 → 기준이 `mergeRef`로 갱신된다.
  `MERGE_HEAD`가 있으면 보존된다
- FF: 정상 갱신 / main 체크아웃 중 → 건너뛰고 사유 / 분기(non-FF) → 건너뛰고 사유.
  세 경우 모두 rc 0

### 회귀

- `python3 -m pytest skills/fiftybox-orchestration/tests -q` 전부 통과
- `tests/*.sh` 기존 상태 유지 (`test_9b_spec_smoke.sh`는 `skills/fiftybox-local/`
  부재로 이 브랜치에서 이미 실패 중 — 이 설계의 범위 밖이다)

## 넣지 않는 것 (YAGNI)

- `phase_pi_complete` 변경 — 브랜치를 밀므로 이 결함과 무관하다
- 푸시 경합 시 자동 rebase 재시도
- `pending_files`·민감 파일 필터·커밋 메시지 형식 변경
- 스킬 `SKILL.md` 문서 변경 — 2026-08-10 실행에서 쓴 우회(테스트 파일을 태스크
  `files`에 선언)는 아티팩트에만 있었고 문서에 남기지 않았다. 이 수정 뒤에는 우회
  자체가 불필요해진다
- `install.sh` 변경 — `orchestrate.py` 한 파일만 바뀐다
- 소유권 위반 메시지에 마스킹 경고 필드 추가 — 해시 비교가 정확하므로 별도 신호가
  필요 없다
