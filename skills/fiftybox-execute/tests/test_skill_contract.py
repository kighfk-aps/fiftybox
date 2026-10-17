import re
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "SKILL.md"

REQUIRED = [
    "Use when a finished plan already exists and should be implemented and deployed by one subscription model. Also when the user invokes /fiftybox-execute.",
    "--skip-verification",
    "glm-5.3",
    "meta/muse-spark-1.2-contributor",
    "gpt-5.6-luna",
    "grok-4.6",
    "--model만 주면 pi / zai-coding / 그 모델이다.",
    "no_changes이면 complete와 deploy로 가지 않는다.",
    "task-batches.md",
    "implement.out",
    "구현 프로세스는 하나다",
    "세션은 구현 파일을 쓰지 않는다",
    "세션은 테스트 파일을 만들지 않는다",
    "diff를 읽고 판정하지 않는다",
    "요약하지 않는다",
    "다른 레인으로 넘어가지 않는다",
    "다른 모델을 해결책으로 제시하지 않는다",
    "이 스킬은 되돌리지 않는다",
    "되돌리기 어려운 변경도 따로 멈추지 않는다",
    "코드가 계획과 맞다는 문장은 넣지 않는다",
    "~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py",
    "--phase deploy",
    "미리 물어보고 멈추지 않는다",
    "incomplete_commit",
    "산문에 «parallel»이라고 적혀 있어도 무시한다.",
    "그냥 배포만",
]

FORBIDDEN = [
    "Claude가 실패하는 테스트 작성",
    "lane_priority",
    "diff_review.py",
    "implement-task-N.out",
    "--test-command true",
]


def test_skill_contains_the_spec_contract():
    text = SKILL.read_text(encoding="utf-8")
    missing = [item for item in REQUIRED if item not in text]
    assert missing == []


def test_skill_does_not_restore_the_old_loop():
    text = SKILL.read_text(encoding="utf-8")
    present = [item for item in FORBIDDEN if item in text]
    assert present == []


def test_review_test_invocation_skips_verification():
    text = SKILL.read_text(encoding="utf-8")
    blocks = re.findall(r"--phase review-test\b.{0,400}", text, re.S)
    assert blocks, "review-test command missing"
    assert all("--skip-verification" in block for block in blocks)


def test_commandcode_default_is_not_glm():
    text = SKILL.read_text(encoding="utf-8")
    assert "commandcode" in text
    window = text[text.index("commandcode"): text.index("commandcode") + 180]
    assert "meta/muse-spark-1.2-contributor" in window
    assert "glm-5.3" not in window
