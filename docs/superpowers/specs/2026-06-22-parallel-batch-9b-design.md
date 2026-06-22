# Parallel Batch Execution for 9B Explore Phase — Design Spec

> Date: 2026-06-22
> Scope: `qwen-summary-index` file-batch parallelization, 9B (Ollama) model only

---

## Problem

`qwen-summary-index`의 파일 배치 요약 단계(`_summarize_files`)는 배치를 순차적으로 처리한다.
9B Ollama 모델을 사용하는 fiftybox-local / fiftybox-plans Explore Phase에서 배치 수가 많을수록
Python 대기 + 네트워크 왕복 오버헤드가 누적되어 탐색 전체가 느려진다.

## Goal

`QWEN_SUMMARY_PARALLEL=1` 환경변수가 설정된 경우에만 파일 배치 요약을 `ThreadPoolExecutor`로 병렬
실행하여 파이프라인 오버헤드를 줄인다. 9B 이외 모델(glm-5.2, 27b, 35b)의 동작은 변경하지 않는다.

## Constraints

- Ollama 9B는 단일 GPU에서 요청을 직렬 처리한다. 병렬 HTTP 요청은 Ollama 큐에 쌓이므로
  GPU 추론 시간 자체는 줄어들지 않는다. **절감 범위: Python idle + 네트워크 RTT 오버헤드.**
- 기존 순차 경로를 건드리지 않는다 — `QWEN_SUMMARY_PARALLEL` 미설정 시 완전히 동일하게 동작해야 한다.
- 스레드 안전성: 배치별 파일 출력 경로가 이미 고유(`batch-01`, `batch-02`, …)하므로 파일 쓰기 충돌 없음.
  `errors` 리스트는 스레드마다 분리 수집 후 merge한다.
- 결과 순서 보존: 모듈 요약이 파일 경로 순서에 의존하므로 병렬 완료 후 배치 인덱스 기준으로 정렬한다.

## Architecture

### 환경 변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `QWEN_SUMMARY_PARALLEL` | `"0"` | `"1"`이면 파일 배치 병렬 실행 |
| `QWEN_SUMMARY_PARALLEL_WORKERS` | `"4"` | `ThreadPoolExecutor` 최대 워커 수 |

### 변경 파일

#### 1. `skills/fiftybox-local/scripts/select_remote_model.sh`

`9b|ollama-9b` 케이스의 export 블록에 두 줄 추가:

```bash
export QWEN_SUMMARY_PARALLEL=1
export QWEN_SUMMARY_PARALLEL_WORKERS=4
```

다른 케이스(glm-5.4, 27b, 35b)에는 추가하지 않는다.

#### 2. `src/qwen_summary/engine.py`

**모듈 레벨** — 플래그 읽기:

```python
PARALLEL_BATCHES = os.environ.get("QWEN_SUMMARY_PARALLEL", "0") == "1"
MAX_PARALLEL_WORKERS = int(os.environ.get("QWEN_SUMMARY_PARALLEL_WORKERS", "4"))
```

**`_summarize_files()` 수정** — 플래그에 따라 분기:

```python
def _summarize_files(self, files, root_path, batch_plan, output_dir, errors):
    ...
    if PARALLEL_BATCHES and len(batch_plan.batches) > 1:
        summaries = self._summarize_files_parallel(
            files, root_path, batch_plan, output_dir, errors
        )
    else:
        summaries = self._summarize_files_sequential(
            files, root_path, batch_plan, output_dir, errors
        )
    # unbatched (too-large) files always sequential
    for file_path in batch_plan.unbatched_files:
        result = self._summarize_single_file(file_path, root_path, output_dir, errors)
        if result:
            summaries.append(result)
    return summaries
```

**`_summarize_files_parallel()`** — 새 내부 메서드:

```python
def _summarize_files_parallel(self, files, root_path, batch_plan, output_dir, errors):
    from concurrent.futures import ThreadPoolExecutor, as_completed

    batch_results: dict[int, list[dict[str, str]]] = {}
    batch_errors: dict[int, list[str]] = {}

    def run_batch(index_batch):
        idx, batch = index_batch
        local_errors: list[str] = []
        result = self._summarize_file_batch(
            batch_files_list=batch.files,
            root_path=root_path,
            batch_index=idx,
            output_dir=output_dir,
            errors=local_errors,
        )
        return idx, result, local_errors

    workers = min(MAX_PARALLEL_WORKERS, len(batch_plan.batches))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(run_batch, (i, batch)): i
            for i, batch in enumerate(batch_plan.batches, start=1)
        }
        for future in as_completed(futures):
            idx, result, local_errors = future.result()
            batch_results[idx] = result
            batch_errors[idx] = local_errors

    # merge in order, errors last
    summaries: list[dict[str, str]] = []
    for idx in sorted(batch_results):
        summaries.extend(batch_results[idx])
        errors.extend(batch_errors[idx])
    return summaries
```

**`_summarize_files_sequential()`** — 기존 루프를 추출한 내부 메서드:

기존 `_summarize_files()` 내의 배치 루프를 그대로 이 메서드로 이동한다.
`unbatched_files` 처리는 `_summarize_files()`에서 공통으로 처리한다.

### 모듈 요약 / 최종 요약

변경 없음. 파일 요약 완료 후 순차 실행한다.

## Data Flow (parallel mode)

```
scan → batch_plan
         ├─ batch 1 → [Thread 1] → batch_results[1]
         ├─ batch 2 → [Thread 2] → batch_results[2]  → sorted merge
         └─ batch N → [Thread N] → batch_results[N]
                                           ↓
                              _summarize_modules()  (sequential)
                                           ↓
                              _summarize_final()    (sequential)
```

## Model Routing Table

| 모델 | QWEN_SUMMARY_PARALLEL | 실행 경로 |
|------|-----------------------|-----------|
| 9b (Ollama) | `1` | 병렬 |
| glm-5.2 / glm-5.4 | 미설정 | 순차 |
| 27b | 미설정 | 순차 |
| 35b | 미설정 | 순차 |

## Verification Plan

1. `--dry-run` 으로 배치 계획 확인 (`batch-plan.txt` 출력 검토)
2. `QWEN_SUMMARY_PARALLEL=1`로 소규모 프로젝트 탐색 실행 → `elapsed_ms` 비교 (before/after)
3. `QWEN_SUMMARY_PARALLEL=0` (미설정) 으로 동일 프로젝트 실행 → 결과 동일성 확인
4. `final-summary.md` 내용 품질 확인 — 순차 모드와 동등해야 함
5. 오류 케이스: 배치 하나가 실패해도 나머지 결과가 보존되는지 확인

## Out of Scope

- 27b / 35b 모델 병렬화 (vLLM은 이미 서버 측에서 배칭 처리)
- 모듈 요약 / 최종 요약 병렬화
- codegraph 통합 (별도 작업)
- 캐싱 레이어
