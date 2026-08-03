# fiftybox-gpt-review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 설계·계획 마크다운 문서를 Codex의 GPT 모델에 보내 리뷰받고, 타당한 지적만 반영해 커밋하는 스킬 `fiftybox-gpt-review`를 만들고, 같은 리뷰어를 기존 orchestration/plans 파이프라인의 opt-in 리뷰어로도 연결한다.

**Architecture:** 판단이 필요 없는 부분(codex 실행 가능 여부 확인, 모델 슬러그 검증, codex 호출, 리뷰 로그 저장)은 전부 `scripts/gpt_review.py`가 결정적으로 처리하고 exit code로 실패를 구분한다. 판단이 필요한 부분(지적별 타당성 검증, 문서 수정, 커밋)은 SKILL.md 지시에 따라 Claude가 한다. 파이프라인 통합은 `orchestrate.py`에 codex 에이전트 템플릿과 `--design-review-agent` 플래그를 추가하는 최소 변경이며, 플래그를 안 주면 기존 동작이 그대로다.

**Tech Stack:** Python 3 (표준 라이브러리만), pytest, bash (install.sh / test_install.sh), Codex CLI 0.144.1

## Global Constraints

- 스펙: `docs/superpowers/specs/2026-08-03-fiftybox-gpt-review-design.md`
- 스크립트는 표준 라이브러리만 쓴다. 이 레포의 다른 헬퍼(`discover_free_models.py`)와 동일한 규약이다.
- 기본 모델 `gpt-5.6-terra`, 기본 effort `high`, 기본 타임아웃 900초, 기본 출력 디렉터리 `docs/reviews`.
- exit code 규약: `0` 성공 / `2` 인자 오류 / `3` codex 사용 불가 / `4` 알 수 없는 모델 슬러그 / `5` 타임아웃 / `6` codex 실행 실패.
- 리뷰 판정 리터럴은 정확히 `APPROVED` / `REVISE` / `BLOCKED`, 파싱 실패 시 `UNKNOWN`.
- shim 감지 마커 문자열은 정확히 `Codex shutout shim`.
- 모델 캐시 경로는 `~/.codex/models_cache.json` (`CODEX_HOME`이 설정돼 있으면 그쪽 우선).
- codex 호출은 항상 `-s read-only --ephemeral --skip-git-repo-check --ignore-user-config`를 포함한다.
- 기존 동작 불변: `--design-review-agent`를 주지 않으면 orchestration/plans의 Phase 4/5는 지금과 완전히 동일하게 동작한다.
- 파이썬 테스트는 `pytest`로 실행한다: `python3 -m pytest skills/<skill>/tests -q`.

## File Structure

**신규**

| 파일 | 책임 |
|---|---|
| `skills/fiftybox-gpt-review/SKILL.md` | Claude가 따르는 절차: 스크립트 실행 → 리뷰 판독 → 항목별 검증·반영 → 반영 결과 기록 → 커밋 |
| `skills/fiftybox-gpt-review/scripts/gpt_review.py` | codex 프리플라이트·모델 검증·호출·리뷰 로그 저장·JSON 요약 |
| `skills/fiftybox-gpt-review/tests/test_gpt_review.py` | 위 스크립트의 단위 테스트 (codex는 스텁 실행 파일로 대체) |
| `commands/fiftybox-gpt-review.md` | 슬래시 커맨드 |

**수정**

| 파일 | 변경 |
|---|---|
| `skills/fiftybox-orchestration/scripts/orchestrate.py` | `BUILTIN_AGENTS["codex"]` 추가, `--design-review-agent` 플래그, `run_design_review_agent()` 에이전트 선택, `reviewer_active` 조건 완화 |
| `skills/fiftybox-orchestration/tests/test_agent_config.py` | 에이전트 6개 → 7개 기대값 갱신, codex 템플릿 검증 추가 |
| `skills/fiftybox-orchestration/tests/test_orchestrate.py` | `reviewer_active` / 리뷰 에이전트 선택 회귀 테스트 추가 |
| `skills/fiftybox-orchestration/SKILL.md` | Phase 4 문구: opt-in 리뷰어에 codex/GPT 추가 |
| `skills/fiftybox-plans/SKILL.md` | Phase 5 문구: 동일 |
| `install.sh` | 새 스킬·슬래시 커맨드 설치 블록 |
| `tests/test_install.sh` | 새 스킬 설치 검증 |

---

### Task 1: Codex 차단 해제 (선행 1회)

이 작업 없이는 Task 3 이후의 수동 확인이 불가능하다. 코드 변경은 없다.

**Files:**
- 없음 (시스템 상태 변경)

**Interfaces:**
- Consumes: 없음
- Produces: PATH의 `codex`가 실제 바이너리를 가리키는 상태

- [ ] **Step 1: 현재 상태 확인**

```bash
head -3 /opt/homebrew/bin/codex
ls -l /opt/homebrew/Caskroom/codex/0.144.1/bin/codex
```

기대: 첫 명령이 `#!/usr/bin/env bash` + `# Codex shutout shim` 을 보여주고, 두 번째가 실제 바이너리 존재를 확인해준다.

- [ ] **Step 2: shim 제거하고 심볼릭 링크 복구**

```bash
rm /opt/homebrew/bin/codex
ln -s /opt/homebrew/Caskroom/codex/0.144.1/bin/codex /opt/homebrew/bin/codex
```

- [ ] **Step 3: 동작 확인**

```bash
codex --version
```

기대: `codex-cli 0.144.1` 출력, exit 0.

- [ ] **Step 4: 인증 확인**

```bash
codex exec --model gpt-5.4-mini -s read-only --ephemeral --skip-git-repo-check \
  --ignore-user-config "Reply with exactly: OK"
```

기대: `OK`에 해당하는 응답, exit 0. 인증 오류가 나면 여기서 멈추고 사용자에게 보고한다 — 이후 태스크는 전부 이 호출에 의존한다.

---

### Task 2: `gpt_review.py` 프리플라이트와 모델 검증

**Files:**
- Create: `skills/fiftybox-gpt-review/scripts/gpt_review.py`
- Test: `skills/fiftybox-gpt-review/tests/test_gpt_review.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `SHIM_MARKER: str`
  - `EXIT_ARGS = 2`, `EXIT_NO_CODEX = 3`, `EXIT_BAD_MODEL = 4`, `EXIT_TIMEOUT = 5`, `EXIT_CODEX_FAILED = 6`
  - `DEFAULT_MODEL = "gpt-5.6-terra"`, `DEFAULT_EFFORT = "high"`, `DEFAULT_TIMEOUT = 900`, `DEFAULT_OUT_DIR = "docs/reviews"`
  - `is_shim(path: Path) -> bool`
  - `find_codex() -> Path | None`
  - `codex_cache_path() -> Path`
  - `load_model_slugs(cache_path: Path) -> list[str] | None`

- [ ] **Step 1: 실패하는 테스트 작성**

`skills/fiftybox-gpt-review/tests/test_gpt_review.py`:

```python
"""Tests for gpt_review."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import gpt_review as gr  # noqa: E402


SHIM_BODY = """#!/usr/bin/env bash
# Codex shutout shim — installed 2026-07-27.
cat >&2 <<'MSG'
[codex] disabled
MSG
exit 1
"""


class TestIsShim:
    def test_detects_shim_by_marker(self, tmp_path):
        p = tmp_path / "codex"
        p.write_text(SHIM_BODY, encoding="utf-8")
        assert gr.is_shim(p) is True

    def test_real_script_without_marker_is_not_shim(self, tmp_path):
        p = tmp_path / "codex"
        p.write_text("#!/bin/sh\nexec real-codex \"$@\"\n", encoding="utf-8")
        assert gr.is_shim(p) is False

    def test_binary_file_is_not_shim(self, tmp_path):
        p = tmp_path / "codex"
        p.write_bytes(b"\x7fELF\x02\x01\x01\x00\xff\xfe\xfd")
        assert gr.is_shim(p) is False

    def test_missing_file_is_not_shim(self, tmp_path):
        assert gr.is_shim(tmp_path / "nope") is False


class TestFindCodex:
    def test_returns_path_when_on_path(self, tmp_path, monkeypatch):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        exe = bin_dir / "codex"
        exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        exe.chmod(0o755)
        monkeypatch.setenv("PATH", str(bin_dir))
        assert gr.find_codex() == exe

    def test_returns_none_when_absent(self, tmp_path, monkeypatch):
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
        assert gr.find_codex() is None


class TestLoadModelSlugs:
    def test_reads_slugs_from_cache(self, tmp_path):
        cache = tmp_path / "models_cache.json"
        cache.write_text(json.dumps({"models": [
            {"slug": "gpt-5.6-terra"}, {"slug": "gpt-5.4-mini"},
        ]}), encoding="utf-8")
        assert gr.load_model_slugs(cache) == ["gpt-5.6-terra", "gpt-5.4-mini"]

    def test_missing_cache_returns_none(self, tmp_path):
        assert gr.load_model_slugs(tmp_path / "absent.json") is None

    def test_malformed_cache_returns_none(self, tmp_path):
        cache = tmp_path / "models_cache.json"
        cache.write_text("{ not json", encoding="utf-8")
        assert gr.load_model_slugs(cache) is None

    def test_entries_without_slug_are_skipped(self, tmp_path):
        cache = tmp_path / "models_cache.json"
        cache.write_text(json.dumps({"models": [
            {"slug": "gpt-5.5"}, {"display_name": "no slug"}, "junk",
        ]}), encoding="utf-8")
        assert gr.load_model_slugs(cache) == ["gpt-5.5"]


class TestCodexCachePath:
    def test_uses_codex_home_when_set(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CODEX_HOME", str(tmp_path / "ch"))
        assert gr.codex_cache_path() == tmp_path / "ch" / "models_cache.json"

    def test_falls_back_to_home_dot_codex(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CODEX_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        assert gr.codex_cache_path() == Path(tmp_path) / ".codex" / "models_cache.json"
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python3 -m pytest skills/fiftybox-gpt-review/tests/test_gpt_review.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gpt_review'`

- [ ] **Step 3: 최소 구현 작성**

`skills/fiftybox-gpt-review/scripts/gpt_review.py`:

```python
#!/usr/bin/env python3
"""Run a GPT design/plan review through the Codex CLI.

Emits a JSON summary on stdout and writes the raw review to a Markdown log.
Makes no judgement about the review's content — that is Claude's job.
"""
from __future__ import annotations

import json
import os
import shutil
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
DEFAULT_OUT_DIR = "docs/reviews"

REENABLE_HINT = (
    "Codex is disabled on this machine (shutout shim). Re-enable it with:\n"
    "  rm /opt/homebrew/bin/codex\n"
    "  ln -s /opt/homebrew/Caskroom/codex/<version>/bin/codex /opt/homebrew/bin/codex"
)


def is_shim(path: Path) -> bool:
    """True when `path` is the Mac-wide Codex shutout shim.

    Detection reads the file rather than executing it: the shim and a genuinely
    broken codex both exit 1, so execution cannot tell them apart.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return SHIM_MARKER in text


def find_codex() -> Path | None:
    found = shutil.which("codex")
    return Path(found) if found else None


def codex_cache_path() -> Path:
    home = os.environ.get("CODEX_HOME")
    base = Path(home) if home else Path(os.path.expanduser("~")) / ".codex"
    return base / "models_cache.json"


def load_model_slugs(cache_path: Path) -> list[str] | None:
    """Slugs from the Codex model cache, or None when it is absent/unreadable.

    None means "cannot validate", not "no models" — callers skip validation
    rather than block, so an offline or fresh install still works.
    """
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    models = raw.get("models")
    if not isinstance(models, list):
        return None
    return [m["slug"] for m in models
            if isinstance(m, dict) and isinstance(m.get("slug"), str)]
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python3 -m pytest skills/fiftybox-gpt-review/tests/test_gpt_review.py -q`
Expected: PASS (14 passed)

- [ ] **Step 5: 커밋**

```bash
git add skills/fiftybox-gpt-review/scripts/gpt_review.py \
        skills/fiftybox-gpt-review/tests/test_gpt_review.py
git commit -m "feat(gpt-review): add codex preflight and model-slug validation"
```

---

### Task 3: `gpt_review.py` 리뷰 실행·로그 저장·CLI

**Files:**
- Modify: `skills/fiftybox-gpt-review/scripts/gpt_review.py`
- Modify: `skills/fiftybox-gpt-review/tests/test_gpt_review.py`

**Interfaces:**
- Consumes: Task 2의 `is_shim`, `find_codex`, `codex_cache_path`, `load_model_slugs`, exit code 상수, 기본값 상수
- Produces:
  - `REVIEW_CONTRACT: str`
  - `build_prompt(doc_name: str, doc_text: str, contexts: list[tuple[str, str]]) -> str`
  - `parse_verdict(text: str) -> str` — `APPROVED|REVISE|BLOCKED|UNKNOWN`
  - `review_log_path(out_dir: Path, doc_path: Path, today: str) -> Path`
  - `build_codex_cmd(model: str, effort: str, output_file: Path) -> list[str]`
  - `main(argv: list[str] | None = None) -> int`

- [ ] **Step 1: 실패하는 테스트 작성 (기존 파일에 이어 붙임)**

```python
class TestParseVerdict:
    def test_approved_first_line(self):
        assert gr.parse_verdict("APPROVED\n\n- nothing to fix") == "APPROVED"

    def test_revise_with_trailing_summary(self):
        assert gr.parse_verdict("REVISE: 세 군데 빠졌다\n...") == "REVISE"

    def test_blocked(self):
        assert gr.parse_verdict("BLOCKED — 설계 전제가 틀림") == "BLOCKED"

    def test_leading_blank_lines_are_skipped(self):
        assert gr.parse_verdict("\n\n  APPROVED\n") == "APPROVED"

    def test_off_contract_output_is_unknown(self):
        assert gr.parse_verdict("Sure! Here are my thoughts:") == "UNKNOWN"

    def test_empty_is_unknown(self):
        assert gr.parse_verdict("") == "UNKNOWN"

    def test_verdict_word_only_on_later_line_is_unknown(self):
        assert gr.parse_verdict("notes\nAPPROVED") == "UNKNOWN"


class TestReviewLogPath:
    def test_uses_date_and_doc_slug(self, tmp_path):
        p = gr.review_log_path(tmp_path, Path("docs/specs/my-design.md"), "2026-08-03")
        assert p == tmp_path / "2026-08-03-my-design-gpt-review.md"

    def test_second_run_same_day_gets_suffix(self, tmp_path):
        first = gr.review_log_path(tmp_path, Path("a/my-design.md"), "2026-08-03")
        first.parent.mkdir(parents=True, exist_ok=True)
        first.write_text("x", encoding="utf-8")
        second = gr.review_log_path(tmp_path, Path("a/my-design.md"), "2026-08-03")
        assert second == tmp_path / "2026-08-03-my-design-gpt-review-2.md"

    def test_third_run_same_day_gets_next_suffix(self, tmp_path):
        for name in ("2026-08-03-d-gpt-review.md", "2026-08-03-d-gpt-review-2.md"):
            (tmp_path / name).write_text("x", encoding="utf-8")
        p = gr.review_log_path(tmp_path, Path("a/d.md"), "2026-08-03")
        assert p == tmp_path / "2026-08-03-d-gpt-review-3.md"


class TestBuildCodexCmd:
    def test_includes_readonly_and_isolation_flags(self, tmp_path):
        cmd = gr.build_codex_cmd("gpt-5.6-terra", "high", tmp_path / "out.txt")
        assert cmd[:2] == ["codex", "exec"]
        assert "--model" in cmd and "gpt-5.6-terra" in cmd
        for flag in ("-s", "read-only", "--ephemeral",
                     "--skip-git-repo-check", "--ignore-user-config"):
            assert flag in cmd
        assert "-c" in cmd and "model_reasoning_effort=high" in cmd
        assert cmd[-1] == "-", "prompt must come from stdin"
        assert str(tmp_path / "out.txt") in cmd


class TestBuildPrompt:
    def test_inlines_document_and_contract(self):
        prompt = gr.build_prompt("design.md", "# Design\nbody here", [])
        assert "body here" in prompt
        assert "APPROVED" in prompt and "BLOCKED" in prompt
        assert "blocking" in prompt

    def test_inlines_context_files(self):
        prompt = gr.build_prompt("d.md", "doc", [("notes.md", "context body")])
        assert "context body" in prompt
        assert "notes.md" in prompt


# --- main() end-to-end with a stubbed codex -------------------------------

def _stub_codex(bin_dir: Path, *, reply: str = "APPROVED\n\nlooks fine",
                exit_code: int = 0, sleep: float = 0.0) -> Path:
    """Install a fake `codex` on PATH that writes `reply` to -o's target."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    exe = bin_dir / "codex"
    exe.write_text(
        "#!/usr/bin/env bash\n"
        f"sleep {sleep}\n"
        "out=\"\"\n"
        "while [[ $# -gt 0 ]]; do\n"
        "  if [[ $1 == -o ]]; then out=$2; shift; fi\n"
        "  shift\n"
        "done\n"
        "cat >/dev/null\n"
        f"printf '%s' {json.dumps(reply)!s} > \"$out\"\n"
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    exe.chmod(0o755)
    return exe


@pytest.fixture
def doc(tmp_path) -> Path:
    d = tmp_path / "docs" / "specs"
    d.mkdir(parents=True)
    p = d / "my-design.md"
    p.write_text("# My Design\n\nSome content.\n", encoding="utf-8")
    return p


@pytest.fixture
def cache(tmp_path, monkeypatch) -> Path:
    ch = tmp_path / "codex-home"
    ch.mkdir()
    (ch / "models_cache.json").write_text(json.dumps({"models": [
        {"slug": "gpt-5.6-terra"}, {"slug": "gpt-5.4-mini"},
    ]}), encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(ch))
    return ch / "models_cache.json"


class TestMain:
    def test_shim_exits_3(self, tmp_path, doc, cache, monkeypatch, capsys):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "codex").write_text(SHIM_BODY, encoding="utf-8")
        (bin_dir / "codex").chmod(0o755)
        monkeypatch.setenv("PATH", str(bin_dir))
        rc = gr.main(["--doc", str(doc), "--out", str(tmp_path / "reviews")])
        assert rc == gr.EXIT_NO_CODEX
        assert "rm /opt/homebrew/bin/codex" in capsys.readouterr().err

    def test_missing_codex_exits_3(self, tmp_path, doc, cache, monkeypatch):
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
        assert gr.main(["--doc", str(doc)]) == gr.EXIT_NO_CODEX

    def test_missing_doc_exits_2(self, tmp_path, cache, monkeypatch):
        _stub_codex(tmp_path / "bin")
        monkeypatch.setenv("PATH", str(tmp_path / "bin"))
        assert gr.main(["--doc", str(tmp_path / "nope.md")]) == gr.EXIT_ARGS

    def test_unknown_model_exits_4_and_lists_options(self, tmp_path, doc, cache,
                                                     monkeypatch, capsys):
        _stub_codex(tmp_path / "bin")
        monkeypatch.setenv("PATH", str(tmp_path / "bin"))
        rc = gr.main(["--doc", str(doc), "--model", "gpt-9-nope"])
        assert rc == gr.EXIT_BAD_MODEL
        assert "gpt-5.6-terra" in capsys.readouterr().err

    def test_absent_cache_skips_validation_and_succeeds(self, tmp_path, doc,
                                                        monkeypatch, capsys):
        monkeypatch.setenv("CODEX_HOME", str(tmp_path / "no-such-home"))
        _stub_codex(tmp_path / "bin")
        monkeypatch.setenv("PATH", str(tmp_path / "bin"))
        rc = gr.main(["--doc", str(doc), "--model", "gpt-9-unverifiable",
                      "--out", str(tmp_path / "reviews")])
        assert rc == 0
        assert "cannot validate" in capsys.readouterr().err.lower()

    def test_success_writes_log_and_json(self, tmp_path, doc, cache, monkeypatch, capsys):
        _stub_codex(tmp_path / "bin", reply="REVISE: 두 군데\n\n- [severity: major] x")
        monkeypatch.setenv("PATH", str(tmp_path / "bin"))
        out = tmp_path / "reviews"
        rc = gr.main(["--doc", str(doc), "--out", str(out)])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
        assert payload["verdict"] == "REVISE"
        assert payload["model"] == gr.DEFAULT_MODEL
        log = Path(payload["reviewPath"])
        assert log.exists()
        body = log.read_text(encoding="utf-8")
        assert "REVISE: 두 군데" in body
        assert gr.DEFAULT_MODEL in body
        assert str(doc) in body

    def test_codex_failure_exits_6(self, tmp_path, doc, cache, monkeypatch):
        _stub_codex(tmp_path / "bin", reply="", exit_code=1)
        monkeypatch.setenv("PATH", str(tmp_path / "bin"))
        assert gr.main(["--doc", str(doc), "--out", str(tmp_path / "r")]) == gr.EXIT_CODEX_FAILED

    def test_timeout_exits_5(self, tmp_path, doc, cache, monkeypatch):
        _stub_codex(tmp_path / "bin", sleep=2)
        monkeypatch.setenv("PATH", str(tmp_path / "bin"))
        rc = gr.main(["--doc", str(doc), "--out", str(tmp_path / "r"), "--timeout", "1"])
        assert rc == gr.EXIT_TIMEOUT
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python3 -m pytest skills/fiftybox-gpt-review/tests/test_gpt_review.py -q`
Expected: FAIL — `AttributeError: module 'gpt_review' has no attribute 'parse_verdict'`

- [ ] **Step 3: 구현 추가**

`gpt_review.py` 상단 import에 다음을 추가한다:

```python
import argparse
import datetime
import subprocess
import sys
import tempfile
```

그리고 Task 2의 함수들 아래에 이어 붙인다:

```python
VERDICTS = ("APPROVED", "REVISE", "BLOCKED")

REVIEW_CONTRACT = """You are reviewing a design or implementation-plan document.

Respond in exactly this shape:

FIRST LINE: one of APPROVED | REVISE | BLOCKED
THEN: a list of findings. Each finding is

- [severity: blocking|major|minor] one-line summary
  근거: which part of the document is wrong, and why
  제안: concretely what to change

Judge only these:
- missing steps, unverified assumptions
- missing failure/rollback paths
- test adequacy
- vague interface or module boundaries
- whether a different agent could execute this document unaided

Out of scope — do not comment on: code style, prose style, or features the
document deliberately does not cover. Do not modify any file."""


def build_prompt(doc_name: str, doc_text: str, contexts: list[tuple[str, str]]) -> str:
    """Inline everything the reviewer may read.

    The reviewer runs read-only and is given no repository search task: what it
    sees here is exactly what it reviews, which keeps a review reproducible.
    """
    parts = [REVIEW_CONTRACT, f"\n\n## Document under review: {doc_name}\n\n{doc_text}"]
    for name, text in contexts:
        parts.append(f"\n\n## Context: {name}\n\n{text}")
    return "".join(parts)


def parse_verdict(text: str) -> str:
    """Read the verdict off the first non-blank line; UNKNOWN when off-contract."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        for verdict in VERDICTS:
            if stripped.startswith(verdict):
                return verdict
        return "UNKNOWN"
    return "UNKNOWN"


def review_log_path(out_dir: Path, doc_path: Path, today: str) -> Path:
    """<out>/<date>-<doc-slug>-gpt-review[-N].md, never overwriting an existing log."""
    slug = doc_path.stem
    candidate = out_dir / f"{today}-{slug}-gpt-review.md"
    counter = 2
    while candidate.exists():
        candidate = out_dir / f"{today}-{slug}-gpt-review-{counter}.md"
        counter += 1
    return candidate


def build_codex_cmd(model: str, effort: str, output_file: Path) -> list[str]:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GPT review of a design/plan document")
    parser.add_argument("--doc", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", default=DEFAULT_EFFORT)
    parser.add_argument("--context", action="append", default=[])
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--out", default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)

    codex = find_codex()
    if codex is None:
        print("codex not found on PATH. Install the Codex CLI first.", file=sys.stderr)
        return EXIT_NO_CODEX
    if is_shim(codex):
        print(REENABLE_HINT, file=sys.stderr)
        return EXIT_NO_CODEX

    doc_path = Path(args.doc)
    if not doc_path.is_file():
        print(f"document not found: {doc_path}", file=sys.stderr)
        return EXIT_ARGS

    contexts: list[tuple[str, str]] = []
    for raw in args.context:
        ctx = Path(raw)
        if not ctx.is_file():
            print(f"context file not found: {ctx}", file=sys.stderr)
            return EXIT_ARGS
        contexts.append((ctx.name, ctx.read_text(encoding="utf-8", errors="replace")))

    slugs = load_model_slugs(codex_cache_path())
    if slugs is None:
        print("warning: model cache unavailable — cannot validate "
              f"'{args.model}', continuing", file=sys.stderr)
    elif args.model not in slugs:
        print(f"unknown model '{args.model}'. Available: {', '.join(slugs)}",
              file=sys.stderr)
        return EXIT_BAD_MODEL

    prompt = build_prompt(doc_path.name,
                          doc_path.read_text(encoding="utf-8", errors="replace"),
                          contexts)

    with tempfile.TemporaryDirectory() as tmp:
        last_message = Path(tmp) / "review.txt"
        cmd = build_codex_cmd(args.model, args.effort, last_message)
        try:
            result = subprocess.run(cmd, input=prompt, capture_output=True,
                                    text=True, timeout=args.timeout)
        except subprocess.TimeoutExpired:
            print(f"codex review exceeded {args.timeout}s", file=sys.stderr)
            return EXIT_TIMEOUT
        review = last_message.read_text(encoding="utf-8", errors="replace") \
            if last_message.exists() else ""

    if result.returncode != 0 or not review.strip():
        tail = (result.stderr or result.stdout or "")[-2000:]
        print(f"codex exited {result.returncode}: {tail}", file=sys.stderr)
        return EXIT_CODEX_FAILED

    verdict = parse_verdict(review)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()
    log_path = review_log_path(out_dir, doc_path, today)
    log_path.write_text(
        f"# GPT Review — {doc_path.name}\n\n"
        f"- 대상: {doc_path}\n"
        f"- 모델: {args.model} (effort: {args.effort})\n"
        f"- 시각: {datetime.datetime.now().isoformat(timespec='seconds')}\n"
        f"- 판정: {verdict}\n\n"
        f"## 리뷰 원문\n\n{review.rstrip()}\n",
        encoding="utf-8",
    )

    print(json.dumps({
        "ok": True,
        "docPath": str(doc_path),
        "reviewPath": str(log_path),
        "model": args.model,
        "effort": args.effort,
        "verdict": verdict,
    }, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python3 -m pytest skills/fiftybox-gpt-review/tests/test_gpt_review.py -q`
Expected: PASS (전체 통과)

- [ ] **Step 5: 실제 codex로 스모크 확인**

```bash
python3 skills/fiftybox-gpt-review/scripts/gpt_review.py \
  --doc docs/superpowers/specs/2026-08-03-fiftybox-gpt-review-design.md \
  --model gpt-5.4-mini --effort low \
  --out /tmp/gpt-review-smoke
```

Expected: exit 0, stdout에 JSON, `/tmp/gpt-review-smoke/`에 리뷰 로그 생성. 스텁이 아닌 실제 모델이 계약 형식을 지키는지 여기서 확인한다.

- [ ] **Step 6: 커밋**

```bash
git add skills/fiftybox-gpt-review/scripts/gpt_review.py \
        skills/fiftybox-gpt-review/tests/test_gpt_review.py
git commit -m "feat(gpt-review): run codex review, save log, emit JSON summary"
```

---

### Task 4: SKILL.md, 슬래시 커맨드, 설치

**Files:**
- Create: `skills/fiftybox-gpt-review/SKILL.md`
- Create: `commands/fiftybox-gpt-review.md`
- Modify: `install.sh`
- Modify: `tests/test_install.sh`

**Interfaces:**
- Consumes: Task 3의 `gpt_review.py` CLI(`--doc/--model/--effort/--context/--timeout/--out`)와 exit code 규약
- Produces: `/fiftybox-gpt-review <doc-path>` 슬래시 커맨드

- [ ] **Step 1: 설치 검증 테스트를 먼저 추가**

`tests/test_install.sh`의 `COMMANDS_DIR` 정의 아래에 변수를 추가한다:

```bash
GPT_REVIEW_SKILL_DIR="$INSTALL_ROOT/.claude/skills/fiftybox-gpt-review"
```

그리고 다른 `[[ -f ... ]]` 검증들 옆에 추가한다:

```bash
[[ -f "$GPT_REVIEW_SKILL_DIR/SKILL.md" ]] \
    && pass "fiftybox-gpt-review SKILL.md installed" \
    || fail "fiftybox-gpt-review SKILL.md not installed"

[[ -f "$GPT_REVIEW_SKILL_DIR/scripts/gpt_review.py" ]] \
    && pass "gpt_review.py installed" \
    || fail "gpt_review.py not installed"

[[ -f "$COMMANDS_DIR/fiftybox-gpt-review.md" ]] \
    && pass "fiftybox-gpt-review command installed" \
    || fail "fiftybox-gpt-review command not installed"
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `bash tests/test_install.sh`
Expected: 새로 추가한 세 줄이 `FAIL:`로 출력된다.

- [ ] **Step 3: 슬래시 커맨드 작성**

`commands/fiftybox-gpt-review.md`:

```markdown
---
name: fiftybox-gpt-review
description: 설계·계획 문서를 Codex의 GPT 모델에 리뷰받고 타당한 지적을 반영해 커밋
---

Load and follow the fiftybox-gpt-review skill instructions at `skills/fiftybox-gpt-review/SKILL.md`.

Document path (and options): $ARGUMENTS
```

- [ ] **Step 4: SKILL.md 작성**

`skills/fiftybox-gpt-review/SKILL.md`:

````markdown
---
name: fiftybox-gpt-review
description: 설계·계획 마크다운 문서를 Codex의 GPT 모델에 리뷰받고, 타당한 지적만 검증해 원본에 반영한 뒤 리뷰 로그와 함께 커밋한다. 사용자가 /fiftybox-gpt-review를 부르거나 spec·plan 문서를 GPT에게 리뷰받고 싶어할 때 사용한다.
---

# fiftybox-gpt-review

설계·계획 문서를 GPT에 리뷰받고 반영한다. 1회전으로 끝난다 — 재리뷰는 사용자가 다시 부른다.

## Invocation

```text
/fiftybox-gpt-review <문서경로> [--model <slug>] [--effort <level>] [--context <path>]
```

문서 경로가 없으면 대화 맥락에서 추측하지 말고 사용자에게 묻는다.

## Resolve The Helper Script

다음 순서로 존재하는 첫 경로를 쓴다:

1. `~/.claude/skills/fiftybox-gpt-review/scripts/gpt_review.py`
2. `./skills/fiftybox-gpt-review/scripts/gpt_review.py`

둘 다 없으면 스킬이 설치되지 않았다고 보고하고 멈춘다.

## Phase 1: Run The Review

```bash
python3 <gpt_review.py> --doc "<문서경로>" [--model <slug>] [--effort <level>] [--context <path>]
```

기본값은 `gpt-5.6-terra` / `high`다. 사용자가 모델을 지정하지 않으면 그대로 쓴다.

문서가 다른 산출물(intent, explore report 등)에 의존하면 `--context`로 넘긴다. 리뷰어는
read-only 샌드박스에서 돌고 저장소를 탐색하지 않으므로, 넘기지 않은 파일은 리뷰에 반영되지 않는다.

**exit code가 0이 아니면 문서를 절대 수정하지 않는다.** 메시지를 그대로 사용자에게 전달하고 멈춘다:

| exit | 대응 |
|---|---|
| 2 | 경로 오류 — 올바른 경로를 사용자에게 확인 |
| 3 | codex 사용 불가 — 출력된 재활성화 명령을 사용자에게 그대로 전달 |
| 4 | 모델 슬러그 오류 — 출력된 사용 가능 목록에서 고르게 함 |
| 5 | 타임아웃 — `--timeout`을 늘리거나 더 가벼운 모델을 제안 |
| 6 | codex 실행 실패 — 출력된 stderr를 그대로 전달 |

성공하면 stdout JSON에서 `reviewPath`와 `verdict`를 읽는다.

## Phase 2: Apply The Feedback

`verdict`가 `BLOCKED`이면 **문서를 고치지 않는다.** 무엇이 막혔는지 요약해 보고하고
사용자 판단을 기다린다. 설계 자체를 다시 해야 하는 신호이므로 자동 수정이 오히려 해롭다.

`APPROVED`이면 반영할 것이 없다. Phase 3으로 간다.

`REVISE`(또는 `UNKNOWN`이지만 내용이 유효한 지적일 때)이면 리뷰 로그를 읽고 항목별로 처리한다:

- 각 지적을 **검증한 뒤** 반영한다. 문서에 이미 있는 내용을 못 본 지적, 이 저장소의 실제
  코드·규약과 어긋나는 지적은 기각한다. 근거를 확인하려면 해당 파일을 직접 읽는다.
- `blocking` 항목을 기각할 때는 반드시 이유를 남긴다. `minor`는 문서 의도를 흐리면 기각해도 된다.
- 기존 구조·문체를 유지한 채 **최소 편집**한다. 문서를 통째로 다시 쓰지 않는다.

반영을 마치면 리뷰 로그 파일 끝에 다음을 덧붙인다:

```markdown
## 반영 결과

**반영**
- <항목 요약> — <문서의 어디를 어떻게 고쳤는지>

**기각**
- <항목 요약> — <기각 이유>
```

## Phase 3: Commit

문서와 리뷰 로그를 함께 한 커밋으로 남긴다:

```bash
git add "<문서경로>" "<reviewPath>"
git commit -m "docs: apply GPT review feedback to <doc-name>

Reviewed by <model> (<effort>) — verdict <VERDICT>
Applied: N items / Rejected: M items"
```

`APPROVED`라 수정이 없었으면 리뷰 로그만 스테이징하고 커밋 메시지 제목을
`docs: record GPT review of <doc-name>`으로 한다.

## Report

사용자에게 한 화면으로 보고한다: 판정, 반영한 항목 수와 요약, 기각한 항목과 이유,
리뷰 로그 경로, 커밋 해시.

## 파이프라인에서 쓰기

`/fiftybox-orchestration`이나 `/fiftybox-plans` 안에서 설계를 리뷰하려면 이 스킬 대신
그쪽 phase의 opt-in 플래그를 쓴다:

```bash
--design-review-agent codex --design-review-model gpt-5.6-terra
```
````

- [ ] **Step 5: install.sh에 설치 블록 추가**

`fiftybox-free-execute` 설치 블록 바로 아래에 추가한다:

```bash
# Install fiftybox-gpt-review skill (Codex/GPT design & plan review)
mkdir -p "$GPT_REVIEW_SKILL_DIR/scripts"
cp "$SCRIPT_DIR/skills/fiftybox-gpt-review/SKILL.md" "$GPT_REVIEW_SKILL_DIR/SKILL.md"
cp "$SCRIPT_DIR/skills/fiftybox-gpt-review/scripts/"*.py "$GPT_REVIEW_SKILL_DIR/scripts/"
log "Installed Claude skill fiftybox-gpt-review → $GPT_REVIEW_SKILL_DIR"
```

파일 상단의 경로 변수 블록(`FREE_EXECUTE_SKILL_DIR` 정의 아래)에 추가한다:

```bash
GPT_REVIEW_SKILL_DIR="$HOME/.claude/skills/fiftybox-gpt-review"
```

슬래시 커맨드 설치부(`fiftybox-free-execute.md` 복사 아래)에 추가한다:

```bash
cp "$SCRIPT_DIR/commands/fiftybox-gpt-review.md" "$COMMANDS_DIR/fiftybox-gpt-review.md"
log "Installed commands/fiftybox-gpt-review.md → $COMMANDS_DIR/fiftybox-gpt-review.md"
```

- [ ] **Step 6: 설치 테스트 통과 확인**

Run: `bash tests/test_install.sh`
Expected: 새 검증 세 줄이 모두 `PASS:`, 기존 FAIL 없음

- [ ] **Step 7: 커밋**

```bash
git add skills/fiftybox-gpt-review/SKILL.md commands/fiftybox-gpt-review.md \
        install.sh tests/test_install.sh
git commit -m "feat(gpt-review): add SKILL.md, slash command, and installer wiring"
```

---

### Task 5: orchestrate.py 파이프라인 통합

**Files:**
- Modify: `skills/fiftybox-orchestration/scripts/orchestrate.py` (`BUILTIN_AGENTS` 79-88행, `run_design_review_agent` 1663-1694행, `phase_verify_design` 1697-1755행, argparse 3174-3185행)
- Modify: `skills/fiftybox-orchestration/tests/test_agent_config.py`
- Modify: `skills/fiftybox-orchestration/tests/test_orchestrate.py`
- Modify: `skills/fiftybox-orchestration/SKILL.md` (Phase 4)
- Modify: `skills/fiftybox-plans/SKILL.md` (Phase 5)

**Interfaces:**
- Consumes: 기존 `build_agent_cmd(agent_name, config, *, prompt, task, model, provider, adapters_dir)`
- Produces:
  - `BUILTIN_AGENTS["codex"]`
  - argparse 플래그 `--design-review-agent` (기본값 `""`)
  - `run_design_review_agent(worktree, provider, model, prompt, timeout, *, logger=None, agent_override="")`

- [ ] **Step 1: 실패하는 테스트 작성**

`test_agent_config.py`의 `test_all_six_agents_present`를 다음으로 교체한다:

```python
    def test_all_seven_agents_present(self):
        expected = {"pi", "opencode", "aider", "gemini", "qwen", "cursor", "codex"}
        assert set(orc.BUILTIN_AGENTS.keys()) == expected

    def test_codex_cmd_is_read_only_and_isolated(self):
        codex_cmd = orc.BUILTIN_AGENTS["codex"]["cmd"]
        assert codex_cmd[:2] == ["codex", "exec"]
        assert "{model}" in codex_cmd
        assert "{provider}" not in codex_cmd, "codex has no provider concept"
        for flag in ("-s", "read-only", "--ephemeral",
                     "--skip-git-repo-check", "--ignore-user-config"):
            assert flag in codex_cmd

    def test_codex_cmd_renders_without_provider(self, tmp_path):
        cmd = orc.build_agent_cmd(
            "codex", {"agents": dict(orc.BUILTIN_AGENTS)},
            prompt="P", task="T", model="gpt-5.6-terra",
            provider="", adapters_dir=tmp_path,
        )
        assert "gpt-5.6-terra" in cmd
        assert cmd[-1] == "P\nT"
```

`test_orchestrate.py` 끝에 다음 클래스를 추가한다:

```python
class TestDesignReviewerSelection:
    """--design-review-agent selects the reviewer without touching explore_agent."""

    def _args(self, **kw):
        import argparse as _argparse
        base = {"design_review_provider": "", "design_review_model": "",
                "design_review_agent": ""}
        base.update(kw)
        return _argparse.Namespace(**base)

    def test_inactive_without_model(self):
        args = self._args(design_review_agent="codex")
        assert orchestrate.resolve_reviewer(args) is None

    def test_inactive_when_nothing_passed(self):
        assert orchestrate.resolve_reviewer(self._args()) is None

    def test_glm_provider_and_model_still_active(self):
        args = self._args(design_review_provider="zai-coding",
                          design_review_model="glm-5.2")
        reviewer = orchestrate.resolve_reviewer(args)
        assert reviewer == ("", "zai-coding", "glm-5.2")

    def test_codex_agent_and_model_active_without_provider(self):
        args = self._args(design_review_agent="codex",
                          design_review_model="gpt-5.6-terra")
        reviewer = orchestrate.resolve_reviewer(args)
        assert reviewer == ("codex", "", "gpt-5.6-terra")


class TestRunDesignReviewAgentOverride:
    def test_agent_override_replaces_explore_agent(self, monkeypatch, tmp_path):
        captured = {}

        def fake_run(cmd, cwd, timeout=None):
            captured["cmd"] = cmd
            import subprocess as _sp
            return _sp.CompletedProcess(cmd, 0, "APPROVED: ok", "")

        monkeypatch.setattr(orchestrate, "run", fake_run)
        monkeypatch.setattr(orchestrate, "load_agent_config",
                            lambda _d: {"explore_agent": "pi",
                                        "agents": dict(orchestrate.BUILTIN_AGENTS)})
        orchestrate.run_design_review_agent(
            tmp_path, "", "gpt-5.6-terra", "PROMPT", 60, agent_override="codex")
        assert captured["cmd"][0] == "codex"

    def test_no_override_keeps_explore_agent(self, monkeypatch, tmp_path):
        captured = {}

        def fake_run(cmd, cwd, timeout=None):
            captured["cmd"] = cmd
            import subprocess as _sp
            return _sp.CompletedProcess(cmd, 0, "APPROVED: ok", "")

        monkeypatch.setattr(orchestrate, "run", fake_run)
        monkeypatch.setattr(orchestrate, "load_agent_config",
                            lambda _d: {"explore_agent": "pi",
                                        "agents": dict(orchestrate.BUILTIN_AGENTS)})
        orchestrate.run_design_review_agent(
            tmp_path, "zai-coding", "glm-5.2", "PROMPT", 60)
        assert captured["cmd"][0] == "pi"
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python3 -m pytest skills/fiftybox-orchestration/tests -q`
Expected: FAIL — `KeyError: 'codex'`, `AttributeError: module 'orchestrate' has no attribute 'resolve_reviewer'`

- [ ] **Step 3: `BUILTIN_AGENTS`에 codex 추가**

`orchestrate.py` 87행 `cursor` 항목 아래에 추가한다:

```python
    "codex": {"cmd": ["codex", "exec", "--model", "{model}",
                      "-s", "read-only", "--ephemeral", "--skip-git-repo-check",
                      "--ignore-user-config", "{prompt}\n{task}"]},
```

- [ ] **Step 4: `resolve_reviewer` 추가**

`run_design_review_agent` 정의 바로 위에 추가한다:

```python
def resolve_reviewer(args: argparse.Namespace) -> tuple[str, str, str] | None:
    """(agent, provider, model) for the opt-in design review, or None when skipped.

    Two shapes are valid: a provider+model pair (GLM through the explore agent
    template) or an agent+model pair (codex, which has no provider concept).
    A model alone is not enough — that is how the default skip stays the default.
    """
    agent = (getattr(args, "design_review_agent", "") or "").strip()
    provider = (args.design_review_provider or "").strip()
    model = (args.design_review_model or "").strip()
    if not model:
        return None
    if not agent and not provider:
        return None
    return (agent, provider, model)
```

- [ ] **Step 5: `run_design_review_agent`에 override 인자 추가**

1679-1680행을 다음으로 바꾼다:

```python
    agent_config = load_agent_config(SKILL_DIR)
    agent_name = agent_override.strip() or agent_config.get("explore_agent", "pi")
```

시그니처의 키워드 인자에 `agent_override: str = ""`를 추가하고, docstring의
"This is the opt-in GLM replacement..." 문단을 다음으로 갱신한다:

```python
    """Run a read-only design review through the configured agent.

    Two opt-in reviewers exist: GLM through the explore agent template
    (`--design-review-provider zai-coding --design-review-model glm-5.2`) and
    Codex/GPT (`--design-review-agent codex --design-review-model gpt-5.6-terra`).
    `agent_override` selects the latter without changing explore_agent, which
    other phases still use. Read-only by contract: the task instructs the agent
    not to touch files, and the codex template also enforces it with a sandbox.
    """
```

- [ ] **Step 6: `phase_verify_design`을 `resolve_reviewer` 기반으로 변경**

1704-1706행을 다음으로 바꾼다:

```python
    reviewer = resolve_reviewer(args)
    review_agent, review_provider, review_model = reviewer or ("", "", "")
    reviewer_active = reviewer is not None
    reviewer_label = f"{review_agent or review_provider}/{review_model}"
```

1709행의 f-string을 `f"design review via {reviewer_label}"`로,
1711행의 skip 메시지를 `"design review skipped (no reviewer configured)"`로 바꾼다.

1741-1746행의 skip 안내문을 다음으로 바꾼다:

```python
        note = (
            "SKIPPED: design review not requested. Pass "
            "--design-review-provider/--design-review-model (e.g. zai-coding / glm-5.2) "
            "or --design-review-agent codex --design-review-model gpt-5.6-terra "
            "to review a very complex architecture."
        )
```

1771-1774행의 호출을 다음으로 바꾼다:

```python
        review_result = run_design_review_agent(
            worktree, review_provider, review_model, review_prompt,
            args.agent_timeout, logger=logger, agent_override=review_agent,
        )
```

1776행과 1792행의 `{review_provider}/{review_model}`를 `{reviewer_label}`로 바꾼다.

- [ ] **Step 7: argparse 플래그 추가**

`--design-review-model` 정의 아래에 추가한다:

```python
    parser.add_argument(
        "--design-review-agent",
        default="",
        help="Agent for the optional Phase 4 design review when the reviewer has no "
        "provider (e.g. codex). Requires --design-review-model. Empty (default) uses "
        "the configured explore agent with --design-review-provider.",
    )
```

- [ ] **Step 8: 테스트 통과 확인**

Run: `python3 -m pytest skills/fiftybox-orchestration/tests skills/fiftybox-plans/tests -q`
Expected: PASS (기존 테스트 포함 전부)

- [ ] **Step 9: 두 SKILL.md 문구 갱신**

`skills/fiftybox-orchestration/SKILL.md` Phase 4(210행 부근)의 GLM opt-in 설명 뒤에 추가한다:

```markdown
Codex/GPT is the other opt-in reviewer. It needs no provider — pass the agent instead:

```bash
python3 <orchestrate.py> --phase verify-design \
  --design-review-agent codex --design-review-model gpt-5.6-terra ...
```

Codex must be enabled on this machine (`codex --version` must succeed). Either reviewer is
**advisory**: the verdict is recorded in `design-review.md` and surfaced, but does not stop
the pipeline unless you pass `--strict-review`.
```

`skills/fiftybox-plans/SKILL.md` Phase 5(185행 부근)의 GLM 블록 뒤에 같은 내용을 추가하되,
명령은 그 파일의 `--phase verify-design` 호출 형식에 맞춘다.

`skills/fiftybox-orchestration/SKILL.md`의 "GLM Design Review Failures (opt-in only)"
섹션 제목을 "Design Review Failures (opt-in only)"로 바꾸고, 본문에 codex 리뷰어도 같은
advisory 규칙을 따른다는 한 문장을 추가한다. 단, 기본이 skip이라는 서술은 유지한다.

- [ ] **Step 10: 전체 테스트 재확인**

Run: `python3 -m pytest skills -q && bash tests/test_install.sh`
Expected: pytest 전부 PASS, install 테스트 FAIL 0

- [ ] **Step 11: 커밋**

```bash
git add skills/fiftybox-orchestration/scripts/orchestrate.py \
        skills/fiftybox-orchestration/tests/test_agent_config.py \
        skills/fiftybox-orchestration/tests/test_orchestrate.py \
        skills/fiftybox-orchestration/SKILL.md \
        skills/fiftybox-plans/SKILL.md
git commit -m "feat(orchestrate): add codex/GPT as an opt-in design reviewer"
```

---

### Task 6: 실제 문서로 종단 검증

**Files:**
- 없음 (검증 전용, 산출물은 리뷰 로그 커밋)

**Interfaces:**
- Consumes: Task 4의 `/fiftybox-gpt-review`, Task 5의 `--design-review-agent`
- Produces: 없음

- [ ] **Step 1: 설치본으로 스킬 실행**

```bash
bash install.sh
python3 ~/.claude/skills/fiftybox-gpt-review/scripts/gpt_review.py \
  --doc docs/superpowers/plans/2026-08-03-fiftybox-gpt-review.md \
  --out docs/reviews
```

Expected: exit 0, `docs/reviews/`에 로그 생성, JSON에 `verdict` 포함.

- [ ] **Step 2: 리뷰 내용이 계약 형식을 지켰는지 확인**

생성된 로그를 읽고 첫 줄 판정과 `[severity: ...]` 항목 형식이 지켜졌는지 본다.
형식이 무너졌으면 `REVIEW_CONTRACT` 문구를 조정하고 Task 3의 테스트를 다시 돌린다.

- [ ] **Step 3: 파이프라인 경로 스모크**

```bash
python3 skills/fiftybox-orchestration/scripts/orchestrate.py --help | grep design-review
```

Expected: `--design-review-agent`가 목록에 보인다.

- [ ] **Step 4: 리뷰 로그 커밋**

```bash
git add docs/reviews
git commit -m "docs: record end-to-end GPT review of the gpt-review plan"
```

---

## Self-Review 결과

- 스펙 커버리지: 컴포넌트 1(Task 2·3), 컴포넌트 2 리뷰 계약(Task 3의 `REVIEW_CONTRACT`),
  컴포넌트 3 반영 규칙·커밋(Task 4의 SKILL.md), 컴포넌트 4 파이프라인 통합(Task 5),
  테스트(Task 2·3·4·5), 설치·배포(Task 4), 선행 작업(Task 1) 모두 대응됨.
- 스펙에는 없었지만 필요해서 추가한 것: `test_agent_config.py`의 "에이전트 6개" 기대값이
  codex 추가로 깨지므로 Task 5에서 함께 갱신한다. 이걸 빠뜨리면 통합이 기존 테스트를 깬다.
- 이름 일관성: `resolve_reviewer`, `agent_override`, `review_log_path`, `parse_verdict`,
  `build_codex_cmd`, `build_prompt`는 정의된 태스크와 사용하는 태스크에서 동일하다.
