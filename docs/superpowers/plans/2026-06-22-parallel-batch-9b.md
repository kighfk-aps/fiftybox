# Parallel Batch Execution for 9B Explore Phase — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `qwen-summary-index` 파일 배치 요약을 `QWEN_SUMMARY_PARALLEL=1` 설정 시 `ThreadPoolExecutor`로 병렬 실행하여 9B Ollama 탐색의 파이프라인 오버헤드를 줄인다.

**Architecture:** `SummaryEngine._summarize_files()`에서 `QWEN_SUMMARY_PARALLEL` 환경변수를 읽어 배치 루프를 `_summarize_files_sequential()` 또는 `_summarize_files_parallel()` 중 하나로 분기한다. 모듈·최종 요약 단계는 순차 유지. `select_remote_model.sh`의 9b 케이스가 이 env var를 자동 설정한다.

**Tech Stack:** Python 3.11+, `concurrent.futures.ThreadPoolExecutor` (stdlib), pytest, bash

## Global Constraints

- `QWEN_SUMMARY_PARALLEL` 미설정(또는 `"0"`) 시 기존 순차 동작과 100% 동일해야 한다.
- 모듈 요약(`_summarize_modules`)·최종 요약(`_summarize_final`)은 변경하지 않는다.
- `unbatched_files` 처리는 병렬 여부와 무관하게 항상 순차 실행한다.
- 배치 인덱스 순서(batch-01, batch-02…)가 결과 `file_summaries` 순서에 보존되어야 한다.
- `errors` 리스트는 thread-safe하게 수집 후 caller에 전달한다.
- 스크립트 경로:
  - engine: `/Users/tanpapa/Desktop/develop-a/local-model/src/qwen_summary/engine.py`
  - shell script: `/Users/tanpapa/Desktop/develop-a/fiftybox/skills/fiftybox-local/scripts/select_remote_model.sh`
  - 테스트: `/Users/tanpapa/Desktop/develop-a/local-model/tests/test_qwen_summary_parallel.py` (신규)
- 테스트 실행: `cd /Users/tanpapa/Desktop/develop-a/local-model && python3 -m pytest tests/ -v`

---

## File Map

| 파일 | 역할 | 변경 |
|------|------|------|
| `src/qwen_summary/engine.py` | 배치 병렬/순차 분기, 새 메서드 2개 | 수정 |
| `tests/test_qwen_summary_parallel.py` | 병렬 모드 단위 테스트 | 신규 |
| `skills/fiftybox-local/scripts/select_remote_model.sh` | 9b 케이스에 env var 추가 | 수정 (fiftybox repo) |

---

## Task 1: `_summarize_files()` 리팩터 — 순차 경로 추출 + 분기 추가

**Files:**
- Modify: `src/qwen_summary/engine.py` (`_summarize_files` 메서드 재구성 + `_summarize_files_sequential` 추가)

**Interfaces:**
- Produces:
  - `SummaryEngine._summarize_files_sequential(root_path: Path, batch_plan: BatchPlan, output_dir: Path, errors: list[str]) -> list[dict[str, str]]`
  - `SummaryEngine._summarize_files(...)` 시그니처 동일, `QWEN_SUMMARY_PARALLEL="1"` + 배치 2개 이상일 때 `_summarize_files_parallel()` 호출 (Task 2에서 구현)

- [ ] **Step 1: 기존 테스트가 통과하는지 확인 (baseline)**

```bash
cd /Users/tanpapa/Desktop/develop-a/local-model
python3 -m pytest tests/test_qwen_summary_adaptive.py -v
```

Expected: 2 tests PASSED

- [ ] **Step 2: `_summarize_files_sequential()` 추출 + `_summarize_files()` 분기 코드 작성**

`src/qwen_summary/engine.py`의 `_summarize_files` 메서드 전체를 다음으로 교체한다:

```python
def _summarize_files(
    self,
    files: list[str],
    root_path: Path,
    batch_plan: BatchPlan,
    output_dir: Path,
    errors: list[str],
) -> list[dict[str, str]]:
    """Summarize all files in batches."""
    (output_dir / "file-summaries").mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, str]] = []

    if not batch_plan.batches:
        for file_path in files:
            result = self._summarize_single_file(file_path, root_path, output_dir, errors)
            if result:
                summaries.append(result)
        return summaries

    parallel = os.environ.get("QWEN_SUMMARY_PARALLEL", "0") == "1"
    max_workers = int(os.environ.get("QWEN_SUMMARY_PARALLEL_WORKERS", "4"))

    if parallel and len(batch_plan.batches) > 1:
        summaries = self._summarize_files_parallel(
            root_path, batch_plan, output_dir, errors, max_workers=max_workers
        )
    else:
        summaries = self._summarize_files_sequential(root_path, batch_plan, output_dir, errors)

    for file_path in batch_plan.unbatched_files:
        result = self._summarize_single_file(file_path, root_path, output_dir, errors)
        if result:
            summaries.append(result)

    return summaries

def _summarize_files_sequential(
    self,
    root_path: Path,
    batch_plan: BatchPlan,
    output_dir: Path,
    errors: list[str],
) -> list[dict[str, str]]:
    """Summarize file batches sequentially (original behavior)."""
    summaries: list[dict[str, str]] = []
    for i, batch in enumerate(batch_plan.batches, start=1):
        batch_summaries = self._summarize_file_batch(
            batch_files_list=batch.files,
            root_path=root_path,
            batch_index=i,
            output_dir=output_dir,
            errors=errors,
        )
        summaries.extend(batch_summaries)
    return summaries
```

`_summarize_files_parallel`은 아직 없으므로, 지금은 `parallel` 분기가 실행되지 않는다.

- [ ] **Step 3: 기존 테스트 재실행 — 동작 변화 없어야 함**

```bash
cd /Users/tanpapa/Desktop/develop-a/local-model
python3 -m pytest tests/test_qwen_summary_adaptive.py -v
```

Expected: 2 tests PASSED (동일 결과)

- [ ] **Step 4: 변경 확인**

`local-model`은 git 레포가 아니므로 커밋하지 않는다. 변경된 파일만 확인:

```bash
python3 -c "import sys; sys.path.insert(0, 'src'); from qwen_summary.engine import SummaryEngine; print('OK')"
```

Expected: `OK`

---

## Task 2: `_summarize_files_parallel()` 구현 + 테스트

**Files:**
- Modify: `src/qwen_summary/engine.py` (`_summarize_files_parallel` 추가)
- Create: `tests/test_qwen_summary_parallel.py`

**Interfaces:**
- Consumes:
  - `SummaryEngine._summarize_file_batch(batch_files_list, root_path, batch_index, output_dir, errors)` — 기존 메서드
  - `SummaryEngine._summarize_files_sequential(root_path, batch_plan, output_dir, errors)` — Task 1
- Produces:
  - `SummaryEngine._summarize_files_parallel(root_path: Path, batch_plan: BatchPlan, output_dir: Path, errors: list[str], *, max_workers: int = 4) -> list[dict[str, str]]`

- [ ] **Step 1: 테스트 파일 작성 (Red)**

`tests/test_qwen_summary_parallel.py` 를 아래 내용으로 생성한다:

```python
"""Tests for QWEN_SUMMARY_PARALLEL=1 parallel batch execution."""
from __future__ import annotations

import re
import threading
from pathlib import Path

import pytest

from qwen_summary.client import SummaryResult
from qwen_summary.engine import SummaryEngine
from qwen_summary.prompts import FILE_BATCH_SUMMARY_SYSTEM, FINAL_SUMMARY_SYSTEM, MODULE_SUMMARY_SYSTEM


class TrackingClient:
    """Fake client that records which files were summarized and in what order."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: list[str] = []

    def summarize(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 1500,
    ) -> SummaryResult:
        if system == FILE_BATCH_SUMMARY_SYSTEM:
            files = re.findall(r"^### ([^\n]+)$", prompt, flags=re.MULTILINE)
            with self._lock:
                self._seen.extend(files)
            return SummaryResult(
                text="\n---\n".join(
                    f"## File: {fp}\n### Purpose\nsummary\n### Exports\nNone"
                    f"\n### Dependencies\nNone\n### Key Logic\nNone\n### Risks\nNone"
                    for fp in files
                )
            )
        if system == MODULE_SUMMARY_SYSTEM:
            return SummaryResult(text="## Module Purpose\nmod\n\n## Files & Responsibilities\nnone")
        if system == FINAL_SUMMARY_SYSTEM:
            return SummaryResult(text="## Project Purpose\nproject")
        return SummaryResult(text="summary")

    @property
    def seen(self) -> list[str]:
        return list(self._seen)


class FailingClient(TrackingClient):
    """Every second batch call returns a timeout failure."""

    def __init__(self) -> None:
        super().__init__()
        self._call_count = 0

    def summarize(self, prompt, *, system=None, temperature=0.1, max_tokens=1500):
        if system == FILE_BATCH_SUMMARY_SYSTEM:
            with self._lock:
                self._call_count += 1
                local = self._call_count
            if local % 2 == 0:
                return SummaryResult(text="", finish_reason="timeout")
        return super().summarize(prompt, system=system, temperature=temperature, max_tokens=max_tokens)


def _write_project(root: Path, count: int) -> None:
    src = root / "src"
    src.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        (src / f"file_{i:02d}.py").write_text(
            f"VALUE = {i}\n" + "# filler\n" * 20, encoding="utf-8"
        )


def test_parallel_returns_all_file_summaries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """QWEN_SUMMARY_PARALLEL=1 must return a summary for every file."""
    _write_project(tmp_path / "proj", 30)
    monkeypatch.setenv("QWEN_SUMMARY_PARALLEL", "1")
    monkeypatch.setenv("QWEN_SUMMARY_PARALLEL_WORKERS", "3")

    client = TrackingClient()
    result = SummaryEngine(client).run(
        tmp_path / "proj",
        context_tier="16k",
        output_dir=tmp_path / "out",
        include_child_apps=False,
    )

    assert result.status == "success", result.errors
    assert result.file_count == 30
    assert len(result.file_summaries) == 30


def test_parallel_same_files_as_sequential(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Parallel mode must cover the exact same file set as sequential mode."""
    _write_project(tmp_path / "proj", 30)

    monkeypatch.delenv("QWEN_SUMMARY_PARALLEL", raising=False)
    result_seq = SummaryEngine(TrackingClient()).run(
        tmp_path / "proj",
        context_tier="16k",
        output_dir=tmp_path / "out-seq",
        include_child_apps=False,
    )

    monkeypatch.setenv("QWEN_SUMMARY_PARALLEL", "1")
    monkeypatch.setenv("QWEN_SUMMARY_PARALLEL_WORKERS", "4")
    result_par = SummaryEngine(TrackingClient()).run(
        tmp_path / "proj",
        context_tier="16k",
        output_dir=tmp_path / "out-par",
        include_child_apps=False,
    )

    files_seq = sorted(e["file"] for e in result_seq.file_summaries)
    files_par = sorted(e["file"] for e in result_par.file_summaries)
    assert files_par == files_seq


def test_parallel_file_order_preserved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Batch results must appear in ascending batch order (batch-01 before batch-02, etc.)."""
    _write_project(tmp_path / "proj", 30)
    monkeypatch.setenv("QWEN_SUMMARY_PARALLEL", "1")
    monkeypatch.setenv("QWEN_SUMMARY_PARALLEL_WORKERS", "4")

    result = SummaryEngine(TrackingClient()).run(
        tmp_path / "proj",
        context_tier="16k",
        output_dir=tmp_path / "out",
        include_child_apps=False,
    )

    file_names = [e["file"] for e in result.file_summaries]
    assert file_names == sorted(file_names), (
        "file_summaries must be in sorted file order; got: " + str(file_names[:5])
    )


def test_parallel_errors_collected_from_all_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Errors from failing batches are all collected, not silently dropped."""
    _write_project(tmp_path / "proj", 30)
    monkeypatch.setenv("QWEN_SUMMARY_PARALLEL", "1")
    monkeypatch.setenv("QWEN_SUMMARY_PARALLEL_WORKERS", "4")

    result = SummaryEngine(FailingClient()).run(
        tmp_path / "proj",
        context_tier="16k",
        output_dir=tmp_path / "out",
        include_child_apps=False,
    )

    assert len(result.errors) > 0, "Expected errors from failing batches to be collected"


def test_single_batch_ignores_parallel_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When there is only 1 batch, PARALLEL=1 has no effect (condition: len > 1)."""
    _write_project(tmp_path / "proj", 2)  # 2 files → single batch at 256k tier
    monkeypatch.setenv("QWEN_SUMMARY_PARALLEL", "1")

    result = SummaryEngine(TrackingClient()).run(
        tmp_path / "proj",
        context_tier="256k",
        output_dir=tmp_path / "out",
        include_child_apps=False,
    )

    assert result.status == "success", result.errors
    assert result.file_count == 2


def test_unbatched_files_are_included_in_parallel_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Files too large for batching (unbatched_files) are included even in parallel mode."""
    src = tmp_path / "proj" / "src"
    src.mkdir(parents=True)
    # 1 normal file + 1 very large file that forces single-file summarization
    (src / "normal.py").write_text("VALUE = 1\n" + "# filler\n" * 20, encoding="utf-8")
    # Large file: exceeds MAX_CHARS_PER_FILE in prompt, but still scanned
    (src / "large.py").write_text("X = 0\n" + "# line\n" * 10000, encoding="utf-8")

    monkeypatch.setenv("QWEN_SUMMARY_PARALLEL", "1")
    result = SummaryEngine(TrackingClient()).run(
        tmp_path / "proj",
        context_tier="8k",
        output_dir=tmp_path / "out",
        include_child_apps=False,
    )

    summarized = {e["file"] for e in result.file_summaries}
    assert "src/normal.py" in summarized
    assert "src/large.py" in summarized
```

- [ ] **Step 2: 테스트 실행 — 실패 확인 (Red)**

```bash
cd /Users/tanpapa/Desktop/develop-a/local-model
python3 -m pytest tests/test_qwen_summary_parallel.py -v
```

Expected: 5 tests FAILED (`AttributeError: '_summarize_files_parallel' not found` 또는 유사)

- [ ] **Step 3: `_summarize_files_parallel()` 구현**

`src/qwen_summary/engine.py`의 `_summarize_files_sequential` 정의 바로 뒤에 다음 메서드를 추가한다:

```python
def _summarize_files_parallel(
    self,
    root_path: Path,
    batch_plan: BatchPlan,
    output_dir: Path,
    errors: list[str],
    *,
    max_workers: int = 4,
) -> list[dict[str, str]]:
    """Summarize file batches concurrently using a thread pool.

    Submits all batches at once; Ollama queues them and the GPU processes
    them one at a time. Speedup comes from eliminating Python idle time
    between sequential submissions.
    """
    from concurrent.futures import ThreadPoolExecutor

    def run_batch(idx: int, batch_files_list: list[str]) -> tuple[list[dict[str, str]], list[str]]:
        local_errors: list[str] = []
        result = self._summarize_file_batch(
            batch_files_list=batch_files_list,
            root_path=root_path,
            batch_index=idx,
            output_dir=output_dir,
            errors=local_errors,
        )
        return result, local_errors

    workers = min(max_workers, len(batch_plan.batches))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures_in_order = [
            executor.submit(run_batch, i, batch.files)
            for i, batch in enumerate(batch_plan.batches, start=1)
        ]
    # executor has shut down — all futures are done; collect in submission order
    summaries: list[dict[str, str]] = []
    for future in futures_in_order:
        batch_summaries, local_errors = future.result()
        summaries.extend(batch_summaries)
        errors.extend(local_errors)
    return summaries
```

- [ ] **Step 4: 테스트 실행 — 통과 확인 (Green)**

```bash
cd /Users/tanpapa/Desktop/develop-a/local-model
python3 -m pytest tests/test_qwen_summary_parallel.py tests/test_qwen_summary_adaptive.py -v
```

Expected: 7 tests PASSED

- [ ] **Step 5: 변경 확인 (`local-model`은 git 레포 아님)**

```bash
cd /Users/tanpapa/Desktop/develop-a/local-model
python3 -m pytest tests/test_qwen_summary_parallel.py tests/test_qwen_summary_adaptive.py -v
```

Expected: 7 tests PASSED

---

## Task 3: `select_remote_model.sh` — 9b 케이스에 병렬 env var 추가

**Files:**
- Modify: `skills/fiftybox-local/scripts/select_remote_model.sh` (fiftybox repo)

**Interfaces:**
- Consumes: `QWEN_SUMMARY_PARALLEL`, `QWEN_SUMMARY_PARALLEL_WORKERS` — Task 2에서 `engine.py`가 읽음
- Produces: 9b 케이스 `eval` 시 `QWEN_SUMMARY_PARALLEL=1`, `QWEN_SUMMARY_PARALLEL_WORKERS=4` 설정

- [ ] **Step 1: 스크립트의 공통 EXPORTS 블록 확인**

```bash
grep -n "QWEN_SUMMARY" /Users/tanpapa/Desktop/develop-a/fiftybox/skills/fiftybox-local/scripts/select_remote_model.sh
```

Expected: `QWEN_SUMMARY_TIMEOUT=300` 가 공통 EXPORTS 블록 안에 있음을 확인

- [ ] **Step 2: 9b 케이스 다음에 조건부 export 블록 추가**

`select_remote_model.sh`의 공통 `EXPORTS` heredoc 끝 바로 뒤(파일 마지막 부분)에 다음을 추가한다:

```bash
# 9b 모델은 Ollama 단일 GPU — 병렬 배치 제출로 파이프라인 오버헤드 절감
if [ "$choice" = "9" ] || [ "$choice" = "9b" ] || [ "$choice" = "ollama-9b" ]; then
cat <<PARALLEL_EXPORTS
export QWEN_SUMMARY_PARALLEL=1
export QWEN_SUMMARY_PARALLEL_WORKERS=4
PARALLEL_EXPORTS
fi
```

- [ ] **Step 3: 수동 검증 — glm-5.4 케이스에 PARALLEL이 없는지 확인**

```bash
/Users/tanpapa/Desktop/develop-a/fiftybox/skills/fiftybox-local/scripts/select_remote_model.sh glm-5.4 2>/dev/null | grep PARALLEL
```

Expected: 아무 출력 없음 (PARALLEL 관련 export 없음)

- [ ] **Step 4: 수동 검증 — 실제 9b 실행 시 env var 설정 확인**

원격 GPU가 접근 가능할 때:

```bash
eval "$(/Users/tanpapa/Desktop/develop-a/fiftybox/skills/fiftybox-local/scripts/select_remote_model.sh 9b 2>/dev/null)"
echo "PARALLEL=$QWEN_SUMMARY_PARALLEL"
echo "WORKERS=$QWEN_SUMMARY_PARALLEL_WORKERS"
```

Expected:
```
PARALLEL=1
WORKERS=4
```

- [ ] **Step 5: commit (fiftybox repo)**

```bash
git add skills/fiftybox-local/scripts/select_remote_model.sh
git commit -m "feat: export QWEN_SUMMARY_PARALLEL=1 for 9b model to enable parallel batch explore"
```

---

## 전체 검증

Task 1–3 완료 후:

```bash
# 모든 qwen_summary 테스트
cd /Users/tanpapa/Desktop/develop-a/local-model
python3 -m pytest tests/test_qwen_summary_adaptive.py tests/test_qwen_summary_parallel.py -v
```

Expected: 8 tests PASSED

fiftybox 레포 커밋 확인:
```bash
git log --oneline -3
```
