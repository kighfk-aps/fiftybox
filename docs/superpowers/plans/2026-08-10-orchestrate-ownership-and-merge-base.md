# orchestrate 소유권 오탐·머지 기준 수정 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `changed_files`가 이번 실행이 실제로 바꾼 파일만 보고하게 만들고, `phase_complete`의 머지 기준을 푸시 대상과 같은 ref로 맞춘다.

**Architecture:** `orchestrate.py` 한 파일에 순수 헬퍼를 추가하고 기존 호출부를 그 헬퍼로 갈아끼운다. 새 동작은 전부 선택적 인자(`before_dirty=None`) 또는 새 함수 뒤에 있어서, 기존 2인자 `changed_files` 호출은 그대로 동작한다. 판정 로직은 작은 함수로 떼어내 실제 git 저장소를 만드는 기존 `_sandbox_repo()` 테스트 하네스로 검증한다.

**Tech Stack:** Python 3 표준 라이브러리만(subprocess/pathlib), pytest, git CLI

## Global Constraints

- 스펙: `docs/superpowers/specs/2026-08-10-orchestrate-ownership-and-merge-base-design.md`
- 수정 대상은 `skills/fiftybox-orchestration/scripts/orchestrate.py`와 그 테스트 `skills/fiftybox-orchestration/tests/test_orchestrate.py` **두 파일뿐이다**
- 외부 의존성 추가 금지. Python 표준 라이브러리와 git CLI만 쓴다
- Python 코드 주석·docstring은 영어. 계획·스펙 문서는 한국어 (기존 리포지토리 관례)
- **하위 호환:** `changed_files(root, before_files)` 2인자 호출이 계속 동작해야 한다. 세 번째 인자는 기본값 `None`이고, `None`이면 기존 동작을 그대로 낸다
- `phase_pi_complete`, `pending_files`, `filter_sensitive_files`, 커밋 메시지 형식은 건드리지 않는다
- `install.sh`는 건드리지 않는다 (`orchestrate.py` 한 파일만 바뀐다)
- 이 스크립트는 `fiftybox-orchestration` / `fiftybox-cc-execute` / `fiftybox-execute` / `fiftybox-free-execute` 네 스킬이 공유한다. 기존 페이즈 계약을 깨지 않는다
- `tests/test_9b_spec_smoke.sh`는 `skills/fiftybox-local/` 부재로 이 브랜치에서 이미 실패 중이다. 이 계획의 범위 밖이며 고치지 않는다

---

## File Structure

| 파일 | 책임 |
|---|---|
| `skills/fiftybox-orchestration/scripts/orchestrate.py` | 신규 헬퍼(`working_hashes`, `dirty_baseline`, `resolve_merge_ref`, `main_is_checked_out`, `fast_forward_local_main`, `refresh_merge_worktree`) 추가, `changed_files` 확장, `_implement_sequential`·`phase_implement`·`phase_complete` 재배선 |
| `skills/fiftybox-orchestration/tests/test_orchestrate.py` | 새 헬퍼 단위 테스트, 실제 git 저장소 시나리오 테스트, 기존 `fake_changed_files` 4곳 시그니처 갱신 |

`orchestrate.py`는 이미 14만 자가 넘는 단일 파일이지만, 이 리포의 확립된 구조이고 이 계획의 변경은 국소적이다. 분할은 하지 않는다.

---

## Task 1: 내용 해시 기준선 (`working_hashes`, `dirty_baseline`, `changed_files`)

`codex`나 에이전트를 부르지 않는 순수 git 조회 계층을 먼저 만든다. 이 태스크가 끝나면 판정이 정확해지고, 배선은 Task 2에서 한다.

**Files:**
- Modify: `skills/fiftybox-orchestration/scripts/orchestrate.py` (`repo_snapshot` 바로 뒤, 현재 `:893-906`)
- Test: `skills/fiftybox-orchestration/tests/test_orchestrate.py`

**Interfaces:**
- Consumes: 기존 `run(cmd: list[str], cwd: Path) -> CompletedProcess[str]` (`:301`), `repo_snapshot(root: Path) -> set[str]` (`:893`)
- Produces:
  - `DIRTY_MISSING: str = "MISSING"`
  - `working_hashes(root: Path, paths: list[str]) -> dict[str, str]`
  - `dirty_baseline(root: Path) -> dict[str, str]`
  - `changed_files(root: Path, before_files: set[str] | None = None, before_dirty: dict[str, str] | None = None) -> list[str]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`skills/fiftybox-orchestration/tests/test_orchestrate.py` **맨 끝**에 덧붙인다. 파일 상단에는 이미 `json`, `subprocess`, `tempfile`, `patch`, `Path`, `sys`, `os`, `orchestrate`가 import 돼 있으므로 추가 import는 필요 없다.

```python
# ---------------------------------------------------------------------------
# dirty_baseline / changed_files — "이번 실행이 바꾼 파일"의 정확한 정의
#
# changed_files 는 워크트리가 지금 더러운 파일을 반환했고, 호출부는 그것을
# 이번 실행의 변경으로 해석했다. Red 페이즈에서 Claude 가 이미 추적 중인
# 테스트 파일을 고쳐두면 에이전트가 건드리지 않아도 소유권 위반이 났다.
# ---------------------------------------------------------------------------

def _plain_repo(base: Path) -> Path:
    """git 저장소 하나. tracked.txt 와 other.txt 가 커밋돼 있다."""
    root = base / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for key, value in (("user.email", "t@example.com"), ("user.name", "t")):
        subprocess.run(["git", "config", key, value], cwd=root, check=True)
    (root / "tracked.txt").write_text("base\n")
    (root / "other.txt").write_text("other\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True)
    return root


def test_dirty_baseline_records_modified_tracked_file():
    with tempfile.TemporaryDirectory() as tmp:
        root = _plain_repo(Path(tmp))
        (root / "tracked.txt").write_text("dirty\n")
        baseline = orchestrate.dirty_baseline(root)
        assert list(baseline) == ["tracked.txt"]
        assert len(baseline["tracked.txt"]) == 40


def test_dirty_baseline_includes_staged_modification():
    with tempfile.TemporaryDirectory() as tmp:
        root = _plain_repo(Path(tmp))
        (root / "tracked.txt").write_text("dirty\n")
        subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
        assert "tracked.txt" in orchestrate.dirty_baseline(root)


def test_dirty_baseline_ignores_untracked_files():
    with tempfile.TemporaryDirectory() as tmp:
        root = _plain_repo(Path(tmp))
        (root / "brand-new.txt").write_text("new\n")
        assert orchestrate.dirty_baseline(root) == {}


def test_dirty_baseline_marks_deleted_file_missing():
    with tempfile.TemporaryDirectory() as tmp:
        root = _plain_repo(Path(tmp))
        (root / "tracked.txt").unlink()
        assert orchestrate.dirty_baseline(root) == {"tracked.txt": orchestrate.DIRTY_MISSING}


def test_dirty_baseline_of_clean_repo_is_empty():
    with tempfile.TemporaryDirectory() as tmp:
        root = _plain_repo(Path(tmp))
        assert orchestrate.dirty_baseline(root) == {}


def test_working_hashes_is_unaffected_by_staging():
    """git add 는 색인만 바꾼다. 기준선은 스테이징을 건너뛰고 살아남아야 한다."""
    with tempfile.TemporaryDirectory() as tmp:
        root = _plain_repo(Path(tmp))
        (root / "tracked.txt").write_text("dirty\n")
        before = orchestrate.working_hashes(root, ["tracked.txt"])
        subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
        assert orchestrate.working_hashes(root, ["tracked.txt"]) == before


def test_changed_files_excludes_file_dirty_before_the_run():
    """이번 오탐의 회귀 테스트."""
    with tempfile.TemporaryDirectory() as tmp:
        root = _plain_repo(Path(tmp))
        (root / "tracked.txt").write_text("red phase edit\n")
        before_files = orchestrate.repo_snapshot(root)
        before_dirty = orchestrate.dirty_baseline(root)

        (root / "impl.txt").write_text("agent work\n")   # 에이전트가 만든 파일

        got = orchestrate.changed_files(root, before_files, before_dirty)
        assert got == ["impl.txt"]


def test_changed_files_includes_further_edit_to_a_dirty_file():
    with tempfile.TemporaryDirectory() as tmp:
        root = _plain_repo(Path(tmp))
        (root / "tracked.txt").write_text("red phase edit\n")
        before_files = orchestrate.repo_snapshot(root)
        before_dirty = orchestrate.dirty_baseline(root)

        (root / "tracked.txt").write_text("agent clobbered it\n")

        assert orchestrate.changed_files(root, before_files, before_dirty) == ["tracked.txt"]


def test_changed_files_detects_revert_of_a_dirty_file():
    """더러움 → 깨끗함 전이. cmd 가 Claude 의 Red 편집을 되돌린 경우다."""
    with tempfile.TemporaryDirectory() as tmp:
        root = _plain_repo(Path(tmp))
        (root / "tracked.txt").write_text("red phase edit\n")
        before_files = orchestrate.repo_snapshot(root)
        before_dirty = orchestrate.dirty_baseline(root)

        (root / "tracked.txt").write_text("base\n")   # HEAD 내용으로 복구

        assert orchestrate.changed_files(root, before_files, before_dirty) == ["tracked.txt"]


def test_changed_files_includes_clean_file_edited_during_the_run():
    with tempfile.TemporaryDirectory() as tmp:
        root = _plain_repo(Path(tmp))
        before_files = orchestrate.repo_snapshot(root)
        before_dirty = orchestrate.dirty_baseline(root)

        (root / "other.txt").write_text("agent work\n")

        assert orchestrate.changed_files(root, before_files, before_dirty) == ["other.txt"]


def test_changed_files_excludes_untracked_file_present_before_the_run():
    with tempfile.TemporaryDirectory() as tmp:
        root = _plain_repo(Path(tmp))
        (root / "scratch.txt").write_text("pre-existing\n")
        before_files = orchestrate.repo_snapshot(root)
        before_dirty = orchestrate.dirty_baseline(root)

        assert orchestrate.changed_files(root, before_files, before_dirty) == []


def test_changed_files_without_baseline_keeps_old_behavior():
    """before_dirty=None 은 기존 호출부의 계약이다."""
    with tempfile.TemporaryDirectory() as tmp:
        root = _plain_repo(Path(tmp))
        (root / "tracked.txt").write_text("dirty before\n")
        before_files = orchestrate.repo_snapshot(root)

        assert orchestrate.changed_files(root, before_files) == ["tracked.txt"]
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python3 -m pytest skills/fiftybox-orchestration/tests/test_orchestrate.py -q -k "dirty_baseline or working_hashes or changed_files"`
Expected: FAIL — `AttributeError: module 'orchestrate' has no attribute 'dirty_baseline'` (그리고 `working_hashes`, `DIRTY_MISSING` 부재). 마지막 `test_changed_files_without_baseline_keeps_old_behavior`만 통과한다.

- [ ] **Step 3: 헬퍼를 구현한다**

`skills/fiftybox-orchestration/scripts/orchestrate.py`에서 현재 `changed_files`(`:900-906`) 정의를 아래 블록으로 **통째로 교체**한다. `repo_snapshot`(`:893`)은 그대로 둔다.

```python
DIRTY_MISSING = "MISSING"


def _dirty_paths(root: Path) -> list[str]:
    """Tracked paths that differ from HEAD, staged or not."""
    paths: set[str] = set()
    for cmd in (["git", "diff", "--name-only"],
                ["git", "diff", "--cached", "--name-only"]):
        result = run(cmd, root)
        if result.returncode == 0:
            paths.update(line for line in result.stdout.splitlines() if line)
    return sorted(paths)


def working_hashes(root: Path, paths: list[str]) -> dict[str, str]:
    """path -> blob hash of the working-tree file; DIRTY_MISSING when absent.

    Hashing the working tree rather than the index is what lets a baseline
    survive `git add`: staging changes the index but not the file's content,
    and a baseline taken before an agent runs must still match afterwards if
    the agent only staged what was already there.
    """
    hashes: dict[str, str] = {}
    present = [p for p in paths if (root / p).is_file()]
    for path in paths:
        if path not in present:
            hashes[path] = DIRTY_MISSING
    if present:
        result = run(["git", "hash-object", "--"] + present, root)
        if result.returncode == 0:
            # git prints one hash per input path, in the order given.
            for path, line in zip(present, result.stdout.splitlines()):
                hashes[path] = line.strip()
    return hashes


def dirty_baseline(root: Path) -> dict[str, str]:
    """Content hashes of every tracked file that already differs from HEAD.

    Taken before an agent runs so that changed_files can tell the agent's
    edits apart from work that was already sitting in the worktree — the Red
    phase test edits the skill asks Claude to make, most of all. Untracked
    files are not included here; repo_snapshot already covers those.
    """
    return working_hashes(root, _dirty_paths(root))


def changed_files(root: Path, before_files: set[str] | None = None,
                  before_dirty: dict[str, str] | None = None) -> list[str]:
    """Files this run changed, as repo-relative paths.

    With before_dirty supplied, a tracked file counts as changed only when
    its content differs from the baseline. Candidates are the union of what
    is dirty now and what was dirty then: a file the agent reverted to its
    HEAD content disappears from `git diff` entirely, and that reversion is
    exactly the TDD violation the review gate exists to catch.
    """
    tracked = _dirty_paths(root)
    if before_dirty is None:
        changed = tracked
    else:
        candidates = sorted(set(tracked) | set(before_dirty))
        current = working_hashes(root, candidates)
        changed = [p for p in candidates
                   if current.get(p) != before_dirty.get(p)]
    untracked = sorted(repo_snapshot(root) - before_files) if before_files is not None else []
    return sorted(set(changed + untracked))
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python3 -m pytest skills/fiftybox-orchestration/tests/test_orchestrate.py -q -k "dirty_baseline or working_hashes or changed_files"`
Expected: PASS (12개)

- [ ] **Step 5: 커밋**

```bash
git add skills/fiftybox-orchestration/scripts/orchestrate.py \
        skills/fiftybox-orchestration/tests/test_orchestrate.py
git commit -m "feat(orchestrate): report only what a run actually changed"
```

---

## Task 2: 구현 페이즈 배선과 기존 테스트 갱신

Task 1의 기준선을 실제 소유권 검사에 연결한다. 기존 테스트가 `changed_files`를 2인자 시그니처로 패치하고 있어 함께 고쳐야 한다.

**Files:**
- Modify: `skills/fiftybox-orchestration/scripts/orchestrate.py` (`_implement_sequential` `:1973`·`:2010`·`:2044`, `phase_implement` `:2314`·`:2345`)
- Test: `skills/fiftybox-orchestration/tests/test_orchestrate.py` (`:874`, `:927`, `:995`, `:1083`의 `fake_changed_files` 4곳)

**Interfaces:**
- Consumes: Task 1의 `dirty_baseline(root) -> dict[str, str]`, `changed_files(root, before_files, before_dirty)`
- Produces: 없음 (내부 배선)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`skills/fiftybox-orchestration/tests/test_orchestrate.py` **맨 끝**에 덧붙인다.

```python
def test_pre_existing_dirty_tracked_file_is_not_an_ownership_violation():
    """2026-08-10 cc-execute 실패의 회귀 테스트.

    Claude 가 Red 페이즈에서 추적 중인 테스트 파일을 고쳐두면, 에이전트가
    자기 소유 파일만 건드려도 implement 가 소유권 위반으로 죽었다.
    """
    with tempfile.TemporaryDirectory() as tmp:
        artifact_dir = Path(tmp) / "art"
        (artifact_dir / "logs").mkdir(parents=True)
        (artifact_dir / "summary.json").write_text(json.dumps({
            "worktree": str(Path(tmp) / "wt"),
            "branch": "feature/sim",
            "phases": {"setup": {"status": "success"}},
        }))
        (artifact_dir / "design.md").write_text("# design\n")
        (artifact_dir / "task-batches.md").write_text(
            "```json\n" + json.dumps({"tasks": [{
                "name": "Task A",
                "description": "edit only the owned file",
                "files": ["src/owned.py"],
            }]}) + "\n```\n"
        )
        (Path(tmp) / "wt").mkdir()

        args = orchestrate.parse_args([
            "--phase", "implement", "--task", "build feature",
            "--artifact-dir", str(artifact_dir), "--skip-verify",
        ])
        ok_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="Done.\n")

        with patch("orchestrate.run", return_value=ok_result), \
             patch("orchestrate.repo_snapshot", return_value=set()), \
             patch("orchestrate.dirty_baseline",
                   return_value={"tests/test_doc.sh": "aaaa"}), \
             patch("orchestrate.changed_files", return_value=["src/owned.py"]):
            rc = orchestrate.phase_implement(Path(tmp), artifact_dir, args)

        assert rc == 0
        summary = json.loads((artifact_dir / "summary.json").read_text())
        assert summary["phases"]["implement"]["status"] == "success"


def test_implement_passes_the_dirty_baseline_to_changed_files():
    """배선 검증: 기준선을 뜨고도 넘기지 않으면 오탐이 그대로 재발한다."""
    with tempfile.TemporaryDirectory() as tmp:
        artifact_dir = Path(tmp) / "art"
        (artifact_dir / "logs").mkdir(parents=True)
        (artifact_dir / "summary.json").write_text(json.dumps({
            "worktree": str(Path(tmp) / "wt"),
            "branch": "feature/sim",
            "phases": {"setup": {"status": "success"}},
        }))
        (artifact_dir / "design.md").write_text("# design\n")
        (Path(tmp) / "wt").mkdir()

        args = orchestrate.parse_args([
            "--phase", "implement", "--task", "build feature",
            "--artifact-dir", str(artifact_dir), "--skip-verify",
        ])
        ok_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="Done.\n")
        seen = {}

        def spy_changed_files(_root, _before=None, _before_dirty=None):
            seen["baseline"] = _before_dirty
            return ["src/app.py"]

        with patch("orchestrate.run", return_value=ok_result), \
             patch("orchestrate.repo_snapshot", return_value=set()), \
             patch("orchestrate.dirty_baseline", return_value={"a.txt": "bbbb"}), \
             patch("orchestrate.changed_files", side_effect=spy_changed_files):
            orchestrate.phase_implement(Path(tmp), artifact_dir, args)

        assert seen["baseline"] == {"a.txt": "bbbb"}
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python3 -m pytest skills/fiftybox-orchestration/tests/test_orchestrate.py -q -k "dirty_baseline_to_changed_files or ownership_violation"`
Expected: FAIL — `test_implement_passes_the_dirty_baseline_to_changed_files`가 `KeyError: 'baseline'` 또는 `assert None == {...}`로 실패한다(배선 전이라 세 번째 인자가 넘어가지 않는다).

- [ ] **Step 3: 호출부 다섯 곳을 고친다**

**(a)** `_implement_sequential`, 현재 `:1972-1973`:

```python
        # Snapshot repo before this task
        before_files = repo_snapshot(worktree)
```

를 이렇게 바꾼다:

```python
        # Snapshot repo before this task. The hash baseline is what keeps a
        # file that was already dirty — a Red phase test edit, typically —
        # from being attributed to this agent.
        before_files = repo_snapshot(worktree)
        before_dirty = dirty_baseline(worktree)
```

**(b)** 같은 함수의 타임아웃 경로, 현재 `:2010`:

```python
            timeout_changed = changed_files(worktree, before_files)
```
→
```python
            timeout_changed = changed_files(worktree, before_files, before_dirty)
```

**(c)** 같은 함수, 현재 `:2044`:

```python
        task_changed = changed_files(worktree, before_files)
```
→
```python
        task_changed = changed_files(worktree, before_files, before_dirty)
```

**(d)** `phase_implement`, 현재 `:2314`:

```python
    before_files = repo_snapshot(worktree)
```
→
```python
    before_files = repo_snapshot(worktree)
    before_dirty = dirty_baseline(worktree)
```

**(e)** `phase_implement`, 현재 `:2345`:

```python
    all_changed = changed_files(worktree, before_files)
```
→
```python
    all_changed = changed_files(worktree, before_files, before_dirty)
```

- [ ] **Step 4: 기존 테스트의 페이크 4개를 갱신한다**

`skills/fiftybox-orchestration/tests/test_orchestrate.py`의 `:874`, `:927`, `:995`, `:1083`에 있는 `fake_changed_files` 정의를 전부 세 번째 인자를 받도록 고친다. 세 곳은 `(_root, _before)`, 한 곳은 `(_root, _before=None)`이지만 **네 곳 모두 아래 형태로 통일한다**:

```python
    def fake_changed_files(_root, _before=None, _before_dirty=None):
```

본문은 그대로 둔다.

같은 네 테스트의 `with patch(...)` 블록에 `dirty_baseline` 패치를 추가한다. 이 테스트들은 `orchestrate.run`을 통째로 패치하므로, 패치하지 않으면 `dirty_baseline`이 가짜 stdout(`"Done.\n"` 등)을 git 출력으로 파싱해 엉뚱한 경로를 만든다. 각 블록의 `patch("orchestrate.repo_snapshot", ...)` 줄 **바로 뒤**에 넣는다:

```python
         patch("orchestrate.dirty_baseline", return_value={}), \
```

- [ ] **Step 5: 전체 테스트 통과를 확인한다**

Run: `python3 -m pytest skills/fiftybox-orchestration/tests -q`
Expected: PASS. 이 시점의 총계는 기존 140개 + Task 1의 12개 + Task 2의 2개 = 154개.

- [ ] **Step 6: 커밋**

```bash
git add skills/fiftybox-orchestration/scripts/orchestrate.py \
        skills/fiftybox-orchestration/tests/test_orchestrate.py
git commit -m "fix(orchestrate): stop attributing pre-existing edits to the agent"
```

---

## Task 3: 머지 기준·로컬 main 헬퍼

`phase_complete`를 손대기 전에, 판정 로직을 따로 테스트할 수 있는 함수로 떼어낸다.

**Files:**
- Modify: `skills/fiftybox-orchestration/scripts/orchestrate.py` (Task 1이 만든 `changed_files` 블록 바로 뒤)
- Test: `skills/fiftybox-orchestration/tests/test_orchestrate.py`

**Interfaces:**
- Consumes: 기존 `run(cmd, cwd)`
- Produces:
  - `resolve_merge_ref(root: Path) -> tuple[str | None, bool, str]` — `(merge ref, pushable, error)`. ref가 `None`이면 중단
  - `main_is_checked_out(root: Path) -> bool`
  - `fast_forward_local_main(root: Path, commit: str) -> str | None` — `None`이면 갱신됨, 문자열이면 건너뛴 사유
  - `refresh_merge_worktree(merge_worktree: Path, merge_ref: str) -> tuple[str, str]` — `("refreshed" | "in_progress" | "failed", detail)`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`skills/fiftybox-orchestration/tests/test_orchestrate.py` **맨 끝**에 덧붙인다. `_sandbox_repo()`는 이미 이 파일 `:1744`에 있고 bare origin + clone + 워크트리를 만든다. 원격이 로컬 경로라 `fetch`/`push`가 네트워크 없이 실제로 동작한다.

```python
# ---------------------------------------------------------------------------
# 머지 기준 — 머지하는 ref 와 미는 ref 가 같아야 한다
#
# phase_complete 는 로컬 main 에서 머지 워크트리를 뜨고 origin/main 으로 밀었다.
# 로컬 main 이 뒤처져 있으면 커밋과 머지를 다 마친 뒤 push 가 거부됐다.
# ---------------------------------------------------------------------------

def _push_extra_commit_to_origin(base: Path) -> None:
    """다른 클론에서 origin/main 을 앞서게 만든다 — 로컬 main 이 뒤처지는 상황."""
    other = base / "other"
    subprocess.run(["git", "clone", "-q", str(base / "origin.git"), str(other)], check=True)
    for key, value in (("user.email", "t@example.com"), ("user.name", "t")):
        subprocess.run(["git", "config", key, value], cwd=other, check=True)
    (other / "remote-only.txt").write_text("remote work\n")
    subprocess.run(["git", "add", "-A"], cwd=other, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "remote work"], cwd=other, check=True)
    subprocess.run(["git", "push", "-q", "origin", "main"], cwd=other, check=True)


def _solo_repo(base: Path) -> tuple[Path, Path]:
    """원격 없는 저장소. root 는 parked 브랜치에 있어 main 이 비어 있다."""
    root = base / "solo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    for key, value in (("user.email", "t@example.com"), ("user.name", "t")):
        subprocess.run(["git", "config", key, value], cwd=root, check=True)
    (root / "tracked.txt").write_text("base\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True)
    worktree = root / ".worktrees" / "wt"
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "feature/sim", str(worktree), "main"],
        cwd=root, check=True,
    )
    subprocess.run(["git", "checkout", "-q", "-b", "parked"], cwd=root, check=True)
    return root, worktree


def test_resolve_merge_ref_uses_origin_main_when_a_remote_exists():
    with tempfile.TemporaryDirectory() as tmp:
        root, _worktree, _artifact_dir = _sandbox_repo(Path(tmp))
        assert orchestrate.resolve_merge_ref(root) == ("origin/main", True, "")


def test_resolve_merge_ref_falls_back_to_local_main_without_a_remote():
    with tempfile.TemporaryDirectory() as tmp:
        root, _worktree = _solo_repo(Path(tmp))
        assert orchestrate.resolve_merge_ref(root) == ("main", False, "")


def test_resolve_merge_ref_reports_a_fetch_failure():
    with tempfile.TemporaryDirectory() as tmp:
        root, _worktree, _artifact_dir = _sandbox_repo(Path(tmp))
        subprocess.run(
            ["git", "remote", "set-url", "origin", str(Path(tmp) / "gone.git")],
            cwd=root, check=True,
        )
        ref, pushable, error = orchestrate.resolve_merge_ref(root)
        assert ref is None
        assert pushable is True
        assert "fetch" in error


def test_resolve_merge_ref_uses_local_main_when_the_remote_has_no_main():
    """빈 원격에 처음 미는 경우 — 머지 기준은 로컬 main, 푸시는 시도한다."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        subprocess.run(["git", "init", "-q", "--bare", str(base / "empty.git")], check=True)
        root, _worktree = _solo_repo(base)
        subprocess.run(
            ["git", "remote", "add", "origin", str(base / "empty.git")],
            cwd=root, check=True,
        )
        assert orchestrate.resolve_merge_ref(root) == ("main", True, "")


def test_main_is_checked_out_detects_the_clone_root():
    with tempfile.TemporaryDirectory() as tmp:
        root, _worktree, _artifact_dir = _sandbox_repo(Path(tmp))
        assert orchestrate.main_is_checked_out(root) is True


def test_main_is_checked_out_false_when_parked_elsewhere():
    with tempfile.TemporaryDirectory() as tmp:
        root, _worktree = _solo_repo(Path(tmp))
        assert orchestrate.main_is_checked_out(root) is False


def test_fast_forward_local_main_moves_the_branch():
    with tempfile.TemporaryDirectory() as tmp:
        root, worktree = _solo_repo(Path(tmp))
        (worktree / "feature.txt").write_text("work\n")
        subprocess.run(["git", "add", "-A"], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "feature"], cwd=worktree, check=True)
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=worktree,
                              capture_output=True, text=True, check=True).stdout.strip()

        assert orchestrate.fast_forward_local_main(root, head) is None

        moved = subprocess.run(["git", "rev-parse", "main"], cwd=root,
                               capture_output=True, text=True, check=True).stdout.strip()
        assert moved == head


def test_fast_forward_local_main_skips_when_main_is_checked_out():
    with tempfile.TemporaryDirectory() as tmp:
        root, _worktree, _artifact_dir = _sandbox_repo(Path(tmp))
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                              capture_output=True, text=True, check=True).stdout.strip()
        assert orchestrate.fast_forward_local_main(root, head) == \
            "main is checked out in a worktree"


def test_fast_forward_local_main_skips_a_non_fast_forward():
    with tempfile.TemporaryDirectory() as tmp:
        root, worktree = _solo_repo(Path(tmp))
        # main 을 앞세워 두면 워크트리 커밋은 더 이상 FF 가 아니다.
        (root / "parked.txt").write_text("diverged\n")
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "diverge"], cwd=root, check=True)
        subprocess.run(["git", "branch", "-f", "main", "parked"], cwd=root, check=True)

        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=worktree,
                              capture_output=True, text=True, check=True).stdout.strip()
        reason = orchestrate.fast_forward_local_main(root, head)
        assert reason == "local main is not an ancestor of the merged commit"


def test_refresh_merge_worktree_re_detaches_onto_the_merge_ref():
    with tempfile.TemporaryDirectory() as tmp:
        root, _worktree, _artifact_dir = _sandbox_repo(Path(tmp))
        _push_extra_commit_to_origin(Path(tmp))
        subprocess.run(["git", "fetch", "-q", "origin"], cwd=root, check=True)

        merge_worktree = root / ".worktrees" / "merge"
        subprocess.run(
            ["git", "worktree", "add", "-q", "--detach", str(merge_worktree), "main"],
            cwd=root, check=True,
        )

        status, _detail = orchestrate.refresh_merge_worktree(merge_worktree, "origin/main")
        assert status == "refreshed"

        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=merge_worktree,
                              capture_output=True, text=True, check=True).stdout.strip()
        target = subprocess.run(["git", "rev-parse", "origin/main"], cwd=root,
                                capture_output=True, text=True, check=True).stdout.strip()
        assert head == target


def test_refresh_merge_worktree_leaves_an_in_progress_merge_alone():
    with tempfile.TemporaryDirectory() as tmp:
        root, _worktree, _artifact_dir = _sandbox_repo(Path(tmp))
        merge_worktree = root / ".worktrees" / "merge"
        subprocess.run(
            ["git", "worktree", "add", "-q", "--detach", str(merge_worktree), "main"],
            cwd=root, check=True,
        )
        # 충돌하는 두 브랜치를 만들어 MERGE_HEAD 를 남긴다.
        subprocess.run(["git", "checkout", "-q", "-b", "left"], cwd=merge_worktree, check=True)
        (merge_worktree / "tracked.txt").write_text("left\n")
        subprocess.run(["git", "commit", "-qam", "left"], cwd=merge_worktree, check=True)
        subprocess.run(["git", "checkout", "-q", "-b", "right", "main"], cwd=merge_worktree, check=True)
        (merge_worktree / "tracked.txt").write_text("right\n")
        subprocess.run(["git", "commit", "-qam", "right"], cwd=merge_worktree, check=True)
        subprocess.run(["git", "merge", "left"], cwd=merge_worktree,
                       capture_output=True)   # 충돌로 실패한다 — MERGE_HEAD 가 남는다

        before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=merge_worktree,
                                capture_output=True, text=True, check=True).stdout.strip()
        status, _detail = orchestrate.refresh_merge_worktree(merge_worktree, "main")
        assert status == "in_progress"
        after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=merge_worktree,
                               capture_output=True, text=True, check=True).stdout.strip()
        assert after == before
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python3 -m pytest skills/fiftybox-orchestration/tests/test_orchestrate.py -q -k "merge_ref or main_is_checked_out or fast_forward or refresh_merge"`
Expected: FAIL — `AttributeError: module 'orchestrate' has no attribute 'resolve_merge_ref'` 외 3개 함수 부재

- [ ] **Step 3: 헬퍼를 구현한다**

Task 1이 만든 `changed_files` 블록 **바로 뒤**에 덧붙인다.

```python
def resolve_merge_ref(root: Path) -> tuple[str | None, bool, str]:
    """(merge ref, pushable, error). A None ref means: stop before committing.

    The ref a run merges into and the ref it pushes to must be the same one.
    Merging local main while pushing origin/main is what makes a stale local
    main reject the push only after the commit and the merge already happened.
    """
    remote = run(["git", "remote", "get-url", "origin"], root)
    if remote.returncode != 0:
        return "main", False, ""
    fetched = run(["git", "fetch", "origin"], root)
    if fetched.returncode != 0:
        return None, True, f"git fetch origin failed: {fetched.stdout.strip()}"
    verified = run(["git", "rev-parse", "--verify", "origin/main"], root)
    if verified.returncode != 0:
        # The remote exists but carries no main yet — this is the first push.
        return "main", True, ""
    return "origin/main", True, ""


def main_is_checked_out(root: Path) -> bool:
    """True when any worktree has refs/heads/main checked out.

    An unreadable worktree list answers True: the caller only uses this to
    decide whether moving the branch is safe, and refusing to move it is the
    harmless answer.
    """
    result = run(["git", "worktree", "list", "--porcelain"], root)
    if result.returncode != 0:
        return True
    return any(line.strip() == "branch refs/heads/main"
               for line in result.stdout.splitlines())


def fast_forward_local_main(root: Path, commit: str) -> str | None:
    """Move local main to `commit`; return a reason string when skipped.

    None means the branch moved. Callers treat a skip as fatal only when
    there is no remote, because then local main was the sole destination and
    the merge commit would otherwise be unreachable.
    """
    if main_is_checked_out(root):
        return "main is checked out in a worktree"
    ancestor = run(["git", "merge-base", "--is-ancestor", "main", commit], root)
    if ancestor.returncode != 0:
        return "local main is not an ancestor of the merged commit"
    updated = run(["git", "branch", "-f", "main", commit], root)
    if updated.returncode != 0:
        return f"git branch -f main failed: {updated.stdout.strip()}"
    return None


def refresh_merge_worktree(merge_worktree: Path, merge_ref: str) -> tuple[str, str]:
    """Re-detach a leftover merge worktree onto merge_ref.

    A merge worktree that survived an earlier failed run still sits on the
    base that run used. Reusing it as-is repeats the failure. A worktree with
    MERGE_HEAD is someone resolving a conflict, so it is left untouched.
    """
    merge_head = run(["git", "rev-parse", "--verify", "MERGE_HEAD"], merge_worktree)
    if merge_head.returncode == 0:
        return "in_progress", "MERGE_HEAD present; base left untouched"
    result = run(["git", "checkout", "--detach", merge_ref], merge_worktree)
    if result.returncode != 0:
        return "failed", result.stdout.strip()
    return "refreshed", merge_ref
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python3 -m pytest skills/fiftybox-orchestration/tests/test_orchestrate.py -q -k "merge_ref or main_is_checked_out or fast_forward or refresh_merge"`
Expected: PASS (11개)

- [ ] **Step 5: 커밋**

```bash
git add skills/fiftybox-orchestration/scripts/orchestrate.py \
        skills/fiftybox-orchestration/tests/test_orchestrate.py
git commit -m "feat(orchestrate): add merge-ref and local-main helpers"
```

---

## Task 4: `phase_complete` 재배선

Task 3의 헬퍼를 실제 페이즈에 연결한다. 이 태스크가 끝나면 stale main 시나리오가 성공한다.

**Files:**
- Modify: `skills/fiftybox-orchestration/scripts/orchestrate.py` (`phase_complete` `:2586-2722`)
- Test: `skills/fiftybox-orchestration/tests/test_orchestrate.py`

**Interfaces:**
- Consumes: Task 3의 `resolve_merge_ref`, `fast_forward_local_main`, `refresh_merge_worktree`
- Produces: `phase_complete`의 성공 JSON에 `mergeRef`(str), `pushed`(bool), `localMainUpdated`(bool), 그리고 건너뛴 경우 `localMainSkipReason`(str). `summary["phases"]["complete"]`에 새 상태값 `fetch_failed`와 `local_main_blocked`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`skills/fiftybox-orchestration/tests/test_orchestrate.py` **맨 끝**에 덧붙인다. `_complete_args()`는 이미 `:1778`에 있다.

```python
def test_complete_succeeds_when_local_main_is_behind_origin():
    """2026-08-10 푸시 거부의 회귀 테스트.

    로컬 main 이 뒤처져 있어도 origin/main 에서 머지하면 push 가 통과한다.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root, worktree, artifact_dir = _sandbox_repo(Path(tmp))
        _push_extra_commit_to_origin(Path(tmp))
        (worktree / "feature.txt").write_text("work\n")

        rc = orchestrate.phase_complete(root, artifact_dir, _complete_args())
        assert rc == 0

        listed = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "origin/main"],
            cwd=root, capture_output=True, text=True, check=True,
        ).stdout.split()
        assert "feature.txt" in listed
        assert "remote-only.txt" in listed

        summary = json.loads((artifact_dir / "summary.json").read_text())
        assert summary["phases"]["complete"]["status"] == "success"
        assert summary["phases"]["complete"]["mergeRef"] == "origin/main"


def test_complete_aborts_before_committing_when_fetch_fails():
    with tempfile.TemporaryDirectory() as tmp:
        root, worktree, artifact_dir = _sandbox_repo(Path(tmp))
        (worktree / "feature.txt").write_text("work\n")
        head_before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=worktree,
                                     capture_output=True, text=True, check=True).stdout.strip()
        subprocess.run(
            ["git", "remote", "set-url", "origin", str(Path(tmp) / "gone.git")],
            cwd=root, check=True,
        )

        rc = orchestrate.phase_complete(root, artifact_dir, _complete_args())
        assert rc != 0

        head_after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=worktree,
                                    capture_output=True, text=True, check=True).stdout.strip()
        assert head_after == head_before   # 커밋이 생기지 않았다
        summary = json.loads((artifact_dir / "summary.json").read_text())
        assert summary["phases"]["complete"]["status"] == "fetch_failed"


def test_complete_without_a_remote_merges_and_moves_local_main():
    with tempfile.TemporaryDirectory() as tmp:
        root, worktree = _solo_repo(Path(tmp))
        artifact_dir = root / "art"
        (artifact_dir / "logs").mkdir(parents=True)
        (artifact_dir / "summary.json").write_text(json.dumps({
            "worktree": str(worktree),
            "branch": "feature/sim",
            "artifactDir": str(artifact_dir),
            "phases": {
                "setup": {"status": "success"},
                "implement": {"status": "success", "changedFiles": ["feature.txt"]},
                "review_test": {"status": "success", "testCommand": "true"},
            },
            "finalStatus": "in_progress",
        }))
        (worktree / "feature.txt").write_text("work\n")

        rc = orchestrate.phase_complete(root, artifact_dir, _complete_args())
        assert rc == 0

        listed = subprocess.run(["git", "ls-tree", "-r", "--name-only", "main"],
                                cwd=root, capture_output=True, text=True,
                                check=True).stdout.split()
        assert "feature.txt" in listed
        summary = json.loads((artifact_dir / "summary.json").read_text())
        assert summary["phases"]["complete"]["pushed"] is False
        assert summary["phases"]["complete"]["localMainUpdated"] is True


def test_complete_reports_local_main_skip_but_still_succeeds_with_a_remote():
    """origin/main 에 이미 올라갔으므로 로컬 main 갱신 실패는 경고다."""
    with tempfile.TemporaryDirectory() as tmp:
        root, worktree, artifact_dir = _sandbox_repo(Path(tmp))
        (worktree / "feature.txt").write_text("work\n")
        # _sandbox_repo 의 root 는 main 을 체크아웃한 상태라 FF 가 불가능하다.

        rc = orchestrate.phase_complete(root, artifact_dir, _complete_args())
        assert rc == 0

        summary = json.loads((artifact_dir / "summary.json").read_text())
        assert summary["phases"]["complete"]["localMainUpdated"] is False
        assert "checked out" in summary["phases"]["complete"]["localMainSkipReason"]
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python3 -m pytest skills/fiftybox-orchestration/tests/test_orchestrate.py -q -k "complete_succeeds_when_local_main or aborts_before_committing or without_a_remote or local_main_skip"`
Expected: FAIL — stale main 테스트는 push 거부로 rc != 0, fetch 실패 테스트는 상태가 `push_failed`, 나머지 둘은 `KeyError: 'pushed'` / `KeyError: 'localMainUpdated'`

- [ ] **Step 3: 원격 사전 검사를 커밋 앞에 넣는다**

`phase_complete`의 dry-run 블록(현재 `:2602-2609`)이 `return 0`으로 끝난 **직후**, `staging_files = ...` 줄(현재 `:2615`) **앞**에 삽입한다:

```python
    # Resolve the merge target before touching the worktree. The push target
    # and the merge base must be the same ref, and finding that out after the
    # commit and merge is what left an orphan merge commit behind.
    merge_ref, pushable, ref_error = resolve_merge_ref(root)
    if merge_ref is None:
        logger.log(ref_error)
        logger.finish(1, "failed")
        summary["phases"]["complete"] = phase_record("fetch_failed", logger, error=ref_error)
        mark_summary_failed(summary, ref_error)
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase="complete", error=ref_error, artifact_dir=artifact_dir)
```

- [ ] **Step 4: 머지 워크트리를 `merge_ref`에서 뜬다**

현재 `:2675-2684`의 블록:

```python
    if not merge_worktree.exists():
        add_merge_tree = run(["git", "worktree", "add", "--detach", str(merge_worktree), "main"], root)
        logger.log(f"$ git worktree add --detach {merge_worktree} main")
        logger.log(add_merge_tree.stdout)
        if add_merge_tree.returncode != 0:
            error = f"merge worktree creation failed: {add_merge_tree.stdout}"
            logger.finish(add_merge_tree.returncode, "failed")
            summary["phases"]["complete"] = phase_record("failed", logger)
            mark_summary_failed(summary, error)
            write_json(artifact_dir / "summary.json", summary)
            return fail_json(phase="complete", error=error, artifact_dir=artifact_dir, exit_code=add_merge_tree.returncode)
```

를 이렇게 바꾼다:

```python
    if not merge_worktree.exists():
        add_merge_tree = run(["git", "worktree", "add", "--detach", str(merge_worktree), merge_ref], root)
        logger.log(f"$ git worktree add --detach {merge_worktree} {merge_ref}")
        logger.log(add_merge_tree.stdout)
        if add_merge_tree.returncode != 0:
            error = f"merge worktree creation failed: {add_merge_tree.stdout}"
            logger.finish(add_merge_tree.returncode, "failed")
            summary["phases"]["complete"] = phase_record("failed", logger)
            mark_summary_failed(summary, error)
            write_json(artifact_dir / "summary.json", summary)
            return fail_json(phase="complete", error=error, artifact_dir=artifact_dir, exit_code=add_merge_tree.returncode)
    else:
        refresh_status, refresh_detail = refresh_merge_worktree(merge_worktree, merge_ref)
        logger.log(f"existing merge worktree: {refresh_status} ({refresh_detail})")
        if refresh_status == "failed":
            error = f"merge worktree could not be re-detached onto {merge_ref}: {refresh_detail}"
            logger.finish(1, "failed")
            summary["phases"]["complete"] = phase_record("failed", logger)
            mark_summary_failed(summary, error)
            write_json(artifact_dir / "summary.json", summary)
            return fail_json(phase="complete", error=error, artifact_dir=artifact_dir)
```

- [ ] **Step 5: 푸시를 `pushable`로 감싼다**

현재 `:2699-2716`의 push 블록:

```python
    push_result = run(["git", "push", "origin", "HEAD:main"], merge_worktree)
    logger.log("$ git push origin HEAD:main")
    logger.log(push_result.stdout)
    if push_result.returncode != 0:
        ...
```

를 이렇게 바꾼다(실패 처리 본문은 그대로 유지한다):

```python
    if pushable:
        push_result = run(["git", "push", "origin", "HEAD:main"], merge_worktree)
        logger.log("$ git push origin HEAD:main")
        logger.log(push_result.stdout)
        if push_result.returncode != 0:
            error = f"Push failed after detached merge:\n{push_result.stdout}"
            logger.finish(push_result.returncode, "failed")
            summary["phases"]["complete"] = phase_record("push_failed", logger)
            summary["mergedCommit"] = merged_hash
            mark_summary_failed(summary, error)
            write_json(artifact_dir / "summary.json", summary)
            return fail_json(
                phase="complete",
                error=error,
                artifact_dir=artifact_dir,
                exit_code=push_result.returncode,
                extra={"mergedCommit": merged_hash, "mergeWorktree": str(merge_worktree)},
            )
    else:
        logger.log("No origin remote; skipping push")
```

- [ ] **Step 6: 로컬 main FF와 결과 필드를 넣는다**

현재 `:2718-2723`의 성공 처리:

```python
    logger.finish(0, "success")
    summary["phases"]["complete"] = phase_record("success", logger)
    summary["mergedCommit"] = merged_hash
    write_json(artifact_dir / "summary.json", summary)
    print(json.dumps({"status": "success", "phase": "complete", "mergedCommit": merged_hash, "artifactDir": str(artifact_dir)}, ensure_ascii=False, separators=(",", ":"))
)
    return 0
```

를 이렇게 바꾼다:

```python
    # Move local main onto the merged commit. With a remote this is a
    # convenience — origin/main already carries the work. Without one it is
    # the only destination, so failing to move it leaves an orphan merge.
    local_main_skip = fast_forward_local_main(root, merged_hash)
    if local_main_skip:
        logger.log(f"local main not updated: {local_main_skip}")
    if local_main_skip and not pushable:
        error = (
            "local_main_blocked: nothing was pushed and local main could not be "
            f"advanced ({local_main_skip}), so the merge commit is unreachable. "
            f"The work is preserved on branch {branch}."
        )
        logger.finish(1, "failed")
        summary["phases"]["complete"] = phase_record(
            "local_main_blocked", logger, error=error, mergeRef=merge_ref, pushed=False,
        )
        summary["mergedCommit"] = merged_hash
        mark_summary_failed(summary, error)
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase="complete", error=error, artifact_dir=artifact_dir)

    logger.finish(0, "success")
    complete_record: dict[str, Any] = {
        "mergeRef": merge_ref,
        "pushed": pushable,
        "localMainUpdated": local_main_skip is None,
    }
    if local_main_skip:
        complete_record["localMainSkipReason"] = local_main_skip
    summary["phases"]["complete"] = phase_record("success", logger, **complete_record)
    summary["mergedCommit"] = merged_hash
    write_json(artifact_dir / "summary.json", summary)
    print(json.dumps({"status": "success", "phase": "complete", "mergedCommit": merged_hash,
                      **complete_record, "artifactDir": str(artifact_dir)},
                     ensure_ascii=False, separators=(",", ":")))
    return 0
```

`Any`는 파일 상단에서 이미 `from typing import Any`로 import 돼 있다(`phase_record`가 쓴다).

- [ ] **Step 7: 통과를 확인한다**

Run: `python3 -m pytest skills/fiftybox-orchestration/tests/test_orchestrate.py -q -k "complete"`
Expected: PASS. 기존 `test_complete_*` 4개와 새 4개가 모두 통과한다.

- [ ] **Step 8: 전체 회귀를 돌린다**

Run: `python3 -m pytest skills/fiftybox-orchestration/tests -q`
Expected: PASS (154 + Task 3의 11 + Task 4의 4 = 169개)

Run: `for t in tests/*.sh; do echo "== $t"; bash "$t" | tail -1; done`
Expected: `test_9b_spec_smoke.sh`만 `0 passed, 8 failed`(기존 상태), 나머지는 전부 `0 failed`

- [ ] **Step 9: 커밋**

```bash
git add skills/fiftybox-orchestration/scripts/orchestrate.py \
        skills/fiftybox-orchestration/tests/test_orchestrate.py
git commit -m "fix(orchestrate): merge from the ref complete pushes to"
```

---

## Task 5: 설치본 동기화 확인 (수동)

`orchestrate.py`는 `~/.claude/skills/`에 복사돼 실행된다. 리포만 고치면 다음 실행이 여전히 옛 코드를 쓴다.

**Files:** 없음 (확인만)

- [ ] **Step 1: 설치본과 리포가 다른지 확인한다**

Run: `diff -q skills/fiftybox-orchestration/scripts/orchestrate.py ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py`
Expected: `differ` — Task 1~4의 변경이 아직 설치되지 않았다

- [ ] **Step 2: 설치 스크립트를 돌린다**

Run: `bash install.sh`
Expected: 오류 없이 종료

- [ ] **Step 3: 동일해졌는지 확인한다**

Run: `diff -q skills/fiftybox-orchestration/scripts/orchestrate.py ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py`
Expected: 출력 없음 (동일)

- [ ] **Step 4: 설치본이 실제로 돈다**

Run: `python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py --help`
Expected: usage 출력, exit 0

---

## Self-Review

**스펙 커버리지**

| 스펙 절 | 담당 태스크 |
|---|---|
| `dirty_baseline` — 경로 수집, 해시, `MISSING` 센티널, untracked 제외 | Task 1 |
| `changed_files(root, before_files, before_dirty)` — 합집합 후보, 해시 비교, 하위 호환 | Task 1 |
| 합집합이 잡는 "더러움 → 깨끗함" 전이 | Task 1 (`test_changed_files_detects_revert_of_a_dirty_file`) |
| 호출부 배선 (`_implement_sequential` ×3, `phase_implement` ×2) | Task 2 |
| 기존 `fake_changed_files` 4곳 갱신 | Task 2 Step 4 |
| ① 원격 사전 검사, 커밋 전 중단, `fetch_failed` | Task 3 (`resolve_merge_ref`), Task 4 Step 3 |
| 빈 원격(첫 푸시) → 로컬 main 기준, 푸시는 시도 | Task 3 (`test_resolve_merge_ref_uses_local_main_when_the_remote_has_no_main`) |
| ② 머지 워크트리를 `mergeRef`에서, 낡은 워크트리 재detach, `MERGE_HEAD` 보존 | Task 3 (`refresh_merge_worktree`), Task 4 Step 4 |
| ③ 로컬 main FF, 원격 있으면 경고 / 없으면 `local_main_blocked` 실패 | Task 3 (`fast_forward_local_main`), Task 4 Step 6 |
| 결과 JSON `mergeRef` / `pushed` / `localMainUpdated` / `localMainSkipReason` | Task 4 Step 6 |
| 테스트 — 이슈 1 전 항목 | Task 1 Step 1 (12개) |
| 테스트 — 이슈 2 전 항목 | Task 3 Step 1 (11개), Task 4 Step 1 (4개) |
| 회귀 — pytest 전체 + `tests/*.sh` | Task 4 Step 8 |
| 설치본 동기화 | Task 5 |

**넣지 않은 것 (스펙의 YAGNI 준수):** `phase_pi_complete` 변경, 푸시 경합 자동 rebase, `pending_files`·민감 파일 필터·커밋 메시지 변경, `SKILL.md` 문서 변경, `install.sh` 변경, 소유권 메시지의 마스킹 경고 필드.

**타입 일관성:** `dirty_baseline`은 Task 1 정의(`dict[str, str]`)와 Task 2 배선, Task 2 테스트의 패치 `return_value={}`에서 모두 같은 타입이다. `changed_files`의 세 번째 인자 이름 `before_dirty`는 Task 1 정의, Task 2 호출부, Task 2 페이크 시그니처에서 일치한다. `resolve_merge_ref`의 3튜플 `(str | None, bool, str)`은 Task 3 정의·테스트와 Task 4의 `merge_ref, pushable, ref_error` 언패킹에서 일치한다. `refresh_merge_worktree`의 2튜플 `(status, detail)`은 Task 3 정의·테스트와 Task 4 Step 4의 `refresh_status, refresh_detail` 언패킹에서 일치한다. `fast_forward_local_main`의 `str | None`은 Task 3 정의·테스트와 Task 4 Step 6의 `local_main_skip` 사용에서 일치한다.
