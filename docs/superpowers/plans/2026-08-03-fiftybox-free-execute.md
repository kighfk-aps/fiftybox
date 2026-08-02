# fiftybox-free-execute Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** opencode Zen 무료 모델로 구현 페이즈를 돌리는 실행 스킬 `fiftybox-free-execute`를 만든다. 실행마다 사용 가능한 무료 모델을 탐색하고 사용자가 하나를 고른다.

**Architecture:** 세 부분으로 나뉜다. ① 순수 함수 위주의 탐색 스크립트 `discover_free_models.py`가 opencode CLI 출력을 파싱·필터·스모크 테스트해 JSON 후보 목록을 낸다. ② `orchestrate.py`에 호출 단위 에이전트 오버라이드 플래그 `--implement-agent`를 추가하고 망가진 `opencode` 어댑터 커맨드를 고친다. ③ `SKILL.md`가 둘을 잇는 순차 TDD 워크플로를 기술한다. 세 부분은 모델 ID 문자열로만 결합된다.

**Tech Stack:** Python 3 표준 라이브러리 (`subprocess`, `json`, `re`, `argparse`, `concurrent.futures`), pytest, bash (install.sh)

## Global Constraints

- 스펙 원본: `docs/superpowers/specs/2026-08-03-fiftybox-free-execute-design.md`
- 무료 판별 규칙은 반드시 **네 조건 모두**: `providerID == "opencode"` AND `cost.input == 0` AND `cost.output == 0` AND `capabilities.toolcall == True` AND `status == "active"`. 모델 이름의 `-free` 접미사로 판별하지 않는다.
- `fiftybox-execute`와 `fiftybox-orchestration`의 기존 동작은 절대 바뀌면 안 된다. `--implement-agent`를 넘기지 않으면 `config.json` 값이 그대로 쓰여야 한다.
- 새 파이썬 코드는 표준 라이브러리만 쓴다. 새 의존성을 추가하지 않는다.
- 테스트는 네트워크에 의존하지 않는다. `subprocess` 호출은 전부 목으로 대체한다.
- 스모크 테스트 파라미터: 타임아웃 30초, 동시 실행 최대 4개.
- rate limit 판별 패턴 (소문자 비교): `429`, `rate limit`, `quota`, `insufficient`
- 커밋 메시지는 리포지토리 관례(`feat:`, `fix:`, `docs:`, `test:`)를 따른다.

## File Structure

**Create**
| 파일 | 책임 |
|---|---|
| `skills/fiftybox-free-execute/scripts/discover_free_models.py` | opencode 모델 목록 파싱·무료 필터·스모크 테스트·JSON 출력. orchestrate.py를 모른다 |
| `skills/fiftybox-free-execute/tests/test_discover_free_models.py` | 위 스크립트의 순수 함수 테스트 |
| `skills/fiftybox-free-execute/tests/fixtures/opencode_models_verbose.txt` | `opencode models --verbose` 출력 픽스처 |
| `skills/fiftybox-free-execute/tests/fixtures/opencode_models_plain.txt` | 평문 `opencode models` 출력 픽스처 |
| `skills/fiftybox-free-execute/SKILL.md` | 순차 TDD 워크플로 문서 |
| `commands/fiftybox-free-execute.md` | 슬래시 커맨드 |

**Modify**
| 파일 | 변경 |
|---|---|
| `skills/fiftybox-orchestration/scripts/orchestrate.py` | `resolve_agent_config()` 추가, `--implement-agent` 인자 추가, `opencode` 어댑터 cmd 수정 |
| `skills/fiftybox-orchestration/config.example.json` | `opencode` 어댑터 cmd 수정 |
| `skills/fiftybox-orchestration/tests/test_agent_config.py` | 신규 테스트 추가 |
| `install.sh` | 새 스킬·커맨드 설치 |
| `tests/test_install.sh` | 설치 검증 추가 |

**알아둘 것:** `orchestrate.py:77`의 `SKILL_DIR`은 `~/.claude/skills/orchestrate`를 가리키는데 `install.sh`는 `~/.claude/skills/fiftybox-orchestration`에 설치한다. 즉 설치본에서는 `config.json`이 발견되지 않아 항상 Pi 기본값이 쓰인다. **이 계획의 범위 밖이며 고치지 않는다.** `--implement-agent` 플래그는 이 불일치와 무관하게 동작한다(오버라이드가 config 로드 이후에 적용되므로).

---

### Task 1: 모델 목록 파서

`opencode models opencode --verbose` 출력을 `(model_id, metadata_dict)` 목록으로 바꾸는 순수 함수와, 평문 폴백 파서를 만든다.

**Files:**
- Create: `skills/fiftybox-free-execute/scripts/discover_free_models.py`
- Create: `skills/fiftybox-free-execute/tests/fixtures/opencode_models_verbose.txt`
- Create: `skills/fiftybox-free-execute/tests/fixtures/opencode_models_plain.txt`
- Test: `skills/fiftybox-free-execute/tests/test_discover_free_models.py`

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces:
  - `parse_verbose_models(text: str) -> list[tuple[str, dict]]` — `[("opencode/big-pickle", {...}), ...]`. 파싱 불가 블록은 조용히 건너뛴다.
  - `parse_plain_models(text: str) -> list[str]` — `["opencode/big-pickle", ...]`

- [ ] **Step 1: 픽스처 디렉터리와 verbose 픽스처 작성**

`skills/fiftybox-free-execute/tests/fixtures/opencode_models_verbose.txt` 를 만든다. 실제 출력 형식(모델 ID 한 줄 + JSON 블록 반복)을 그대로 따르되, 필터 회귀 검증에 필요한 항목만 담는다.

```
opencode/big-pickle
{
  "id": "big-pickle",
  "providerID": "opencode",
  "name": "Big Pickle",
  "status": "active",
  "cost": { "input": 0, "output": 0 },
  "limit": { "context": 200000, "output": 32000 },
  "capabilities": { "toolcall": true }
}
opencode/mimo-v2.5-free
{
  "id": "mimo-v2.5-free",
  "providerID": "opencode",
  "name": "MiMo v2.5 Free",
  "status": "active",
  "cost": { "input": 0, "output": 0 },
  "limit": { "context": 200000, "output": 32000 },
  "capabilities": { "toolcall": true }
}
opencode/nemotron-3-ultra-free
{
  "id": "nemotron-3-ultra-free",
  "providerID": "opencode",
  "name": "Nemotron 3 Ultra Free",
  "status": "active",
  "cost": { "input": 0, "output": 0 },
  "limit": { "context": 1000000, "output": 32000 },
  "capabilities": { "toolcall": true }
}
opencode/legacy-chat-free
{
  "id": "legacy-chat-free",
  "providerID": "opencode",
  "name": "Legacy Chat Free",
  "status": "active",
  "cost": { "input": 0, "output": 0 },
  "limit": { "context": 128000, "output": 8000 },
  "capabilities": { "toolcall": false }
}
opencode/retired-free
{
  "id": "retired-free",
  "providerID": "opencode",
  "name": "Retired Free",
  "status": "deprecated",
  "cost": { "input": 0, "output": 0 },
  "limit": { "context": 128000, "output": 8000 },
  "capabilities": { "toolcall": true }
}
opencode-go/deepseek-v4-flash
{
  "id": "deepseek-v4-flash",
  "providerID": "opencode-go",
  "name": "DeepSeek v4 Flash",
  "status": "active",
  "cost": { "input": 0.14, "output": 0.28 },
  "limit": { "context": 1000000, "output": 384000 },
  "capabilities": { "toolcall": true }
}
openai/gpt-5.6-pro
{
  "id": "gpt-5.6-pro",
  "providerID": "openai",
  "name": "GPT-5.6 Pro",
  "status": "active",
  "cost": { "input": 0, "output": 0 },
  "limit": { "context": 1050000, "output": 128000 },
  "capabilities": { "toolcall": true }
}
zai/glm-4.5-flash
{
  "id": "glm-4.5-flash",
  "providerID": "zai",
  "name": "GLM 4.5 Flash",
  "status": "active",
  "cost": { "input": 0, "output": 0 },
  "limit": { "context": 131072, "output": 98304 },
  "capabilities": { "toolcall": true }
}
```

- [ ] **Step 2: 평문 픽스처 작성**

`skills/fiftybox-free-execute/tests/fixtures/opencode_models_plain.txt`:

```
opencode/big-pickle
opencode/mimo-v2.5-free
opencode/nemotron-3-ultra-free
```

- [ ] **Step 3: 실패하는 테스트 작성**

`skills/fiftybox-free-execute/tests/test_discover_free_models.py`:

```python
"""Tests for discover_free_models."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
FIXTURES_DIR = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(SCRIPTS_DIR))

import discover_free_models as dfm  # noqa: E402


@pytest.fixture
def verbose_text() -> str:
    return (FIXTURES_DIR / "opencode_models_verbose.txt").read_text(encoding="utf-8")


@pytest.fixture
def plain_text() -> str:
    return (FIXTURES_DIR / "opencode_models_plain.txt").read_text(encoding="utf-8")


class TestParseVerboseModels:
    def test_parses_every_block(self, verbose_text):
        parsed = dfm.parse_verbose_models(verbose_text)
        assert len(parsed) == 8

    def test_returns_id_and_metadata_pairs(self, verbose_text):
        parsed = dfm.parse_verbose_models(verbose_text)
        ids = [model_id for model_id, _ in parsed]
        assert ids[0] == "opencode/big-pickle"
        assert ids[-1] == "zai/glm-4.5-flash"

    def test_metadata_is_parsed_json(self, verbose_text):
        parsed = dfm.parse_verbose_models(verbose_text)
        by_id = dict(parsed)
        entry = by_id["opencode/nemotron-3-ultra-free"]
        assert entry["providerID"] == "opencode"
        assert entry["limit"]["context"] == 1000000
        assert entry["capabilities"]["toolcall"] is True

    def test_skips_unparseable_block_keeps_rest(self):
        text = (
            "opencode/good\n"
            '{ "providerID": "opencode" }\n'
            "opencode/broken\n"
            "{ not json at all\n"
            "opencode/also-good\n"
            '{ "providerID": "opencode" }\n'
        )
        parsed = dfm.parse_verbose_models(text)
        assert [model_id for model_id, _ in parsed] == ["opencode/good", "opencode/also-good"]

    def test_empty_text_returns_empty_list(self):
        assert dfm.parse_verbose_models("") == []

    def test_plain_listing_without_json_returns_empty(self, plain_text):
        assert dfm.parse_verbose_models(plain_text) == []


class TestParsePlainModels:
    def test_returns_model_ids(self, plain_text):
        assert dfm.parse_plain_models(plain_text) == [
            "opencode/big-pickle",
            "opencode/mimo-v2.5-free",
            "opencode/nemotron-3-ultra-free",
        ]

    def test_ignores_blank_and_non_model_lines(self):
        text = "\nopencode/a\nsome noise here\n\nopencode/b\n"
        assert dfm.parse_plain_models(text) == ["opencode/a", "opencode/b"]
```

- [ ] **Step 4: 테스트가 실패하는지 확인**

Run: `python3 -m pytest skills/fiftybox-free-execute/tests/test_discover_free_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'discover_free_models'`

- [ ] **Step 5: 최소 구현 작성**

`skills/fiftybox-free-execute/scripts/discover_free_models.py`:

```python
#!/usr/bin/env python3
"""Discover usable opencode Zen free models.

Emits a JSON document on stdout describing free-tier candidates and whether
each one currently answers a trivial prompt. Knows nothing about orchestrate.py.
"""
from __future__ import annotations

import json
import re

MODEL_ID_RE = re.compile(r"(?m)^([a-z0-9][a-z0-9-]*/[A-Za-z0-9._-]+)[ \t]*$")


def parse_verbose_models(text: str) -> list[tuple[str, dict]]:
    """Parse `opencode models <provider> --verbose` output.

    The output repeats a bare `provider/model` line followed by a JSON block.
    Blocks that fail to parse are skipped so one format change cannot blank
    the whole listing.
    """
    parts = MODEL_ID_RE.split(text)
    # parts[0] is whatever preceded the first id line; pairs follow.
    pairs: list[tuple[str, dict]] = []
    for i in range(1, len(parts) - 1, 2):
        model_id = parts[i].strip()
        blob = parts[i + 1]
        try:
            entry = json.loads(blob)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(entry, dict):
            pairs.append((model_id, entry))
    return pairs


def parse_plain_models(text: str) -> list[str]:
    """Parse plain `opencode models <provider>` output into model ids."""
    return [m.strip() for m in MODEL_ID_RE.findall(text)]
```

- [ ] **Step 6: 테스트가 통과하는지 확인**

Run: `python3 -m pytest skills/fiftybox-free-execute/tests/test_discover_free_models.py -v`
Expected: PASS (13 tests)

- [ ] **Step 7: 커밋**

```bash
git add skills/fiftybox-free-execute/scripts/discover_free_models.py \
        skills/fiftybox-free-execute/tests/test_discover_free_models.py \
        skills/fiftybox-free-execute/tests/fixtures/
git commit -m "feat(free-execute): add opencode model listing parsers"
```

---

### Task 2: 무료 후보 필터와 정렬

무료 판별 규칙과 후보 레코드 변환, 정렬을 구현한다. **이 태스크의 테스트가 이 프로젝트에서 가장 중요한 회귀 방지선이다** — 규칙이 느슨해지면 사용자의 유료 할당량을 태운다.

**Files:**
- Modify: `skills/fiftybox-free-execute/scripts/discover_free_models.py`
- Test: `skills/fiftybox-free-execute/tests/test_discover_free_models.py`

**Interfaces:**
- Consumes: `parse_verbose_models(text) -> list[tuple[str, dict]]` (Task 1)
- Produces:
  - `is_free_candidate(entry: dict) -> bool`
  - `to_candidate(model_id: str, entry: dict) -> dict` — `{"id","context","toolcall","smoke","latency_ms"}`. `smoke`는 `"unknown"`, `latency_ms`는 `None`으로 초기화.
  - `sort_candidates(candidates: list[dict]) -> list[dict]`

- [ ] **Step 1: 실패하는 테스트 작성**

`skills/fiftybox-free-execute/tests/test_discover_free_models.py` 끝에 추가:

```python
class TestIsFreeCandidate:
    def _entry(self, **overrides) -> dict:
        base = {
            "providerID": "opencode",
            "status": "active",
            "cost": {"input": 0, "output": 0},
            "limit": {"context": 200000},
            "capabilities": {"toolcall": True},
        }
        base.update(overrides)
        return base

    def test_accepts_opencode_zero_cost_toolcall_active(self):
        assert dfm.is_free_candidate(self._entry()) is True

    def test_rejects_other_provider_even_at_zero_cost(self):
        assert dfm.is_free_candidate(self._entry(providerID="openai")) is False
        assert dfm.is_free_candidate(self._entry(providerID="zai")) is False
        assert dfm.is_free_candidate(self._entry(providerID="opencode-go")) is False

    def test_rejects_nonzero_input_cost(self):
        assert dfm.is_free_candidate(self._entry(cost={"input": 0.14, "output": 0})) is False

    def test_rejects_nonzero_output_cost(self):
        assert dfm.is_free_candidate(self._entry(cost={"input": 0, "output": 0.28})) is False

    def test_rejects_missing_toolcall(self):
        assert dfm.is_free_candidate(self._entry(capabilities={"toolcall": False})) is False

    def test_rejects_inactive_status(self):
        assert dfm.is_free_candidate(self._entry(status="deprecated")) is False

    def test_rejects_entry_missing_keys(self):
        assert dfm.is_free_candidate({}) is False
        assert dfm.is_free_candidate({"providerID": "opencode"}) is False


class TestFilterAgainstRealFixture:
    """The regression tests that matter: which models survive the filter."""

    def _surviving_ids(self, verbose_text) -> list[str]:
        parsed = dfm.parse_verbose_models(verbose_text)
        return [mid for mid, entry in parsed if dfm.is_free_candidate(entry)]

    def test_big_pickle_included_despite_no_free_suffix(self, verbose_text):
        assert "opencode/big-pickle" in self._surviving_ids(verbose_text)

    def test_openai_pro_excluded_despite_zero_cost(self, verbose_text):
        assert "openai/gpt-5.6-pro" not in self._surviving_ids(verbose_text)

    def test_zai_flash_excluded_despite_zero_cost(self, verbose_text):
        assert "zai/glm-4.5-flash" not in self._surviving_ids(verbose_text)

    def test_paid_opencode_go_excluded(self, verbose_text):
        assert "opencode-go/deepseek-v4-flash" not in self._surviving_ids(verbose_text)

    def test_non_toolcall_free_model_excluded(self, verbose_text):
        assert "opencode/legacy-chat-free" not in self._surviving_ids(verbose_text)

    def test_deprecated_free_model_excluded(self, verbose_text):
        assert "opencode/retired-free" not in self._surviving_ids(verbose_text)

    def test_exact_surviving_set(self, verbose_text):
        assert set(self._surviving_ids(verbose_text)) == {
            "opencode/big-pickle",
            "opencode/mimo-v2.5-free",
            "opencode/nemotron-3-ultra-free",
        }


class TestToCandidate:
    def test_builds_record_with_unknown_smoke(self):
        entry = {
            "providerID": "opencode",
            "status": "active",
            "cost": {"input": 0, "output": 0},
            "limit": {"context": 256000},
            "capabilities": {"toolcall": True},
        }
        assert dfm.to_candidate("opencode/x-free", entry) == {
            "id": "opencode/x-free",
            "context": 256000,
            "toolcall": True,
            "smoke": "unknown",
            "latency_ms": None,
        }

    def test_missing_context_becomes_none(self):
        entry = {"capabilities": {"toolcall": True}}
        assert dfm.to_candidate("opencode/y-free", entry)["context"] is None


class TestSortCandidates:
    def test_ok_before_non_ok(self):
        cands = [
            {"id": "a", "context": 1000000, "smoke": "rate_limited"},
            {"id": "b", "context": 100000, "smoke": "ok"},
        ]
        assert [c["id"] for c in dfm.sort_candidates(cands)] == ["b", "a"]

    def test_larger_context_first_within_same_smoke(self):
        cands = [
            {"id": "a", "context": 200000, "smoke": "ok"},
            {"id": "b", "context": 1000000, "smoke": "ok"},
        ]
        assert [c["id"] for c in dfm.sort_candidates(cands)] == ["b", "a"]

    def test_none_context_sorts_last(self):
        cands = [
            {"id": "a", "context": None, "smoke": "ok"},
            {"id": "b", "context": 100000, "smoke": "ok"},
        ]
        assert [c["id"] for c in dfm.sort_candidates(cands)] == ["b", "a"]
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python3 -m pytest skills/fiftybox-free-execute/tests/test_discover_free_models.py -v`
Expected: FAIL — `AttributeError: module 'discover_free_models' has no attribute 'is_free_candidate'`

- [ ] **Step 3: 최소 구현 작성**

`discover_free_models.py`의 `parse_plain_models` 아래에 추가:

```python
FREE_PROVIDER = "opencode"


def is_free_candidate(entry: dict) -> bool:
    """True only for opencode Zen free-tier models usable as an implementer.

    Cost alone is not sufficient: subscription-authenticated providers such as
    openai and zai also report zero cost but consume the user's paid quota.
    The provider scope is therefore part of the rule, not an optimisation.
    """
    if not isinstance(entry, dict):
        return False
    if entry.get("providerID") != FREE_PROVIDER:
        return False
    if entry.get("status") != "active":
        return False
    cost = entry.get("cost")
    if not isinstance(cost, dict):
        return False
    if cost.get("input") != 0 or cost.get("output") != 0:
        return False
    capabilities = entry.get("capabilities")
    if not isinstance(capabilities, dict):
        return False
    return capabilities.get("toolcall") is True


def to_candidate(model_id: str, entry: dict) -> dict:
    """Build the candidate record emitted to stdout (pre-smoke-test)."""
    limit = entry.get("limit") if isinstance(entry.get("limit"), dict) else {}
    capabilities = entry.get("capabilities") if isinstance(entry.get("capabilities"), dict) else {}
    return {
        "id": model_id,
        "context": limit.get("context"),
        "toolcall": capabilities.get("toolcall"),
        "smoke": "unknown",
        "latency_ms": None,
    }


def sort_candidates(candidates: list[dict]) -> list[dict]:
    """Sort by smoke result (ok first), then by descending context."""
    def key(candidate: dict):
        context = candidate.get("context")
        return (
            0 if candidate.get("smoke") == "ok" else 1,
            -(context if isinstance(context, int) else -1),
        )

    return sorted(candidates, key=key)
```

- [ ] **Step 4: 테스트가 통과하는지 확인**

Run: `python3 -m pytest skills/fiftybox-free-execute/tests/test_discover_free_models.py -v`
Expected: PASS (전체 통과, 필터 회귀 테스트 포함)

- [ ] **Step 5: 커밋**

```bash
git add skills/fiftybox-free-execute/scripts/discover_free_models.py \
        skills/fiftybox-free-execute/tests/test_discover_free_models.py
git commit -m "feat(free-execute): filter opencode free-tier candidates by provider and cost"
```

---

### Task 3: 스모크 테스트 실행과 분류

후보가 지금 실제로 응답하는지 확인하고 결과를 분류한다.

**Files:**
- Modify: `skills/fiftybox-free-execute/scripts/discover_free_models.py`
- Test: `skills/fiftybox-free-execute/tests/test_discover_free_models.py`

**Interfaces:**
- Consumes: `to_candidate(...) -> dict` (Task 2)
- Produces:
  - `classify_smoke(returncode: int, output: str, timed_out: bool) -> str` — `"ok" | "rate_limited" | "error" | "timeout"`
  - `run_smoke_test(model_id: str, timeout: int = SMOKE_TIMEOUT_SECONDS) -> tuple[str, int]` — `(분류, 지연ms)`
  - `smoke_test_all(candidates: list[dict], max_workers: int = SMOKE_MAX_WORKERS) -> list[dict]` — 각 후보의 `smoke`·`latency_ms`를 채운 새 리스트
  - 상수 `SMOKE_TIMEOUT_SECONDS = 30`, `SMOKE_MAX_WORKERS = 4`, `SMOKE_PROMPT`

- [ ] **Step 1: 실패하는 테스트 작성**

`test_discover_free_models.py` 끝에 추가:

```python
import subprocess  # noqa: E402  (used by the smoke tests below)


class TestClassifySmoke:
    def test_zero_exit_is_ok(self):
        assert dfm.classify_smoke(0, "OK", timed_out=False) == "ok"

    def test_timed_out_wins_over_exit_code(self):
        assert dfm.classify_smoke(0, "OK", timed_out=True) == "timeout"

    def test_429_is_rate_limited(self):
        assert dfm.classify_smoke(1, "HTTP 429 Too Many Requests", timed_out=False) == "rate_limited"

    def test_rate_limit_phrase_is_rate_limited(self):
        assert dfm.classify_smoke(1, "Error: rate limit exceeded", timed_out=False) == "rate_limited"

    def test_quota_phrase_is_rate_limited(self):
        assert dfm.classify_smoke(1, "monthly QUOTA exhausted", timed_out=False) == "rate_limited"

    def test_insufficient_phrase_is_rate_limited(self):
        assert dfm.classify_smoke(1, "insufficient credits", timed_out=False) == "rate_limited"

    def test_other_failure_is_error(self):
        assert dfm.classify_smoke(1, "connection refused", timed_out=False) == "error"

    def test_rate_limit_pattern_wins_even_on_zero_exit(self):
        assert dfm.classify_smoke(0, "warning: rate limit near", timed_out=False) == "rate_limited"


class TestRunSmokeTest:
    def test_invokes_opencode_run_with_model(self, monkeypatch):
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return subprocess.CompletedProcess(cmd, 0, stdout="OK", stderr="")

        monkeypatch.setattr(dfm.subprocess, "run", fake_run)
        result, latency = dfm.run_smoke_test("opencode/mimo-v2.5-free")

        assert result == "ok"
        assert isinstance(latency, int)
        assert captured["cmd"][:2] == ["opencode", "run"]
        assert "--model" in captured["cmd"]
        assert captured["cmd"][captured["cmd"].index("--model") + 1] == "opencode/mimo-v2.5-free"

    def test_runs_in_a_temporary_directory_not_the_repo(self, monkeypatch):
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cwd"] = kwargs.get("cwd")
            return subprocess.CompletedProcess(cmd, 0, stdout="OK", stderr="")

        monkeypatch.setattr(dfm.subprocess, "run", fake_run)
        dfm.run_smoke_test("opencode/x-free")

        assert captured["cwd"] is not None
        assert Path(captured["cwd"]) != Path.cwd()

    def test_never_passes_skip_permissions(self, monkeypatch):
        """The smoke prompt makes no edits, so it must not request write access."""
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0, stdout="OK", stderr="")

        monkeypatch.setattr(dfm.subprocess, "run", fake_run)
        dfm.run_smoke_test("opencode/x-free")

        assert "--dangerously-skip-permissions" not in captured["cmd"]

    def test_timeout_expired_is_classified_timeout(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 30)

        monkeypatch.setattr(dfm.subprocess, "run", fake_run)
        assert dfm.run_smoke_test("opencode/x-free")[0] == "timeout"

    def test_missing_binary_is_error(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            raise FileNotFoundError("opencode")

        monkeypatch.setattr(dfm.subprocess, "run", fake_run)
        assert dfm.run_smoke_test("opencode/x-free")[0] == "error"

    def test_stderr_is_considered_for_classification(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="429 rate limit")

        monkeypatch.setattr(dfm.subprocess, "run", fake_run)
        assert dfm.run_smoke_test("opencode/x-free")[0] == "rate_limited"


class TestSmokeTestAll:
    def test_fills_smoke_and_latency_for_each_candidate(self, monkeypatch):
        monkeypatch.setattr(dfm, "run_smoke_test", lambda model_id, timeout=30: ("ok", 1234))
        candidates = [
            {"id": "opencode/a", "context": 100, "toolcall": True, "smoke": "unknown", "latency_ms": None},
            {"id": "opencode/b", "context": 200, "toolcall": True, "smoke": "unknown", "latency_ms": None},
        ]
        result = dfm.smoke_test_all(candidates)
        assert all(c["smoke"] == "ok" for c in result)
        assert all(c["latency_ms"] == 1234 for c in result)

    def test_does_not_mutate_input(self, monkeypatch):
        monkeypatch.setattr(dfm, "run_smoke_test", lambda model_id, timeout=30: ("ok", 5))
        candidates = [{"id": "opencode/a", "context": 1, "toolcall": True, "smoke": "unknown", "latency_ms": None}]
        dfm.smoke_test_all(candidates)
        assert candidates[0]["smoke"] == "unknown"

    def test_per_model_results_are_not_swapped(self, monkeypatch):
        monkeypatch.setattr(
            dfm, "run_smoke_test",
            lambda model_id, timeout=30: ("ok", 1) if model_id == "opencode/a" else ("rate_limited", 2),
        )
        candidates = [
            {"id": "opencode/a", "context": 1, "toolcall": True, "smoke": "unknown", "latency_ms": None},
            {"id": "opencode/b", "context": 2, "toolcall": True, "smoke": "unknown", "latency_ms": None},
        ]
        by_id = {c["id"]: c for c in dfm.smoke_test_all(candidates)}
        assert by_id["opencode/a"]["smoke"] == "ok"
        assert by_id["opencode/b"]["smoke"] == "rate_limited"

    def test_empty_list_returns_empty(self):
        assert dfm.smoke_test_all([]) == []
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python3 -m pytest skills/fiftybox-free-execute/tests/test_discover_free_models.py -v -k "Smoke"`
Expected: FAIL — `AttributeError: module 'discover_free_models' has no attribute 'classify_smoke'`

- [ ] **Step 3: 최소 구현 작성**

`discover_free_models.py` 상단 import에 추가:

```python
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
```

파일 끝에 추가:

```python
SMOKE_TIMEOUT_SECONDS = 30
SMOKE_MAX_WORKERS = 4
SMOKE_PROMPT = "reply with exactly: OK"
RATE_LIMIT_PATTERNS = ("429", "rate limit", "quota", "insufficient")


def classify_smoke(returncode: int, output: str, timed_out: bool) -> str:
    """Classify one smoke-test run.

    opencode does not distinguish rate limiting by exit code, so the output is
    pattern-matched. A rate-limit phrase wins even on a zero exit code.
    """
    if timed_out:
        return "timeout"
    lowered = (output or "").lower()
    if any(pattern in lowered for pattern in RATE_LIMIT_PATTERNS):
        return "rate_limited"
    return "ok" if returncode == 0 else "error"


def run_smoke_test(model_id: str, timeout: int = SMOKE_TIMEOUT_SECONDS) -> tuple[str, int]:
    """Ask one model a trivial question in a throwaway directory.

    The prompt makes no edits, so no permission flag is passed and the user's
    repository is never the working directory.
    """
    cmd = ["opencode", "run", "--model", model_id, "--format", "json", SMOKE_PROMPT]
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="fiftybox-smoke-") as workdir:
        try:
            proc = subprocess.run(
                cmd, cwd=workdir, capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return "timeout", int((time.monotonic() - started) * 1000)
        except (FileNotFoundError, OSError):
            return "error", int((time.monotonic() - started) * 1000)
    latency_ms = int((time.monotonic() - started) * 1000)
    combined = f"{proc.stdout}\n{proc.stderr}"
    return classify_smoke(proc.returncode, combined, timed_out=False), latency_ms


def smoke_test_all(
    candidates: list[dict], max_workers: int = SMOKE_MAX_WORKERS
) -> list[dict]:
    """Smoke-test every candidate concurrently, returning updated copies."""
    if not candidates:
        return []
    results = [dict(candidate) for candidate in candidates]
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        outcomes = list(pool.map(lambda c: run_smoke_test(c["id"]), results))
    for candidate, (smoke, latency_ms) in zip(results, outcomes):
        candidate["smoke"] = smoke
        candidate["latency_ms"] = latency_ms
    return results
```

- [ ] **Step 4: 테스트가 통과하는지 확인**

Run: `python3 -m pytest skills/fiftybox-free-execute/tests/test_discover_free_models.py -v`
Expected: PASS (전체 통과)

- [ ] **Step 5: 커밋**

```bash
git add skills/fiftybox-free-execute/scripts/discover_free_models.py \
        skills/fiftybox-free-execute/tests/test_discover_free_models.py
git commit -m "feat(free-execute): smoke-test free candidates and classify rate limits"
```

---

### Task 4: 탐색 오케스트레이션과 CLI

CLI 진입점을 만들어 stdout에 JSON 한 덩어리를 낸다. 메타데이터 파싱이 전면 실패하면 평문 폴백으로 후퇴한다.

**Files:**
- Modify: `skills/fiftybox-free-execute/scripts/discover_free_models.py`
- Test: `skills/fiftybox-free-execute/tests/test_discover_free_models.py`

**Interfaces:**
- Consumes: `parse_verbose_models`, `parse_plain_models` (Task 1), `is_free_candidate`, `to_candidate`, `sort_candidates` (Task 2), `smoke_test_all` (Task 3)
- Produces:
  - `list_models_verbose() -> str` / `list_models_plain() -> str` — opencode CLI 호출 래퍼
  - `discover(skip_smoke: bool = False) -> dict` — `{"metadata_degraded": bool, "candidates": [...]}`
  - `main(argv: list[str] | None = None) -> int` — JSON을 stdout에 출력

- [ ] **Step 1: 실패하는 테스트 작성**

`test_discover_free_models.py` 끝에 추가:

```python
import json as _json  # noqa: E402


class TestDiscover:
    def test_returns_sorted_free_candidates(self, monkeypatch, verbose_text):
        monkeypatch.setattr(dfm, "list_models_verbose", lambda: verbose_text)
        monkeypatch.setattr(dfm, "smoke_test_all", lambda cands, **kw: [
            {**c, "smoke": "ok", "latency_ms": 100} for c in cands
        ])
        result = dfm.discover()
        assert result["metadata_degraded"] is False
        ids = [c["id"] for c in result["candidates"]]
        assert set(ids) == {
            "opencode/big-pickle",
            "opencode/mimo-v2.5-free",
            "opencode/nemotron-3-ultra-free",
        }
        assert ids[0] == "opencode/nemotron-3-ultra-free"  # largest context first

    def test_skip_smoke_leaves_smoke_unknown(self, monkeypatch, verbose_text):
        monkeypatch.setattr(dfm, "list_models_verbose", lambda: verbose_text)
        result = dfm.discover(skip_smoke=True)
        assert all(c["smoke"] == "unknown" for c in result["candidates"])

    def test_falls_back_to_plain_when_verbose_unparseable(self, monkeypatch, plain_text):
        monkeypatch.setattr(dfm, "list_models_verbose", lambda: "garbage with no json")
        monkeypatch.setattr(dfm, "list_models_plain", lambda: plain_text)
        monkeypatch.setattr(dfm, "smoke_test_all", lambda cands, **kw: [
            {**c, "smoke": "ok", "latency_ms": 10} for c in cands
        ])
        result = dfm.discover()
        assert result["metadata_degraded"] is True
        assert {c["id"] for c in result["candidates"]} == {
            "opencode/big-pickle",
            "opencode/mimo-v2.5-free",
            "opencode/nemotron-3-ultra-free",
        }

    def test_degraded_candidates_have_unknown_metadata(self, monkeypatch, plain_text):
        monkeypatch.setattr(dfm, "list_models_verbose", lambda: "garbage")
        monkeypatch.setattr(dfm, "list_models_plain", lambda: plain_text)
        monkeypatch.setattr(dfm, "smoke_test_all", lambda cands, **kw: cands)
        result = dfm.discover()
        assert all(c["context"] is None and c["toolcall"] is None for c in result["candidates"])

    def test_degraded_fallback_still_scopes_to_opencode_provider(self, monkeypatch):
        monkeypatch.setattr(dfm, "list_models_verbose", lambda: "garbage")
        monkeypatch.setattr(
            dfm, "list_models_plain",
            lambda: "opencode/a-free\nopencode-go/paid\nopenai/gpt-5.6-pro\n",
        )
        monkeypatch.setattr(dfm, "smoke_test_all", lambda cands, **kw: cands)
        result = dfm.discover()
        assert [c["id"] for c in result["candidates"]] == ["opencode/a-free"]

    def test_no_candidates_returns_empty_list_not_error(self, monkeypatch):
        monkeypatch.setattr(dfm, "list_models_verbose", lambda: "")
        monkeypatch.setattr(dfm, "list_models_plain", lambda: "")
        result = dfm.discover()
        assert result["candidates"] == []


class TestMain:
    def test_prints_json_document(self, monkeypatch, capsys, verbose_text):
        monkeypatch.setattr(dfm, "list_models_verbose", lambda: verbose_text)
        monkeypatch.setattr(dfm, "smoke_test_all", lambda cands, **kw: [
            {**c, "smoke": "ok", "latency_ms": 1} for c in cands
        ])
        exit_code = dfm.main([])
        payload = _json.loads(capsys.readouterr().out)
        assert exit_code == 0
        assert payload["metadata_degraded"] is False
        assert len(payload["candidates"]) == 3

    def test_skip_smoke_flag_is_honoured(self, monkeypatch, capsys, verbose_text):
        monkeypatch.setattr(dfm, "list_models_verbose", lambda: verbose_text)
        dfm.main(["--skip-smoke"])
        payload = _json.loads(capsys.readouterr().out)
        assert all(c["smoke"] == "unknown" for c in payload["candidates"])

    def test_exit_code_zero_even_with_no_candidates(self, monkeypatch, capsys):
        monkeypatch.setattr(dfm, "list_models_verbose", lambda: "")
        monkeypatch.setattr(dfm, "list_models_plain", lambda: "")
        assert dfm.main([]) == 0
        assert _json.loads(capsys.readouterr().out)["candidates"] == []
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python3 -m pytest skills/fiftybox-free-execute/tests/test_discover_free_models.py -v -k "Discover or Main"`
Expected: FAIL — `AttributeError: module 'discover_free_models' has no attribute 'discover'`

- [ ] **Step 3: 최소 구현 작성**

`discover_free_models.py` 상단 import에 `import argparse`, `import sys`를 추가하고 파일 끝에 추가:

```python
LIST_TIMEOUT_SECONDS = 60


def _run_capture(cmd: list[str]) -> str:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=LIST_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""
    return proc.stdout or ""


def list_models_verbose() -> str:
    return _run_capture(
        ["opencode", "models", FREE_PROVIDER, "--verbose", "--refresh"]
    )


def list_models_plain() -> str:
    return _run_capture(["opencode", "models", FREE_PROVIDER])


def discover(skip_smoke: bool = False) -> dict:
    """Find opencode free-tier models that can act as an implementer.

    Falls back to the plain listing when no verbose block parses, rather than
    reporting an empty list — a format change must be visible, not silent.
    """
    parsed = parse_verbose_models(list_models_verbose())
    metadata_degraded = not parsed

    if parsed:
        candidates = [
            to_candidate(model_id, entry)
            for model_id, entry in parsed
            if is_free_candidate(entry)
        ]
    else:
        prefix = f"{FREE_PROVIDER}/"
        candidates = [
            {"id": model_id, "context": None, "toolcall": None,
             "smoke": "unknown", "latency_ms": None}
            for model_id in parse_plain_models(list_models_plain())
            if model_id.startswith(prefix)
        ]

    if candidates and not skip_smoke:
        candidates = smoke_test_all(candidates)

    return {
        "metadata_degraded": metadata_degraded,
        "candidates": sort_candidates(candidates),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-smoke", action="store_true",
        help="List candidates from metadata only, without calling each model.",
    )
    args = parser.parse_args(argv)
    print(json.dumps(discover(skip_smoke=args.skip_smoke), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 테스트가 통과하는지 확인**

Run: `python3 -m pytest skills/fiftybox-free-execute/tests/test_discover_free_models.py -v`
Expected: PASS (전체 통과)

- [ ] **Step 5: 실제 CLI로 한 번 확인**

Run: `python3 skills/fiftybox-free-execute/scripts/discover_free_models.py --skip-smoke`
Expected: `metadata_degraded: false`이고 `candidates`에 `opencode/` 모델만, 각각 `context`와 `toolcall: true`가 채워진 JSON. `openai/`나 `zai/` 항목이 하나라도 있으면 필터가 잘못된 것이므로 멈추고 Task 2를 다시 볼 것.

- [ ] **Step 6: 커밋**

```bash
git add skills/fiftybox-free-execute/scripts/discover_free_models.py \
        skills/fiftybox-free-execute/tests/test_discover_free_models.py
git commit -m "feat(free-execute): add discover CLI with degraded-metadata fallback"
```

---

### Task 5: orchestrate.py에 `--implement-agent` 오버라이드 추가

호출 단위로 구현 에이전트를 바꿀 수 있게 한다. 플래그를 넘기지 않으면 기존 동작이 그대로여야 한다.

**Files:**
- Modify: `skills/fiftybox-orchestration/scripts/orchestrate.py` (`load_agent_config` 아래에 함수 추가, `parse_args`에 인자 추가, `load_agent_config(SKILL_DIR)` 호출부 교체)
- Test: `skills/fiftybox-orchestration/tests/test_agent_config.py`

**Interfaces:**
- Consumes: 기존 `load_agent_config(skill_dir: Path) -> dict[str, Any]`
- Produces: `resolve_agent_config(skill_dir: Path, args: argparse.Namespace) -> dict[str, Any]` — `load_agent_config` 결과에 `args.implement_agent`가 비어있지 않으면 `implement_agent` 키를 덮어쓴 **새 딕셔너리**를 반환

- [ ] **Step 1: 실패하는 테스트 작성**

`skills/fiftybox-orchestration/tests/test_agent_config.py` 끝에 추가:

```python
class TestResolveAgentConfig:
    """--implement-agent overrides config.json for a single orchestrate call."""

    def _args(self, implement_agent=""):
        return argparse.Namespace(implement_agent=implement_agent)

    def test_no_override_keeps_config_value(self, tmp_path):
        (tmp_path / "config.json").write_text(
            json.dumps({"implement_agent": "aider"}), encoding="utf-8"
        )
        config = orc.resolve_agent_config(tmp_path, self._args())
        assert config["implement_agent"] == "aider"

    def test_no_override_keeps_pi_default_when_no_config(self, tmp_path):
        config = orc.resolve_agent_config(tmp_path, self._args())
        assert config["implement_agent"] == "pi"

    def test_override_replaces_config_value(self, tmp_path):
        (tmp_path / "config.json").write_text(
            json.dumps({"implement_agent": "aider"}), encoding="utf-8"
        )
        config = orc.resolve_agent_config(tmp_path, self._args("opencode"))
        assert config["implement_agent"] == "opencode"

    def test_override_does_not_touch_explore_agent(self, tmp_path):
        (tmp_path / "config.json").write_text(
            json.dumps({"explore_agent": "gemini", "implement_agent": "aider"}),
            encoding="utf-8",
        )
        config = orc.resolve_agent_config(tmp_path, self._args("opencode"))
        assert config["explore_agent"] == "gemini"

    def test_empty_string_override_is_ignored(self, tmp_path):
        (tmp_path / "config.json").write_text(
            json.dumps({"implement_agent": "aider"}), encoding="utf-8"
        )
        assert orc.resolve_agent_config(tmp_path, self._args(""))["implement_agent"] == "aider"

    def test_missing_attribute_is_treated_as_no_override(self, tmp_path):
        (tmp_path / "config.json").write_text(
            json.dumps({"implement_agent": "aider"}), encoding="utf-8"
        )
        config = orc.resolve_agent_config(tmp_path, argparse.Namespace())
        assert config["implement_agent"] == "aider"

    def test_agents_dict_is_preserved(self, tmp_path):
        config = orc.resolve_agent_config(tmp_path, self._args("opencode"))
        assert "opencode" in config["agents"]
        assert "pi" in config["agents"]

    def test_unknown_override_name_survives_to_validation(self, tmp_path):
        """resolve_ does not validate; phase_setup reports the unknown name."""
        config = orc.resolve_agent_config(tmp_path, self._args("nope"))
        assert config["implement_agent"] == "nope"
        with pytest.raises(ValueError, match="Unknown agent 'nope'"):
            orc.build_agent_cmd(
                "nope", config, prompt="p", task="t",
                model="m", provider="pr", adapters_dir=tmp_path,
            )


class TestImplementAgentArg:
    def test_defaults_to_empty_string(self):
        args = orc.parse_args(["--phase", "setup", "--task", "t"])
        assert args.implement_agent == ""

    def test_accepts_value(self):
        args = orc.parse_args(
            ["--phase", "implement", "--task", "t", "--implement-agent", "opencode"]
        )
        assert args.implement_agent == "opencode"
```

파일 상단 import 블록에 `import argparse`가 없으면 추가한다.

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python3 -m pytest skills/fiftybox-orchestration/tests/test_agent_config.py -v -k "ResolveAgentConfig or ImplementAgentArg"`
Expected: FAIL — `AttributeError: module 'orchestrate' has no attribute 'resolve_agent_config'`

- [ ] **Step 3: `resolve_agent_config` 구현**

`orchestrate.py`의 `load_agent_config` 함수 정의 바로 다음에 추가:

```python
def resolve_agent_config(skill_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    """Load config.json, then apply per-invocation agent overrides.

    `--implement-agent` lets one skill run a different implementer without
    mutating the shared config.json, which other sessions read concurrently.
    Validation stays in phase_setup: an unknown name must fail there with the
    existing message, not silently here.
    """
    config = load_agent_config(skill_dir)
    override = (getattr(args, "implement_agent", "") or "").strip()
    if override:
        return {**config, "implement_agent": override}
    return config
```

- [ ] **Step 4: `--implement-agent` 인자 추가**

`parse_args`에서 `--provider` 인자 바로 다음 줄에 추가:

```python
    parser.add_argument(
        "--implement-agent",
        default="",
        help="Override config.json's implement_agent for this invocation only "
        "(e.g. opencode). Empty (default) uses the configured agent.",
    )
```

- [ ] **Step 5: 호출부 교체**

`orchestrate.py`에서 `load_agent_config(SKILL_DIR)` 호출을 `resolve_agent_config(SKILL_DIR, args)`로 바꾼다. **`args`가 스코프에 있는 곳만** 바꾼다:

- `phase_setup` (기존 `agent_config = load_agent_config(SKILL_DIR)`)
- `phase_explore`
- `phase_implement` (`agent_config_pre`와 그 아래 `agent_config` 둘 다)
- `phase_pi_complete` (`_pic_agent` 줄과 `agent_config` 줄)
- `phase_pi_deploy` (`_pid_agent` 줄과 `agent_config` 줄)
- `phase_deploy` (`_deploy_agent` 줄과 `agent_config` 줄)

`run_design_review_agent`는 `args`를 받지 않고 `explore_agent`만 쓰므로 **바꾸지 않는다**.

교체가 빠짐없이 됐는지 확인:

```bash
grep -n "load_agent_config(SKILL_DIR)" skills/fiftybox-orchestration/scripts/orchestrate.py
```
Expected: `run_design_review_agent` 안의 한 줄만 남아야 한다.

- [ ] **Step 6: 테스트가 통과하는지 확인**

Run: `python3 -m pytest skills/fiftybox-orchestration/tests/ -v`
Expected: PASS — 신규 테스트 + **기존 테스트 전부**. 기존 테스트가 하나라도 깨지면 회귀이므로 멈추고 고칠 것.

- [ ] **Step 7: 커밋**

```bash
git add skills/fiftybox-orchestration/scripts/orchestrate.py \
        skills/fiftybox-orchestration/tests/test_agent_config.py
git commit -m "feat(orchestrate): add --implement-agent per-invocation override"
```

---

### Task 6: opencode 어댑터 커맨드 수정

현재 `opencode` 어댑터는 존재하지 않는 `--print` 플래그를 써서 실행 즉시 실패한다.

**Files:**
- Modify: `skills/fiftybox-orchestration/scripts/orchestrate.py:82` (`BUILTIN_AGENTS["opencode"]`)
- Modify: `skills/fiftybox-orchestration/config.example.json`
- Test: `skills/fiftybox-orchestration/tests/test_agent_config.py`

**Interfaces:**
- Consumes: `build_agent_cmd(agent_name, config, *, prompt, task, model, provider, adapters_dir) -> list[str]` (기존)
- Produces: 없음 (데이터 수정)

- [ ] **Step 1: 실패하는 테스트 작성**

`test_agent_config.py`의 `TestBuiltinAgents` 클래스 안에 추가:

```python
    def test_opencode_cmd_has_no_print_flag(self):
        """opencode run has no --print; it would fail immediately."""
        assert "--print" not in orc.BUILTIN_AGENTS["opencode"]["cmd"]

    def test_opencode_cmd_skips_permissions(self):
        """Non-interactive runs cannot approve edits, so the flag is required."""
        assert "--dangerously-skip-permissions" in orc.BUILTIN_AGENTS["opencode"]["cmd"]

    def test_opencode_cmd_passes_model(self):
        cmd = orc.BUILTIN_AGENTS["opencode"]["cmd"]
        assert cmd[:2] == ["opencode", "run"]
        assert "--model" in cmd
        assert cmd[cmd.index("--model") + 1] == "{model}"
```

`TestBuildAgentCmd` 클래스 안에 추가:

```python
    def test_opencode_cmd_substitutes_model(self, tmp_path):
        config = {"agents": dict(orc.BUILTIN_AGENTS)}
        cmd = orc.build_agent_cmd(
            "opencode", config, prompt="PROMPT", task="TASK",
            model="opencode/mimo-v2.5-free", provider="unused", adapters_dir=tmp_path,
        )
        assert cmd[cmd.index("--model") + 1] == "opencode/mimo-v2.5-free"
        assert "--print" not in cmd
        assert "--dangerously-skip-permissions" in cmd
        assert any("PROMPT" in token and "TASK" in token for token in cmd)
```

`TestBuildAgentCmd`에 `config` 픽스처가 이미 있다면 그 형태를 따르고, 없으면 위처럼 인라인으로 만든다.

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python3 -m pytest skills/fiftybox-orchestration/tests/test_agent_config.py -v -k "opencode"`
Expected: FAIL — `assert '--print' not in [...]`

- [ ] **Step 3: `BUILTIN_AGENTS` 수정**

`orchestrate.py:82`:

```python
    "opencode": {"cmd": ["opencode", "run", "--model", "{model}",
                         "--dangerously-skip-permissions", "{prompt}\n{task}"]},
```

- [ ] **Step 4: `config.example.json` 수정**

`skills/fiftybox-orchestration/config.example.json`의 `opencode` 항목을 동일하게 바꾼다:

```json
    "opencode": {
      "cmd": ["opencode", "run", "--model", "{model}",
              "--dangerously-skip-permissions", "{prompt}\n{task}"]
    },
```

- [ ] **Step 5: 테스트가 통과하는지 확인**

Run: `python3 -m pytest skills/fiftybox-orchestration/tests/ -v`
Expected: PASS (전체)

- [ ] **Step 6: 실제 어댑터가 도는지 확인**

Run:
```bash
cd "$(mktemp -d)" && opencode run --model opencode/mimo-v2.5-free \
  --dangerously-skip-permissions "reply with exactly: OK"
```
Expected: 모델이 응답한다(정확한 문구는 달라도 됨). `unknown option --print` 류의 에러가 없어야 한다. 해당 모델이 rate limit이면 `discover_free_models.py --skip-smoke` 출력에서 다른 `opencode/` 모델을 골라 다시 시도한다.

- [ ] **Step 7: 커밋**

```bash
git add skills/fiftybox-orchestration/scripts/orchestrate.py \
        skills/fiftybox-orchestration/config.example.json \
        skills/fiftybox-orchestration/tests/test_agent_config.py
git commit -m "fix(orchestrate): repair opencode adapter cmd for current CLI"
```

---

### Task 7: SKILL.md와 슬래시 커맨드

워크플로 문서를 쓰고 설치 경로에 연결한다.

**Files:**
- Create: `skills/fiftybox-free-execute/SKILL.md`
- Create: `commands/fiftybox-free-execute.md`
- Modify: `install.sh`
- Modify: `tests/test_install.sh`

**Interfaces:**
- Consumes: `discover_free_models.py`의 CLI (Task 4), `orchestrate.py --implement-agent` (Task 5)
- Produces: 없음 (문서)

- [ ] **Step 1: SKILL.md 작성**

`skills/fiftybox-free-execute/SKILL.md`:

````markdown
---
name: fiftybox-free-execute
description: opencode 무료 모델로 구현하는 순차 TDD 실행 파이프라인 — 사용 가능한 무료 모델을 탐색해 사용자가 고르고, Claude가 테스트를 쓰고 opencode가 구현하고 Claude가 리뷰한다. 비용 없이 구현을 돌리고 싶을 때 사용한다.
---

# Fiftybox Free Execute

opencode Zen 무료 티어 모델로 구현 페이즈를 돌린다. 무료 티어는 제공 모델과
할당량이 수시로 바뀌므로 **실행할 때마다 탐색하고 사용자가 고른다.**

**핵심 루프:** Claude가 실패하는 테스트 작성(Red) → opencode가 통과시킴(Green) → Claude 리뷰

**실행 방식:** 완전 순차. 태스크를 한 번에 하나씩 처리한다. 무료 티어의 동시 요청·
분당 토큰 제한을 태우지 않기 위해서다.

---

## ⛔ 절대 금지

**Claude는 구현 파일을 직접 쓰거나 고치지 않는다.** 예외 없다. 구현이 "뻔해
보여도", 계획서에 붙여넣기만 하면 되는 코드가 있어도, orchestrate.py가 느려도,
태스크가 사소해 보여도 마찬가지다.

Claude가 이 스킬에서 쓸 수 있는 파일은 두 가지뿐이다:
1. 테스트 파일 (Step 5 — Red 페이즈)
2. 아티팩트 문서 (`<artifactDir>/design.md` 등)

orchestrate.py가 실패하면 사용자에게 보고한다. 대신 구현하지 않는다.

---

## 호출

```
/fiftybox-free-execute "<작업 설명>"
```

작업 설명이 없으면 물어본다.

## 워크플로

### Step 1: 무료 모델 탐색

```bash
python3 ~/.claude/skills/fiftybox-free-execute/scripts/discover_free_models.py
```

stdout의 JSON을 읽는다. 수십 초 걸릴 수 있다(후보마다 실제 호출을 한 번씩 한다).

`metadata_degraded`가 `true`면 사용자에게 먼저 알린다:

> opencode 모델 메타데이터를 파싱하지 못했습니다. 모델 목록만으로 진행하며
> 컨텍스트 크기와 툴콜 지원 여부는 확인되지 않았습니다.

### Step 2: 사용자에게 모델 선택 요청

후보를 표로 제시한다. `smoke`가 `ok`인 것을 위에 둔다.

```
사용 가능한 opencode 무료 모델:

  번호  모델                             컨텍스트  응답      상태
  1     opencode/nemotron-3-ultra-free   1.0M      2.1s      ok
  2     opencode/mimo-v2.5-free          200K      1.8s      ok
  3     opencode/laguna-s-2.1-free       256K      -         rate_limited

어떤 모델로 구현할까요? (번호)
```

`smoke`가 `ok`인 후보가 **하나도 없으면** 목록과 각각의 실패 사유를 보여준 뒤
**중단한다.** 유료 모델로 임의 전환하지 않는다. 비용 절감이 이 스킬의 존재 이유다.

선택된 모델 ID는 이 실행 내내 고정된다. 아래에서 `<선택모델>`로 표기한다.

### Step 3: 설계 수집

사용자에게 설계 문서를 요청한다. 다음 중 아무거나 받는다:
- 파일 경로 (`./design.md`, `./PRD.md`, `./plan.md`)
- 대화 중 인라인 텍스트
- "현재 디렉터리 컨텍스트 사용" — 관련 파일을 읽어 설계로 요약

설계를 `<artifactDir>/design.md`에 쓴다(artifactDir은 Step 4에서 생긴다. 그전까지는
메모리에 들고 있는다).

### Step 4: Setup (Phase 0)

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase setup --task "<작업>" --cwd "$(pwd)"
```

JSON 출력에서 `artifactDir`과 `worktree`를 챙긴다.

설계 문서를 아티팩트 디렉터리에 복사하고, Step 1~2의 탐색 결과와 선택을
`<artifactDir>/model-choice.json`에 기록한다:

```json
{
  "selected": "opencode/nemotron-3-ultra-free",
  "selected_at_step": "initial",
  "discovery": { "metadata_degraded": false, "candidates": [] },
  "history": []
}
```

### Step 5: 태스크 분해

설계를 원자적 구현 단위로 쪼개고 의존성을 파악한다. **배치 병렬화는 하지 않는다.**
의존성 그래프를 위상 정렬해 하나의 순차 목록으로 평탄화한다.

`<artifactDir>/task-list.md`에 쓴다:

```markdown
## Task List (순차)

1. Task A: <설명> — 파일: [목록]
2. Task B: <설명> — 파일: [목록], 선행: Task A
3. Task C: <설명> — 파일: [목록], 선행: Task A
```

### Step 6: Claude가 테스트 작성 (Red)

**현재 태스크 하나에 대해서만** Claude가 직접 실패하는 테스트를 쓴다.

1. 태스크 명세에서 기대 동작·입출력·엣지 케이스를 뽑는다
2. 프로젝트 관례에 맞는 테스트 위치를 정한다 (`tests/`, `__tests__/`, `*_test.py`)
3. 프로젝트의 테스트 프레임워크로 테스트 파일을 쓴다

규칙:
- 내부 구조가 아니라 동작을 테스트한다
- 해피 패스·엣지 케이스·에러 케이스를 명세에서 뽑아 덮는다
- 아직 존재하지 않는 함수·클래스를 참조한다 — opencode가 만들 것이다
- 테스트 이름이 수용 기준처럼 읽히게 쓴다

`<artifactDir>/tests/`와 실제 프로젝트 테스트 디렉터리 양쪽에 쓴다.

**실패하는지 확인한다(Red):**

```bash
<프로젝트 테스트 명령> <테스트 파일>
```

구현 전에 통과하면 아무것도 검증하지 않는 테스트다. 다시 쓴다.

### Step 7: 구현 (Green)

> ⛔ 이 단계에서 Claude는 구현 코드를 쓰지 않는다.

**현재 태스크 하나만** 실행한다:

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase implement --task "<현재 태스크 설명>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --implement-agent opencode --model "<선택모델>" --skip-verify
```

`--skip-verify`는 필수다. 이 스킬은 설계 검증을 외부에서 하고 orchestrate의
verify-design 페이즈를 건너뛴다.

전달하는 태스크 설명에 포함할 것:
- 전체 태스크 설명 (파일 경로가 아니라 텍스트를 붙여넣는다)
- 설계 문서의 관련 컨텍스트
- 건드려야 할 파일
- 이 태스크의 **테스트 파일 전체 내용**
- "이 테스트를 통과시켜라. 테스트 파일은 수정하지 마라. 구현 후 테스트를 실행해 확인하라."

실패 시:
- JSON에 `model_unavailable`이 있거나 출력에 rate limit 패턴이 있으면 → 아래
  「모델 소진 처리」로 간다
- 그 외에는 실패를 보고하고 선택지를 제시한다

### Step 8: Claude 리뷰 게이트

태스크마다 Claude(서브에이전트 아님)가 4단계 리뷰를 한다.

**1단계 — 테스트 결과:** Step 6의 테스트를 전부 돌린다. 하나라도 실패하면 실패
출력과 함께 Step 7을 재실행한다.

**2단계 — 테스트 무력화 검사:** opencode가 테스트를 통과시키려고 테스트 자체를
약화시켰는지 본다. `git diff`로 테스트 파일 변경을 확인한다:
- 테스트 파일이 수정됐으면 되돌리고 재실행한다
- 단언이 삭제됐거나 `assert True`로 바뀌었는지
- 스킵 마킹(`@pytest.mark.skip`, `xfail`, `it.skip`)이 추가됐는지
- 구현이 스텁만 채우고 실제 동작이 없는지

무료 모델은 지시 준수율이 낮다. 이 단계를 건너뛰지 않는다.

**3단계 — 명세 준수:** 실제 코드 변경(`git diff`)을 태스크 명세와 한 줄씩
대조한다. 누락된 요구사항, 범위 밖 작업, 오해가 있는지 본다.

**4단계 — 통합 확인:** 선행 태스크와의 인터페이스가 맞는지(함수 시그니처, 공유
타입), 의도치 않은 결합이 생기지 않았는지 확인한다.

문제가 있으면 리뷰 결과를 피드백으로 Step 7을 재실행한다. 두 번째도 실패하면
사용자에게 선택지를 제시한다.

문제가 없으면 다음 태스크로 가서 Step 6부터 반복한다.

### Step 9: Review + Test (Phase 6)

모든 태스크가 리뷰 게이트를 통과한 뒤:

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase review-test --task "<작업>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" --skip-codex-review
```

`--skip-codex-review`는 필수다. Codex는 은퇴했다. 명세 준수는 Step 8에서 이미 봤다.

첫 실패 시 실패한 태스크의 Step 7을 실패 출력과 함께 **1회 자동 재시도**한다:

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase implement --task "<실패 태스크>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --implement-agent opencode --model "<선택모델>" --skip-verify \
  --is-retry --feedback "<테스트 실패 출력>"
```

두 번째 실패 시 보고하고 선택지를 제시한다:
1. 수동 수정 후 Phase 6 재실행
2. 머지 없이 현재 상태로 커밋
3. 중단

### Step 10: Complete (Phase 7)

Phase 6 성공 후에만 실행한다.

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase complete --task "<작업>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>"
```

### Step 11: Deploy (Phase 7b)

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase deploy --task "<작업>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --implement-agent opencode --model "<선택모델>"
```

사용자가 배포 명령을 지정했으면 `--deploy-command "<명령>"`을 넘긴다.
배포 설정이 감지되지 않으면 자동으로 건너뛴다.

### Step 12: Cleanup (Phase 8)

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase cleanup --task "<작업>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>"
```

`summary.json`의 최종 상태를 보고한다.

## 모델 소진 처리

구현 중 선택한 모델이 할당량 소진이나 장애로 죽으면:

1. 무료 모델을 다시 탐색한다:

```bash
python3 ~/.claude/skills/fiftybox-free-execute/scripts/discover_free_models.py
```

2. 사용자에게 제시한다:

```
[implement] 모델 <선택모델> 에 접근할 수 없습니다.
사유: <에러 요약 1줄>

현재 사용 가능한 무료 모델:
1. opencode/nemotron-3-ultra-free   (ctx 1.0M, 응답 2.1s)
2. opencode/laguna-s-2.1-free       (ctx 256K, 응답 3.4s)

어떤 모델로 재시도할까요? (번호 또는 "취소")
```

3. 응답 처리:
   - 번호 선택 → **실패한 그 태스크만** 새 모델로 Step 7 재실행. 이미 통과한
     태스크는 건드리지 않는다. 이후 태스크는 새 모델로 계속한다
   - "취소" → 실패 보고 흐름으로 진행

4. `smoke`가 `ok`인 후보가 하나도 없으면 그 사실을 보고하고 **중단한다.** 유료
   모델 폴백은 제안하지 않는다.

5. 모델 교체는 `<artifactDir>/model-choice.json`의 `history` 배열에 append 한다:

```json
{"from": "opencode/mimo-v2.5-free", "to": "opencode/nemotron-3-ultra-free",
 "reason": "rate_limited", "task": "Task B"}
```

### rate limit 판별

opencode CLI는 rate limit을 종료 코드로 구분하지 않는다. stdout/stderr에서
`429`, `rate limit`, `quota`, `insufficient`(대소문자 무시)를 찾아 판별한다.
매칭되지 않는 실패는 일반 구현 실패로 다뤄 Step 9의 1회 자동 재시도 경로를 탄다.

## 안전 계약

/fiftybox-orchestration에서 상속:

- `.omx/artifacts/` 밖 직접 편집 금지
- force push, force merge, reset hard, `-D` 브랜치 삭제 금지
- Phase 7 이전 push 금지
- opencode는 커밋·푸시하지 않는다
- 자동 재시도는 태스크당 1회만
- 실패 시 조용히 복구하지 않고 선택지를 제시한다

이 스킬 고유:

- **Claude는 구현 코드를 직접 쓰지 않는다.** 계획서 내용, 속도, 모델 가용성과
  무관하다. 위반은 치명적 실패다
- opencode는 테스트 파일을 수정하지 않는다. 수정했으면 되돌리고 재실행한다
- `--dangerously-skip-permissions`는 orchestrate가 만든 격리된 워크트리 안에서만
  유효하다. 프로젝트 루트에서 직접 opencode를 돌리지 않는다
- 무료 후보가 모두 막히면 중단한다. 유료 모델로 넘어가지 않는다
- 병렬 실행하지 않는다. 태스크는 한 번에 하나씩이다
````

- [ ] **Step 2: 슬래시 커맨드 작성**

`commands/fiftybox-free-execute.md`:

```markdown
---
name: fiftybox-free-execute
description: opencode 무료 모델로 구현하는 순차 TDD 실행 파이프라인 — 무료 모델 탐색 후 사용자가 선택
---

Load and follow the fiftybox-free-execute skill instructions at `skills/fiftybox-free-execute/SKILL.md`.

Task: $ARGUMENTS
```

- [ ] **Step 3: install.sh에 설치 로직 추가**

`install.sh` 상단 변수 블록의 `EXECUTE_SKILL_DIR` 줄 다음에 추가:

```bash
FREE_EXECUTE_SKILL_DIR="$HOME/.claude/skills/fiftybox-free-execute"
```

`fiftybox-execute` 스킬 설치 블록(`log "Installed Claude skill fiftybox-execute ..."`) 바로 다음에 추가:

```bash
# Install fiftybox-free-execute skill (opencode free-tier models)
mkdir -p "$FREE_EXECUTE_SKILL_DIR/scripts"
cp "$SCRIPT_DIR/skills/fiftybox-free-execute/SKILL.md" "$FREE_EXECUTE_SKILL_DIR/SKILL.md"
cp "$SCRIPT_DIR/skills/fiftybox-free-execute/scripts/"*.py "$FREE_EXECUTE_SKILL_DIR/scripts/"
log "Installed Claude skill fiftybox-free-execute → $FREE_EXECUTE_SKILL_DIR"
```

슬래시 커맨드 설치 블록의 `fiftybox-execute.md` 줄 다음에 추가:

```bash
cp "$SCRIPT_DIR/commands/fiftybox-free-execute.md" "$COMMANDS_DIR/fiftybox-free-execute.md"
log "Installed commands/fiftybox-free-execute.md → $COMMANDS_DIR/fiftybox-free-execute.md"
```

- [ ] **Step 4: 설치 테스트 추가**

`tests/test_install.sh`는 `INSTALL_ROOT="$(mktemp -d)"`를 만들고 `export HOME="$INSTALL_ROOT"`
한 뒤 `install.sh`를 돌린다. 경로 변수는 상단 셋업 블록에 모여 있으므로 거기에 한 줄
추가한다 (`LOCAL_EXECUTE_SKILL_DIR` 줄 다음):

```bash
FREE_EXECUTE_SKILL_DIR="$INSTALL_ROOT/.claude/skills/fiftybox-free-execute"
```

그리고 `fiftybox-execute.md` 검증 블록(73~75행 부근) 다음에 추가:

```bash
[[ -f "$COMMANDS_DIR/fiftybox-free-execute.md" ]] \
    && pass "fiftybox-free-execute.md command installed" \
    || fail "fiftybox-free-execute.md command not installed"

[[ -f "$FREE_EXECUTE_SKILL_DIR/SKILL.md" ]] \
    && pass "fiftybox-free-execute SKILL.md installed" \
    || fail "fiftybox-free-execute SKILL.md not installed"

[[ -f "$FREE_EXECUTE_SKILL_DIR/scripts/discover_free_models.py" ]] \
    && pass "discover_free_models.py installed" \
    || fail "discover_free_models.py not installed"
```

- [ ] **Step 5: 설치 테스트 실행**

Run: `bash tests/test_install.sh`
Expected: PASS — 신규 3건 포함 전부

- [ ] **Step 6: 커밋**

```bash
git add skills/fiftybox-free-execute/SKILL.md \
        commands/fiftybox-free-execute.md \
        install.sh tests/test_install.sh
git commit -m "feat(free-execute): add skill workflow, slash command, and install wiring"
```

---

### Task 8: 종단 수동 검증

CLI 플래그 조합은 목으로 검증되지 않는다. 실제로 한 사이클을 돌린다.

**Files:**
- Modify: 없음 (검증만). 결함이 나오면 해당 태스크로 돌아가 고친다.

**Interfaces:**
- Consumes: 전체 파이프라인
- Produces: 없음

- [ ] **Step 1: 전체 테스트 스위트 실행**

Run:
```bash
python3 -m pytest skills/fiftybox-free-execute/tests/ skills/fiftybox-orchestration/tests/ -v
bash tests/test_install.sh
```
Expected: 전부 PASS

- [ ] **Step 2: 설치**

Run: `./install.sh`
Expected: `fiftybox-free-execute` 스킬과 커맨드 설치 로그가 보인다

- [ ] **Step 3: 탐색을 실제로 돌린다**

Run: `python3 ~/.claude/skills/fiftybox-free-execute/scripts/discover_free_models.py`
Expected: `opencode/` 모델만 담긴 JSON. 최소 하나는 `"smoke": "ok"`.
`openai/`나 `zai/` 항목이 있으면 필터 결함이다 — 멈추고 Task 2로 돌아간다.

- [ ] **Step 4: 작은 실제 태스크로 한 사이클 돌린다**

임시 스크래치 리포지토리를 만든다:

```bash
mkdir -p /tmp/fiftybox-free-smoke && cd /tmp/fiftybox-free-smoke
git init -q && git commit -q --allow-empty -m "init"
```

`/fiftybox-free-execute "문자열을 받아 단어 수를 세는 word_count 함수를 src/wordcount.py에 추가"`
를 실행하고 Step 1→8을 끝까지 따라간다.

확인할 것:
- Step 2에서 모델 선택 프롬프트가 뜬다
- Step 7의 orchestrate 호출이 `--implement-agent opencode`를 포함하고,
  `unknown option` 류 에러 없이 진행된다
- opencode가 실제로 구현 파일을 만든다
- Step 8의 리뷰 게이트에서 테스트가 통과한다
- `<artifactDir>/model-choice.json`이 선택한 모델과 함께 존재한다

- [ ] **Step 5: 기존 스킬이 안 깨졌는지 확인 (회귀)**

`--implement-agent` 없이 orchestrate가 기존대로 도는지 본다:

```bash
cd /tmp/fiftybox-free-smoke
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase setup --task "regression check" --cwd "$(pwd)" --dry-run
```
Expected: 성공하고, 에이전트 설정 관련 신규 에러가 없다. 로그에 `pi`가 구현
에이전트로 남아 있어야 한다 — `opencode`로 바뀌어 있으면 오버라이드가 새고 있는
것이므로 Task 5로 돌아간다.

- [ ] **Step 6: 스크래치 정리 후 커밋할 것이 있으면 커밋**

```bash
rm -rf /tmp/fiftybox-free-smoke
```

수동 검증 중 고친 것이 있으면 해당 태스크의 커밋 관례를 따라 커밋한다.
없으면 이 태스크는 커밋 없이 끝난다.
