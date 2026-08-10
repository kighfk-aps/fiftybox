# fiftybox-cc-execute GPT advisory diff 리뷰 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** cc-execute Step 6 리뷰 게이트의 단일 태스크 스펙 준수 검사를 GPT advisory 리뷰(`cc_diff_review.py`)로 위임하고, Claude는 테스트 실행·통합 검사·최종 go/no-go만 유지한다.

**Architecture:** `skills/fiftybox-gpt-review/scripts/gpt_review.py`(문서 리뷰)를 형제 스크립트로 복제해 diff 리뷰 전용 contract와 입력을 갖는 `skills/fiftybox-cc-execute/scripts/cc_diff_review.py`를 만든다. 스크립트는 판단하지 않는다 — `codex exec -s read-only`를 호출하고, 판정을 파싱하고, 로그를 남기고, 한 줄 JSON을 낸다. 판정 해석과 최종 승인은 SKILL.md의 Claude 몫이다. `orchestrate.py`와 `install.sh`는 건드리지 않는다.

**Tech Stack:** Python 3 표준 라이브러리만(argparse/subprocess/json/pathlib/re), pytest, bash 구조 테스트

## Global Constraints

- 스펙: `docs/superpowers/specs/2026-08-10-fiftybox-cc-execute-gpt-review-design.md`
- 기본 모델 `gpt-5.6-terra`, 기본 effort `high`, 기본 timeout `900`초
- exit code는 `gpt_review.py`와 동일하게 고정: `2` 인자/경로, `3` codex 미설치·shim, `4` 모델 slug, `5` 타임아웃, `6` codex 실행 실패
- GPT 리뷰는 **advisory(non-blocking)**. 실패·`UNKNOWN`이면 해당 태스크만 Claude 폴백, 파이프라인은 멈추지 않는다
- GPT 리뷰어는 `-s read-only --ephemeral`이라 파일을 수정할 수도, 테스트를 실행할 수도 없다
- 새 스크립트는 `skills/fiftybox-cc-execute/scripts/`에, 테스트는 형제 디렉터리 `skills/fiftybox-cc-execute/tests/`에 둔다 (`fiftybox-gpt-review` 관례. `scripts/`에 두면 install.sh 글롭이 테스트까지 설치한다)
- 외부 의존성 추가 금지. `codex`를 실제로 호출하는 단위 테스트 금지
- Python 코드 주석·docstring은 영어, SKILL.md와 계획·스펙 문서는 한국어 (기존 리포지토리 관례)

---

## File Structure

| 파일 | 책임 |
|---|---|
| `skills/fiftybox-cc-execute/scripts/cc_diff_review.py` | 신규. diff 리뷰 contract 보유, codex 호출, 판정·findings 파싱, 로그 저장, JSON 출력 |
| `skills/fiftybox-cc-execute/tests/test_cc_diff_review.py` | 신규. 순수 함수와 인자 검증의 pytest 단위 테스트 |
| `skills/fiftybox-cc-execute/SKILL.md` | Step 6을 6a(GPT)/6b(Claude 게이트)로 재구조화, 모델 티어 `review` 행, 안전 계약 갱신 |
| `tests/test_cc_skill_doc.sh` | SKILL.md 구조 단정 갱신·추가 |

---

## Task 0: 기존 실패 테스트 정리 (선행)

작업 트리의 SKILL.md는 티어 모델을 `qwen/qwen3.7-flash`로 바꿨는데
`tests/test_cc_skill_doc.sh`는 아직 `deepseek/deepseek-v4-flash`를 단정한다. 지금
**1개 실패 상태**이고, 이 상태로 Task 3의 문서 변경을 얹으면 새 실패와 기존 실패가
섞여 구분이 안 된다.

**Files:**
- Modify: `tests/test_cc_skill_doc.sh:48`

**Interfaces:**
- Consumes: 없음
- Produces: green한 `tests/test_cc_skill_doc.sh` (Task 3이 여기에 단정을 얹는다)

- [ ] **Step 1: 현재 실패를 눈으로 확인**

Run: `bash tests/test_cc_skill_doc.sh`
Expected: `FAIL: SKILL.md names the simple-tier model`, 마지막 줄 `Results: 24 passed, 1 failed`

- [ ] **Step 2: 단정을 작업 트리의 실제 티어 모델에 맞춘다**

`tests/test_cc_skill_doc.sh:48`을 이렇게 바꾼다:

```bash
has "$SKILL" "qwen/qwen3.7-flash" "SKILL.md names the simple-tier model"
```

> SKILL.md 쪽을 deepseek으로 되돌리지 않는다. 티어 모델 변경은 사용자가 작업
> 트리에 이미 반영한 의도적 변경이고, 이 계획의 범위 밖이다. 테스트가 문서를
> 따라간다.

- [ ] **Step 3: 통과 확인**

Run: `bash tests/test_cc_skill_doc.sh`
Expected: `Results: 25 passed, 0 failed`

- [ ] **Step 4: 커밋**

```bash
git add tests/test_cc_skill_doc.sh
git commit -m "test: align cc-execute doc assertion with the qwen simple tier"
```

---

## Task 1: 순수 함수 — contract, 프롬프트 조립, 판정·findings 파싱

`codex`를 부르지 않는 부분을 먼저 전부 만든다. 이 태스크가 끝나면 스크립트는
import 가능하고 단위 테스트가 전부 돈다. CLI는 Task 2.

**Files:**
- Create: `skills/fiftybox-cc-execute/scripts/cc_diff_review.py`
- Test: `skills/fiftybox-cc-execute/tests/test_cc_diff_review.py`

**Interfaces:**
- Consumes: 없음 (`gpt_review.py`를 import 하지 않는다 — 설치본에서 두 스킬 디렉터리는 서로를 모른다. 복제가 의도된 결합 회피다)
- Produces:
  - `DIFF_REVIEW_CONTRACT: str`
  - `VERDICTS = ("APPROVED", "REVISE", "BLOCKED")`
  - `parse_verdict(text: str) -> str` — 판정 리터럴 또는 `"UNKNOWN"`
  - `count_findings(text: str) -> int`
  - `build_prompt(spec_name: str, spec_text: str, diff_name: str, diff_text: str, tests: list[tuple[str, str]], contexts: list[tuple[str, str]]) -> str`
  - `is_shim(path: Path) -> bool`, `find_codex() -> Path | None`
  - `codex_cache_path() -> Path`, `load_model_slugs(cache_path: Path) -> list[str] | None`
  - `diff_review_log_path(out_dir: Path, task_name: str, today: str) -> Path`
  - `build_codex_cmd(model: str, effort: str, output_file: Path) -> list[str]`
  - 상수 `EXIT_ARGS=2`, `EXIT_NO_CODEX=3`, `EXIT_BAD_MODEL=4`, `EXIT_TIMEOUT=5`, `EXIT_CODEX_FAILED=6`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

Create `skills/fiftybox-cc-execute/tests/test_cc_diff_review.py`:

```python
"""Tests for cc_diff_review."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import cc_diff_review as cdr  # noqa: E402


SHIM_BODY = """#!/usr/bin/env bash
# Codex shutout shim — installed 2026-07-27.
exit 1
"""


class TestParseVerdict:
    def test_reads_verdict_off_first_nonblank_line(self):
        assert cdr.parse_verdict("\n\nREVISE\n\n- [severity: major] x") == "REVISE"

    def test_accepts_trailing_punctuation(self):
        assert cdr.parse_verdict("APPROVED — no findings") == "APPROVED"

    def test_rejects_verdict_glued_to_more_word(self):
        assert cdr.parse_verdict("APPROVEDLY yours") == "UNKNOWN"

    def test_off_contract_first_line_is_unknown(self):
        assert cdr.parse_verdict("Here is my review:\nAPPROVED") == "UNKNOWN"

    def test_empty_text_is_unknown(self):
        assert cdr.parse_verdict("   \n\n") == "UNKNOWN"


class TestCountFindings:
    def test_counts_one_line_per_severity_header(self):
        text = (
            "REVISE\n"
            "- [severity: blocking] missing requirement\n"
            "  Evidence: spec line 3\n"
            "  Proposal: add it\n"
            "- [severity: minor] naming\n"
        )
        assert cdr.count_findings(text) == 2

    def test_indented_findings_still_count(self):
        assert cdr.count_findings("REVISE\n  - [severity: major] x\n") == 1

    def test_off_contract_response_counts_zero(self):
        assert cdr.count_findings("REVISE\nI think you should change things.") == 0

    def test_approved_with_no_findings_is_zero(self):
        assert cdr.count_findings("APPROVED\n") == 0


class TestBuildPrompt:
    def _prompt(self):
        return cdr.build_prompt(
            "spec-task-1.md", "SPEC BODY",
            "diff-task-1.patch", "DIFF BODY",
            [("test_thing.py", "TEST BODY")],
            [("design.md", "DESIGN BODY")],
        )

    def test_starts_with_the_contract(self):
        assert self._prompt().startswith(cdr.DIFF_REVIEW_CONTRACT)

    def test_inlines_every_input(self):
        prompt = self._prompt()
        for body in ("SPEC BODY", "DIFF BODY", "TEST BODY", "DESIGN BODY"):
            assert body in prompt

    def test_orders_spec_before_diff_before_tests_before_context(self):
        prompt = self._prompt()
        assert (prompt.index("SPEC BODY") < prompt.index("DIFF BODY")
                < prompt.index("TEST BODY") < prompt.index("DESIGN BODY"))

    def test_contract_forbids_claiming_test_results(self):
        assert "Never claim a test passed or failed" in cdr.DIFF_REVIEW_CONTRACT

    def test_contract_puts_cross_task_integration_out_of_scope(self):
        assert "cross-task integration" in cdr.DIFF_REVIEW_CONTRACT


class TestIsShim:
    def test_detects_shim_by_marker(self, tmp_path):
        p = tmp_path / "codex"
        p.write_text(SHIM_BODY, encoding="utf-8")
        assert cdr.is_shim(p) is True

    def test_real_script_without_marker_is_not_shim(self, tmp_path):
        p = tmp_path / "codex"
        p.write_text("#!/bin/sh\nexec real-codex \"$@\"\n", encoding="utf-8")
        assert cdr.is_shim(p) is False

    def test_binary_file_is_not_shim(self, tmp_path):
        p = tmp_path / "codex"
        p.write_bytes(b"\x7fELF\x02\x01\x01\x00\xff\xfe\xfd")
        assert cdr.is_shim(p) is False

    def test_missing_file_is_not_shim(self, tmp_path):
        assert cdr.is_shim(tmp_path / "nope") is False


class TestLoadModelSlugs:
    def test_reads_slugs(self, tmp_path):
        cache = tmp_path / "models_cache.json"
        cache.write_text('{"models": [{"slug": "gpt-5.6-terra"}]}', encoding="utf-8")
        assert cdr.load_model_slugs(cache) == ["gpt-5.6-terra"]

    def test_unreadable_cache_is_none(self, tmp_path):
        assert cdr.load_model_slugs(tmp_path / "nope.json") is None


class TestDiffReviewLogPath:
    def test_names_log_by_date_and_task(self, tmp_path):
        got = cdr.diff_review_log_path(tmp_path, "task-1", "2026-08-10")
        assert got == tmp_path / "2026-08-10-task-1-gpt-review.md"

    def test_never_overwrites_an_existing_log(self, tmp_path):
        (tmp_path / "2026-08-10-task-1-gpt-review.md").write_text("x", encoding="utf-8")
        got = cdr.diff_review_log_path(tmp_path, "task-1", "2026-08-10")
        assert got == tmp_path / "2026-08-10-task-1-gpt-review-2.md"


class TestBuildCodexCmd:
    def test_runs_read_only_and_reads_prompt_from_stdin(self, tmp_path):
        cmd = cdr.build_codex_cmd("gpt-5.6-terra", "high", tmp_path / "out.txt")
        assert cmd[:2] == ["codex", "exec"]
        assert "-s" in cmd and cmd[cmd.index("-s") + 1] == "read-only"
        assert cmd[-1] == "-"

    def test_passes_model_and_effort(self, tmp_path):
        cmd = cdr.build_codex_cmd("gpt-5.6-sol", "medium", tmp_path / "out.txt")
        assert cmd[cmd.index("--model") + 1] == "gpt-5.6-sol"
        assert "model_reasoning_effort=medium" in cmd
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python3 -m pytest skills/fiftybox-cc-execute/tests/test_cc_diff_review.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'cc_diff_review'`

- [ ] **Step 3: 스크립트의 순수 함수 부분을 쓴다**

Create `skills/fiftybox-cc-execute/scripts/cc_diff_review.py`:

```python
#!/usr/bin/env python3
"""Run a GPT advisory review of one task's code diff through the Codex CLI.

Sibling of fiftybox-gpt-review/scripts/gpt_review.py, which reviews design and
plan documents. The two are deliberately separate files: the review contract
and the inputs differ, and folding both into one script would mean a mode flag
threaded through every function.

The reviewer runs read-only and cannot execute anything, so it judges spec
conformance and test adequacy from inlined text only. Whether the suite is
green is verified by Claude before this script is ever called. This script
makes no judgement about the review's content — it invokes, parses, persists.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SHIM_MARKER = "Codex shutout shim"

EXIT_ARGS = 2
EXIT_NO_CODEX = 3
EXIT_BAD_MODEL = 4
EXIT_TIMEOUT = 5
EXIT_CODEX_FAILED = 6

DEFAULT_MODEL = "gpt-5.6-terra"
DEFAULT_EFFORT = "high"
DEFAULT_TIMEOUT = 900

VALID_EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")

REENABLE_HINT = (
    "Codex is disabled on this machine (shutout shim). Re-enable it with:\n"
    "  rm /opt/homebrew/bin/codex\n"
    "  ln -s /opt/homebrew/Caskroom/codex/<version>/bin/codex /opt/homebrew/bin/codex"
)

VERDICTS = ("APPROVED", "REVISE", "BLOCKED")

FINDING_RE = re.compile(r"^\s*-\s*\[severity:\s*(?:blocking|major|minor)\]",
                        re.IGNORECASE)

DIFF_REVIEW_CONTRACT = """You are reviewing a code diff against its task specification and acceptance tests.

Respond in exactly this shape:

FIRST LINE: one of APPROVED | REVISE | BLOCKED
THEN: a list of findings. Each finding is

- [severity: blocking|major|minor] one-line summary
  Evidence: which part of the diff or spec is wrong, and why
  Proposal: concretely what to change

Judge only these:
- does the diff satisfy every requirement in the task spec
- do the acceptance tests actually cover the spec, or do they pass
  vacuously (tautological assertions, mocked-away behavior, missing
  edge cases the spec names)
- scope creep: changes outside the task's files, unrelated edits
- missing requirements or half-implemented behavior

Out of scope — do not comment on: code style, naming, prose,
cross-task integration conflicts (a separate reviewer owns that),
or anything the spec deliberately defers. Do not modify any file.

You cannot run anything. Judge from the text you were given. Never claim a
test passed or failed — whether the suite is green has already been verified
by another reviewer."""


def is_shim(path: Path) -> bool:
    """True when `path` is the Mac-wide Codex shutout shim.

    Detection reads the file rather than executing it: both the shim and a
    genuinely broken codex exit 1, so execution cannot tell them apart.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return SHIM_MARKER in text


def find_codex() -> Path | None:
    """The codex executable on PATH, or None when it is not installed."""
    found = shutil.which("codex")
    return Path(found) if found else None


def codex_cache_path() -> Path:
    """<CODEX_HOME>/models_cache.json, or ~/.codex/models_cache.json by default."""
    home = os.environ.get("CODEX_HOME")
    base = Path(home) if home else Path(os.path.expanduser("~")) / ".codex"
    return base / "models_cache.json"


def load_model_slugs(cache_path: Path) -> list[str] | None:
    """Slugs from the Codex model cache, or None when it cannot be read.

    None means "cannot validate", not "no models": callers skip validation
    rather than block, so an offline or fresh install still works.
    """
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    models = raw.get("models")
    if not isinstance(models, list):
        return None
    return [m["slug"] for m in models
            if isinstance(m, dict) and isinstance(m.get("slug"), str)]


def build_prompt(spec_name: str, spec_text: str,
                 diff_name: str, diff_text: str,
                 tests: list[tuple[str, str]],
                 contexts: list[tuple[str, str]]) -> str:
    """Inline everything the reviewer may read, spec first.

    The spec leads because it is the yardstick: the reviewer should know what
    was asked before it reads what was done. The reviewer is read-only and is
    given no repository search task, so what it sees here is exactly what it
    reviews, which keeps a review reproducible.
    """
    parts = [
        DIFF_REVIEW_CONTRACT,
        f"\n\n## Task specification: {spec_name}\n\n{spec_text}",
        f"\n\n## Diff under review: {diff_name}\n\n```diff\n{diff_text}\n```",
    ]
    for name, text in tests:
        parts.append(f"\n\n## Acceptance test: {name}\n\n{text}")
    for name, text in contexts:
        parts.append(f"\n\n## Context: {name}\n\n{text}")
    return "".join(parts)


def parse_verdict(text: str) -> str:
    """Read the verdict off the first non-blank line; UNKNOWN when off-contract.

    A verdict literal only counts when it is followed by a token boundary:
    end of line, or a character that is neither alphanumeric nor an
    underscore. This keeps words like "APPROVEDLY" from being misread.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        for verdict in VERDICTS:
            if stripped.startswith(verdict):
                rest = stripped[len(verdict):]
                if not rest or not (rest[0].isalnum() or rest[0] == "_"):
                    return verdict
        return "UNKNOWN"
    return "UNKNOWN"


def count_findings(text: str) -> int:
    """Number of contract-shaped finding headers in the review.

    Off-contract prose counts zero. A zero count next to a REVISE verdict is
    the signal for Claude to read the raw log rather than trust the summary.
    """
    return sum(1 for line in text.splitlines() if FINDING_RE.match(line))


def diff_review_log_path(out_dir: Path, task_name: str, today: str) -> Path:
    """<out>/<date>-<task>-gpt-review[-N].md, never overwriting a log.

    The counter is what makes a re-review of the same task on the same day
    keep its predecessor, so callers must use the returned path rather than
    rebuilding it.
    """
    candidate = out_dir / f"{today}-{task_name}-gpt-review.md"
    counter = 2
    while candidate.exists():
        candidate = out_dir / f"{today}-{task_name}-gpt-review-{counter}.md"
        counter += 1
    return candidate


def build_codex_cmd(model: str, effort: str, output_file: Path) -> list[str]:
    """The `codex exec` command; the trailing "-" reads the prompt from stdin."""
    return [
        "codex", "exec",
        "--model", model,
        "-c", f"model_reasoning_effort={effort}",
        "-s", "read-only",
        "--ephemeral",
        "--skip-git-repo-check",
        "--ignore-user-config",
        "-o", str(output_file),
        "-",
    ]
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python3 -m pytest skills/fiftybox-cc-execute/tests/test_cc_diff_review.py -q`
Expected: PASS (25 tests)

- [ ] **Step 5: 커밋**

```bash
git add skills/fiftybox-cc-execute/scripts/cc_diff_review.py \
        skills/fiftybox-cc-execute/tests/test_cc_diff_review.py
git commit -m "feat(cc-execute): add diff review contract and parsers"
```

---

## Task 2: CLI — 인자 검증, codex 호출, 로그·JSON 출력

**Files:**
- Modify: `skills/fiftybox-cc-execute/scripts/cc_diff_review.py` (Task 1의 함수 뒤에 `read_pairs`와 `main` 추가)
- Test: `skills/fiftybox-cc-execute/tests/test_cc_diff_review.py` (클래스 추가)

**Interfaces:**
- Consumes: Task 1의 모든 함수와 exit 상수
- Produces:
  - `read_pairs(raw_paths: list[str]) -> list[tuple[str, str]] | None` — 읽기 실패 시 None
  - `main(argv: list[str] | None = None) -> int`
  - stdout JSON 키: `ok`, `verdict`, `reviewPath`, `diffPath`, `findingsCount`, `model`, `effort`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`skills/fiftybox-cc-execute/tests/test_cc_diff_review.py` 끝에 덧붙인다:

```python
@pytest.fixture
def inputs(tmp_path):
    """Three valid input files plus a fake codex on PATH."""
    (tmp_path / "diff.patch").write_text("+ added line\n", encoding="utf-8")
    (tmp_path / "spec.md").write_text("Task: do the thing\n", encoding="utf-8")
    (tmp_path / "test_thing.py").write_text("def test_thing(): pass\n", encoding="utf-8")
    return tmp_path


def base_argv(inputs, **over):
    argv = [
        "--diff", str(inputs / "diff.patch"),
        "--spec", str(inputs / "spec.md"),
        "--test", str(inputs / "test_thing.py"),
        "--task-name", "task-1",
        "--out", str(inputs / "reviews"),
    ]
    for flag, value in over.items():
        argv += ["--" + flag.replace("_", "-"), value]
    return argv


@pytest.fixture
def fake_codex(inputs, monkeypatch):
    """A real (non-shim) file on PATH so preflight passes."""
    bin_dir = inputs / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "codex"
    exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("CODEX_HOME", str(inputs / "codex-home"))
    return exe


class TestReadPairs:
    def test_returns_name_and_text_pairs(self, inputs):
        got = cdr.read_pairs([str(inputs / "spec.md")])
        assert got == [("spec.md", "Task: do the thing\n")]

    def test_missing_file_is_none(self, inputs):
        assert cdr.read_pairs([str(inputs / "nope.md")]) is None


class TestMainArgValidation:
    def test_missing_diff_file_exits_args(self, inputs, fake_codex, capsys):
        argv = base_argv(inputs)
        argv[argv.index("--diff") + 1] = str(inputs / "nope.patch")
        assert cdr.main(argv) == cdr.EXIT_ARGS
        assert "not found" in capsys.readouterr().err

    def test_missing_spec_file_exits_args(self, inputs, fake_codex):
        argv = base_argv(inputs)
        argv[argv.index("--spec") + 1] = str(inputs / "nope.md")
        assert cdr.main(argv) == cdr.EXIT_ARGS

    def test_missing_test_file_exits_args(self, inputs, fake_codex):
        argv = base_argv(inputs)
        argv[argv.index("--test") + 1] = str(inputs / "nope.py")
        assert cdr.main(argv) == cdr.EXIT_ARGS

    def test_invalid_effort_exits_args(self, inputs, fake_codex):
        assert cdr.main(base_argv(inputs, effort="turbo")) == cdr.EXIT_ARGS

    def test_nonpositive_timeout_exits_args(self, inputs, fake_codex):
        assert cdr.main(base_argv(inputs, timeout="0")) == cdr.EXIT_ARGS

    def test_shim_codex_exits_no_codex(self, inputs, monkeypatch):
        bin_dir = inputs / "shimbin"
        bin_dir.mkdir()
        exe = bin_dir / "codex"
        exe.write_text(SHIM_BODY, encoding="utf-8")
        exe.chmod(0o755)
        monkeypatch.setenv("PATH", str(bin_dir))
        assert cdr.main(base_argv(inputs)) == cdr.EXIT_NO_CODEX

    def test_absent_codex_exits_no_codex(self, inputs, monkeypatch):
        empty = inputs / "empty"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
        assert cdr.main(base_argv(inputs)) == cdr.EXIT_NO_CODEX

    def test_unknown_model_exits_bad_model(self, inputs, fake_codex, monkeypatch):
        home = inputs / "codex-home"
        home.mkdir()
        (home / "models_cache.json").write_text(
            '{"models": [{"slug": "gpt-5.6-terra"}]}', encoding="utf-8")
        assert cdr.main(base_argv(inputs, model="gpt-9")) == cdr.EXIT_BAD_MODEL


class TestMainSuccess:
    def _run(self, inputs, fake_codex, monkeypatch, review_text, returncode=0):
        def fake_run(cmd, **kwargs):
            out_file = Path(cmd[cmd.index("-o") + 1])
            out_file.write_text(review_text, encoding="utf-8")
            return subprocess.CompletedProcess(cmd, returncode, "", "")
        monkeypatch.setattr(cdr.subprocess, "run", fake_run)
        return cdr.main(base_argv(inputs))

    def test_writes_log_and_emits_json(self, inputs, fake_codex, monkeypatch, capsys):
        review = ("REVISE\n"
                  "- [severity: blocking] missing requirement\n"
                  "  Evidence: spec says X\n"
                  "  Proposal: add X\n")
        assert self._run(inputs, fake_codex, monkeypatch, review) == 0
        payload = json.loads(capsys.readouterr().out.strip())
        assert payload["ok"] is True
        assert payload["verdict"] == "REVISE"
        assert payload["findingsCount"] == 1
        assert payload["diffPath"] == str(inputs / "diff.patch")
        log = Path(payload["reviewPath"])
        assert log.exists()
        assert "task-1" in log.name
        assert "missing requirement" in log.read_text(encoding="utf-8")

    def test_off_contract_review_reports_unknown(self, inputs, fake_codex,
                                                 monkeypatch, capsys):
        assert self._run(inputs, fake_codex, monkeypatch, "Looks fine to me.\n") == 0
        payload = json.loads(capsys.readouterr().out.strip())
        assert payload["verdict"] == "UNKNOWN"
        assert payload["findingsCount"] == 0

    def test_codex_nonzero_exits_codex_failed(self, inputs, fake_codex, monkeypatch):
        assert self._run(inputs, fake_codex, monkeypatch, "APPROVED\n",
                         returncode=1) == cdr.EXIT_CODEX_FAILED

    def test_empty_review_exits_codex_failed(self, inputs, fake_codex, monkeypatch):
        assert self._run(inputs, fake_codex, monkeypatch, "   \n") == cdr.EXIT_CODEX_FAILED

    def test_timeout_exits_timeout(self, inputs, fake_codex, monkeypatch):
        def raise_timeout(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 900)
        monkeypatch.setattr(cdr.subprocess, "run", raise_timeout)
        assert cdr.main(base_argv(inputs)) == cdr.EXIT_TIMEOUT
```

테스트 파일 상단 import 블록에 `json`과 `subprocess`를 추가한다:

```python
import json
import subprocess
import sys
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python3 -m pytest skills/fiftybox-cc-execute/tests/test_cc_diff_review.py -q`
Expected: FAIL — `AttributeError: module 'cc_diff_review' has no attribute 'read_pairs'` (및 `main` 부재)

- [ ] **Step 3: `read_pairs`와 `main`을 구현한다**

`skills/fiftybox-cc-execute/scripts/cc_diff_review.py`의 `build_codex_cmd` 뒤에 덧붙인다:

```python
def read_pairs(raw_paths: list[str]) -> list[tuple[str, str]] | None:
    """(filename, text) for each path, or None after reporting the first failure."""
    pairs: list[tuple[str, str]] = []
    for raw in raw_paths:
        path = Path(raw)
        if not path.is_file():
            print(f"file not found: {path}", file=sys.stderr)
            return None
        try:
            pairs.append((path.name, path.read_text(encoding="utf-8", errors="replace")))
        except OSError as exc:
            print(f"could not read {path}: {exc}", file=sys.stderr)
            return None
    return pairs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a GPT advisory review of a task diff through the Codex CLI")
    parser.add_argument("--diff", required=True, help="git diff for this task")
    parser.add_argument("--spec", required=True, help="task specification file")
    parser.add_argument("--test", action="append", required=True,
                        help="acceptance test file (repeatable)")
    parser.add_argument("--context", action="append", default=[],
                        help="extra context file to inline (repeatable)")
    parser.add_argument("--task-name", required=True, dest="task_name",
                        help="task identifier used in the log filename")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"codex model slug (default: {DEFAULT_MODEL})")
    parser.add_argument("--effort", default=DEFAULT_EFFORT,
                        help=f"reasoning effort (default: {DEFAULT_EFFORT})")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"codex timeout in seconds (default: {DEFAULT_TIMEOUT})")
    parser.add_argument("--out", required=True, help="review log output directory")
    args = parser.parse_args(argv)

    codex = find_codex()
    if codex is None:
        print("codex not found on PATH. Install the Codex CLI first.",
              file=sys.stderr)
        return EXIT_NO_CODEX
    if is_shim(codex):
        print(REENABLE_HINT, file=sys.stderr)
        return EXIT_NO_CODEX

    if args.effort not in VALID_EFFORTS:
        print(f"invalid effort '{args.effort}'. "
              f"Valid efforts: {', '.join(VALID_EFFORTS)}", file=sys.stderr)
        return EXIT_ARGS
    if args.timeout <= 0:
        print(f"--timeout must be positive, got {args.timeout}", file=sys.stderr)
        return EXIT_ARGS

    diff_pair = read_pairs([args.diff])
    spec_pair = read_pairs([args.spec])
    tests = read_pairs(args.test)
    contexts = read_pairs(args.context)
    if diff_pair is None or spec_pair is None or tests is None or contexts is None:
        return EXIT_ARGS

    slugs = load_model_slugs(codex_cache_path())
    if slugs is None:
        print(f"warning: model cache unavailable — cannot validate "
              f"'{args.model}', continuing", file=sys.stderr)
    elif args.model not in slugs:
        print(f"unknown model '{args.model}'. "
              f"Available: {', '.join(slugs)}", file=sys.stderr)
        return EXIT_BAD_MODEL

    prompt = build_prompt(spec_pair[0][0], spec_pair[0][1],
                          diff_pair[0][0], diff_pair[0][1], tests, contexts)

    # `codex` is resolved through the (possibly restricted) PATH, but it may be
    # a script whose shebang needs env/bash from the standard system dirs, so
    # keep those reachable for the child process too.
    run_env = dict(os.environ)
    run_env["PATH"] = run_env.get("PATH", "") + os.pathsep + os.defpath

    with tempfile.TemporaryDirectory() as tmp:
        last_message = Path(tmp) / "review.txt"
        cmd = build_codex_cmd(args.model, args.effort, last_message)
        try:
            result = subprocess.run(cmd, input=prompt, capture_output=True,
                                    text=True, timeout=args.timeout, env=run_env)
        except subprocess.TimeoutExpired:
            print(f"codex review exceeded {args.timeout}s", file=sys.stderr)
            return EXIT_TIMEOUT
        review = (last_message.read_text(encoding="utf-8", errors="replace")
                  if last_message.exists() else "")

    if result.returncode != 0 or not review.strip():
        tail = (result.stderr or result.stdout or "")[-2000:]
        print(f"codex exited {result.returncode}: {tail}", file=sys.stderr)
        return EXIT_CODEX_FAILED

    verdict = parse_verdict(review)
    findings = count_findings(review)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()
    log_path = diff_review_log_path(out_dir, args.task_name, today)
    log_path.write_text(
        f"# GPT Diff Review — {args.task_name}\n\n"
        f"- diff: {args.diff}\n"
        f"- 명세: {args.spec}\n"
        f"- 테스트: {', '.join(args.test)}\n"
        f"- 모델: {args.model} (effort: {args.effort})\n"
        f"- 시각: {datetime.datetime.now().isoformat(timespec='seconds')}\n"
        f"- 판정: {verdict} (findings: {findings})\n\n"
        f"## 리뷰 원문\n\n{review.rstrip()}\n",
        encoding="utf-8",
    )

    print(json.dumps({
        "ok": True,
        "taskName": args.task_name,
        "diffPath": args.diff,
        "reviewPath": str(log_path),
        "model": args.model,
        "effort": args.effort,
        "verdict": verdict,
        "findingsCount": findings,
    }, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python3 -m pytest skills/fiftybox-cc-execute/tests/test_cc_diff_review.py -q`
Expected: PASS (전체 40여 개)

- [ ] **Step 5: 실물 도움말이 뜨는지 한 번 돌려본다**

Run: `python3 skills/fiftybox-cc-execute/scripts/cc_diff_review.py --help`
Expected: usage 출력, exit 0. (`codex`를 부르지 않는다)

- [ ] **Step 6: 커밋**

```bash
git add skills/fiftybox-cc-execute/scripts/cc_diff_review.py \
        skills/fiftybox-cc-execute/tests/test_cc_diff_review.py
git commit -m "feat(cc-execute): add cc_diff_review CLI with advisory exit codes"
```

---

## Task 3: SKILL.md Step 6 재구조화와 문서 테스트

**Files:**
- Modify: `skills/fiftybox-cc-execute/SKILL.md` (모델 티어 표 ~58행, Step 6 ~224-240행, Step 7 `--skip-codex-review` 설명 ~253행, 안전 계약 ~376행)
- Test: `tests/test_cc_skill_doc.sh`

**Interfaces:**
- Consumes: Task 2가 만든 CLI의 인자 이름과 exit code, JSON 키 `verdict`/`reviewPath`/`findingsCount`
- Produces: 없음 (문서가 최종 산출물)

- [ ] **Step 1: 실패하는 문서 테스트를 쓴다**

`tests/test_cc_skill_doc.sh`의 "Codex는 은퇴했다" 단정 블록 **뒤에** 덧붙인다:

```bash
# --- Step 6 GPT advisory diff 리뷰 (2026-08-10 설계) ----------------------
has "$SKILL" "cc_diff_review.py" "SKILL.md runs the diff review script"
has "$SKILL" "gpt-5.6-terra" "SKILL.md names the review-tier model"
has "$SKILL" "advisory" "SKILL.md marks the GPT review as advisory"
# 리뷰어는 read-only 샌드박스라 테스트를 돌릴 수 없다. 테스트 실행이 GPT로
# 넘어가면 "통과했다"는 근거 없는 주장을 신뢰하게 된다.
has "$SKILL" "테스트 실행은 Claude" "SKILL.md keeps test execution with Claude"
# GPT가 죽어도 파이프라인은 멈추지 않는다
has "$SKILL" "Claude 폴백" "SKILL.md documents the Claude fallback"
# 워크트리를 형제 태스크와 공유하므로 pathspec 없는 git diff는 스코프 오탐을 낳는다
has "$SKILL" "pathspec" "SKILL.md scopes the task diff with a pathspec"
# 재리뷰가 같은 날 돌면 로그에 -2가 붙는다. 경로를 조립하면 엉뚱한 파일을 읽는다
has "$SKILL" "reviewPath" "SKILL.md reads the log path from the JSON"
```

- [ ] **Step 2: 실패를 확인한다**

Run: `bash tests/test_cc_skill_doc.sh`
Expected: 새로 넣은 7개가 전부 FAIL, `Results: 25 passed, 7 failed`

- [ ] **Step 3: 모델 티어 표에 `review` 행을 넣는다**

`skills/fiftybox-cc-execute/SKILL.md`의 티어 표를 이렇게 바꾼다:

```markdown
| 대상 | 모델 |
|---|---|
| `implement` · simple | `qwen/qwen3.7-flash` |
| `implement` · complex | `zai-org/glm-5.2` |
| `deploy` | `qwen/qwen3.7-flash` |
| `review` (Step 6a advisory) | `gpt-5.6-terra` / effort high |
```

표 아래 `**--model <id> 오버라이드:**` 문단 끝에 한 줄 덧붙인다:

```markdown
`review` 티어는 CommandCode가 아니라 Codex CLI로 도는 별도 축이라 `--model`
오버라이드의 영향을 받지 않는다. 바꾸려면 Step 6a 명령의 `--model`을 직접 준다
(`gpt-5.6-sol`도 가능).
```

- [ ] **Step 4: Step 6을 6a/6b로 재구조화한다**

SKILL.md의 `### Step 6 — Claude 리뷰 게이트` 절 전체(현재 `1. 테스트 결과` ~
`Step 7로 간다`)를 아래로 교체한다:

````markdown
### Step 6 — 리뷰 게이트 (6a GPT advisory → 6b Claude 최종)

배치마다 리뷰 게이트를 통과해야 다음 배치로 간다. 검사는 세 항목이고, 담당이
나뉜다:

| 항목 | 담당 |
|---|---|
| ① 테스트 실행·통과 확인 | Claude |
| ② 스펙 준수 + 테스트 커버리지 적정성 | GPT (advisory) |
| ③ 통합 검사 (병렬 충돌·크로스 인터페이스) | Claude |
| findings 검증 + 최종 go/no-go | Claude |

**① 테스트 실행은 Claude가 한다.** GPT 리뷰어는 `-s read-only --ephemeral`
샌드박스에서 프롬프트에 인라인된 텍스트만 보므로 테스트를 실행할 수 없다.
Step 4에서 쓴 테스트를 전부 돌려 통과를 확인한다. `cmd`가 테스트 파일을
수정했다면 되돌리고 재실행한다.

**테스트가 실패한 태스크는 6a를 건너뛴다.** 깨진 diff에 리뷰 비용을 쓰지 않고
곧장 재구현으로 간다.

#### 6a — GPT advisory 리뷰 (자동)

배치가 green이면, 태스크마다 입력 파일 세 개를 만든다:

```bash
# 태스크가 소유한 파일만 pathspec으로 자른다
git -C "<worktree>" diff -- <태스크 소유 파일...> > "<artifactDir>/diff-task-N.patch"
```

그리고 `task-batches.md`의 해당 태스크 절을 발췌해
`<artifactDir>/spec-task-N.md`로 쓴다.

> **pathspec은 필수다.** 워크트리는 배치 내 형제 태스크와 공유된다. pathspec 없이
> `git diff`를 뜨면 형제의 변경이 섞여 GPT가 스코프 위반을 오탐한다.

태스크별 독립 프로세스로 detached 병렬 실행한다:

```bash
nohup python3 ~/.claude/skills/fiftybox-cc-execute/scripts/cc_diff_review.py \
  --diff "<artifactDir>/diff-task-N.patch" \
  --spec "<artifactDir>/spec-task-N.md" \
  --test "<테스트 파일>" \
  --context "<artifactDir>/design.md" \
  --task-name "task-N" --out "<artifactDir>/reviews" \
  --model gpt-5.6-terra --effort high \
  > "<artifactDir>/gpt-review-task-N.out" 2>&1 &
```

`.out` 로그를 폴링해 완료를 기다린다(Step 5 detached 패턴과 동일). 마지막 줄이
stdout JSON이다: `{ok, taskName, diffPath, reviewPath, model, effort, verdict, findingsCount}`.

exit code로 분기한다:

| exit | 의미 | 대응 |
|---|---|---|
| 0 | 성공 | `verdict`를 읽고 6b로 |
| 2 | 인자·경로 오류 | 스킬 버그. 보고하고 해당 태스크 Claude 폴백 |
| 3 | codex 미설치 또는 shim | stderr 안내를 전달하고 Claude 폴백 |
| 4 | 모델 슬러그 오류 | stderr의 사용 가능 목록을 제시하고 대체 모델로 재실행 |
| 5 | 타임아웃 | effort 하향 또는 더 가벼운 모델로 1회 재시도, 실패 시 Claude 폴백 |
| 6 | codex 실행 실패 | stderr를 전달하고 Claude 폴백 |

#### 6b — Claude 최종 게이트

각 태스크의 JSON `verdict`로 분기한다:

- **`APPROVED`** → ③ 통합 검사만 수행
- **`REVISE` / `BLOCKED`** → findings를 **검증**한다. GPT 판정을 맹신하지 않는다
  - 타당하면 → 수정 Agent(`cmd` 재구현)를 붙이고 테스트 재실행 → 6a+6b 재리뷰 1회
  - 타당하지 않으면(이미 만족한 요구, 오해, 범위 밖 지적) → 기각 사유를 JSON의
    `reviewPath`가 가리키는 로그 말미에 남기고 ③으로 간다
- **`UNKNOWN`** → contract를 벗어난 응답이다. 판정으로 취급하지 않고 Claude 폴백
- `findingsCount`가 0인데 판정이 `REVISE`/`BLOCKED`면 요약을 믿지 말고
  `reviewPath` 원문을 직접 읽는다

> 로그 경로를 직접 조립하지 않는다. 같은 날 재리뷰가 돌면 `-2`가 붙으므로 반드시
> JSON의 `reviewPath`를 쓴다.

**③ 통합 검사는 항상 Claude가 한다.** 병렬 태스크 간 충돌 편집(merge conflict,
중복 정의), 크로스 태스크 인터페이스 불일치(함수 시그니처, 공유 타입), 의도치 않은
결합을 본다. 이 항목은 GPT contract에서 명시적으로 out-of-scope다 — 단일 태스크
리뷰어는 형제 태스크를 보지 못한다.

#### Claude 폴백

**GPT 리뷰는 절약 기회이지 필수가 아니다.** 실패하거나 사용 불가면 해당 태스크는
Claude가 기존 방식(`git diff`를 명세와 직접 대조)으로 검사한다. 파이프라인은 GPT
때문에 멈추지 않는다.

폴백은 **태스크 국소**다. 한 태스크의 GPT 리뷰가 죽어도 형제 태스크는 GPT로 계속
간다.

GPT-driven 재구현이 재리뷰에서도 같은 blocking 지적을 받으면 사용자에게 선택지를
제시한다 — 기존 "두 번째 실패 시 사용자 보고" 규칙과 같다.

문제가 없으면 다음 배치로 넘어가 Step 4~6을 반복하거나, 배치가 전부 끝났으면
Step 7로 간다.
````

- [ ] **Step 5: Step 7의 Codex 은퇴 서술이 6a와 충돌하지 않게 한 줄 덧붙인다**

SKILL.md Step 7의 `--skip-codex-review` 설명 문단(“…불필요한 대응을 유발한다.”)
바로 뒤에 덧붙인다:

```markdown
Step 6a의 GPT diff 리뷰와는 별개다. 은퇴시킨 것은 orchestrate의 **설계·스펙**
advisory 리뷰이고, 6a는 cc-execute가 자체 스크립트로 도는 **구현 diff** 리뷰다.
```

- [ ] **Step 6: 안전 계약에 네 줄 추가**

SKILL.md 맨 아래 「안전 계약」 목록에 덧붙인다:

```markdown
- **GPT 리뷰(Step 6a)는 advisory(non-blocking)다.** 판정이 파이프라인을 멈추지 않는다
- **GPT 판정을 맹신하지 않는다.** Claude가 findings를 검증하고 최종 go/no-go를 낸다.
  테스트 실행과 통합 검사는 Claude가 유지한다
- GPT 리뷰어는 read-only 샌드박스라 파일을 수정할 수도, 테스트를 실행할 수도 없다
- **GPT 실패 시 자동 Claude 폴백.** GPT-driven 재구현도 `cmd`가 수행한다 — Claude가
  직접 고치지 않는다. 자동 재구현은 태스크당 1회
```

- [ ] **Step 7: 문서 테스트 통과 확인**

Run: `bash tests/test_cc_skill_doc.sh`
Expected: `Results: 32 passed, 0 failed`

- [ ] **Step 8: 리포지토리 전체 테스트를 돌린다**

Run: `for t in tests/*.sh; do echo "== $t"; bash "$t" || echo "FAILED: $t"; done`
Expected: 실패 없음. (`test_install.sh`가 install.sh를 검사한다 — 이 계획은
install.sh를 바꾸지 않으므로 그대로 통과해야 한다)

Run: `python3 -m pytest skills/fiftybox-cc-execute/tests skills/fiftybox-gpt-review/tests -q`
Expected: PASS

- [ ] **Step 9: 커밋**

```bash
git add skills/fiftybox-cc-execute/SKILL.md tests/test_cc_skill_doc.sh
git commit -m "feat(cc-execute): route single-task spec review to GPT advisory diff review"
```

---

## Task 4: 수동 E2E (사용자와 함께)

단위 테스트는 codex를 부르지 않는다. 실제 GPT가 계약대로 응답하는지는 한 번
사람이 확인해야 한다. **이 태스크는 사용자 동석이 필요하다 — 혼자 진행하지 않고
사용자에게 시점을 확인받는다.**

**Files:** 없음 (검증만)

- [ ] **Step 1: APPROVED 경로 — 실제 diff로 한 번 돌린다**

이 계획 자체의 Task 1 커밋을 재료로 쓴다:

```bash
mkdir -p /tmp/ccdr && \
git show --format= HEAD~1 -- skills/fiftybox-cc-execute/scripts/cc_diff_review.py \
  > /tmp/ccdr/diff-task-1.patch && \
printf 'Task: cc_diff_review.py에 diff 리뷰 contract와 순수 파서를 만든다.\n요구: parse_verdict는 토큰 경계를 지킨다. count_findings는 contract 형태의 severity 줄만 센다. build_prompt는 contract를 맨 앞에 두고 spec→diff→tests→context 순으로 조립한다.\n' \
  > /tmp/ccdr/spec-task-1.md && \
python3 skills/fiftybox-cc-execute/scripts/cc_diff_review.py \
  --diff /tmp/ccdr/diff-task-1.patch \
  --spec /tmp/ccdr/spec-task-1.md \
  --test skills/fiftybox-cc-execute/tests/test_cc_diff_review.py \
  --task-name task-1 --out /tmp/ccdr/reviews
```

Expected: exit 0, JSON 한 줄, `verdict`가 `UNKNOWN`이 아님. `reviewPath`의 로그를
열어 findings가 contract 형태(`- [severity: ...]`)인지 눈으로 확인한다.

- [ ] **Step 2: REVISE 경로 — 의도적 스펙 위반을 넣는다**

`/tmp/ccdr/spec-task-1.md`에 구현되지 않은 요구를 한 줄 더한다:

```bash
printf '요구: --spec 대신 --spec-text로 명세를 인라인 문자열로도 받는다.\n' \
  >> /tmp/ccdr/spec-task-1.md
```

같은 명령을 다시 돌린다.
Expected: `verdict`가 `REVISE` 또는 `BLOCKED`, `findingsCount >= 1`, 로그의 findings가
그 미구현 요구를 지목한다. 로그 파일명에 `-2`가 붙어 1회차 로그가 보존됐는지도
확인한다.

- [ ] **Step 3: 폴백 경로 — codex 없이 돌린다**

```bash
PATH=/usr/bin:/bin python3 skills/fiftybox-cc-execute/scripts/cc_diff_review.py \
  --diff /tmp/ccdr/diff-task-1.patch --spec /tmp/ccdr/spec-task-1.md \
  --test skills/fiftybox-cc-execute/tests/test_cc_diff_review.py \
  --task-name task-1 --out /tmp/ccdr/reviews; echo "exit=$?"
```

Expected: `exit=3`, stderr에 codex 미설치 안내. 이 경우 SKILL.md 6a 표대로 Claude
폴백이다.

- [ ] **Step 4: terra vs sol 비교 (선택)**

Step 2와 같은 입력에 `--model gpt-5.6-sol`을 줘 판정 품질을 비교한다. sol이
명백히 나으면 SKILL.md 티어 표의 기본값을 바꾸고 `tests/test_cc_skill_doc.sh`의
`gpt-5.6-terra` 단정도 함께 고친다. 차이가 애매하면 **terra를 유지한다** —
근거 없는 기본값 변경은 하지 않는다.

- [ ] **Step 5: 정리**

```bash
rm -rf /tmp/ccdr
```

---

## Self-Review

**스펙 커버리지**

| 스펙 절 | 담당 태스크 |
|---|---|
| `cc_diff_review.py` 신규 (contract, 인자, 호출, 출력, exit code) | Task 1, 2 |
| `DIFF_REVIEW_CONTRACT` 및 cross-task out-of-scope 고정 | Task 1 Step 3 (+ 테스트로 단정) |
| `--spec`이 텍스트가 아닌 파일 | Task 2 (`--spec` 경로 인자 + missing-file exit 2 테스트) |
| `findingsCount` 정의 (`count_findings`) | Task 1 |
| `reviewPath` 카운터·조립 금지 | Task 1 (`diff_review_log_path`), Task 3 (문서·단정) |
| Step 6 재구조화 6a/6b, ① Claude 유지 | Task 3 |
| pathspec으로 태스크 소유 파일만 diff | Task 3 (문서·단정) |
| 모델 티어 `review` 행 | Task 3 |
| 폴백 정책 (태스크 국소, non-blocking) | Task 3 |
| 안전 계약 4줄 | Task 3 Step 6 |
| `tests/` 위치 관례, install.sh 미변경 | Task 1 (경로), Task 3 Step 8 (`test_install.sh` 회귀 확인) |
| 검증 — 단위 테스트 | Task 1, 2 |
| 검증 — 수동 E2E, terra/sol 비교 | Task 4 |
| 선행 이슈 (deepseek/qwen 단정 불일치) | Task 0 |

**넣지 않은 것 (스펙의 YAGNI 준수):** `orchestrate.py` 신규 페이즈, GPT를 blocking
게이트로 승격, `gpt_review.py`에 diff 모드 추가, taste 학습 연동, GPT의 테스트 수정.

**타입 일관성:** `parse_verdict`/`count_findings`/`build_prompt`/`read_pairs`/
`diff_review_log_path`/`build_codex_cmd`의 이름과 시그니처가 Task 1 정의 →
Task 2 `main` 호출부 → Task 4 실행 예시에서 동일하다. JSON 키
(`verdict`, `reviewPath`, `findingsCount`, `diffPath`, `taskName`)도 Task 2 출력과
Task 3 문서에서 동일하다.
