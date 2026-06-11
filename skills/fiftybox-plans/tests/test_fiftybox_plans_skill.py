"""Verify skills/fiftybox-plans/SKILL.md has correct structure and content."""
from pathlib import Path

SKILL_PATH = Path(__file__).parent.parent / "SKILL.md"


def test_skill_file_exists():
    assert SKILL_PATH.exists(), f"SKILL.md not found at {SKILL_PATH}"


def test_frontmatter_name():
    content = SKILL_PATH.read_text()
    assert "name: fiftybox-plans" in content


def test_frontmatter_description_present():
    content = SKILL_PATH.read_text()
    lines = content.splitlines()
    assert any(l.startswith("description:") for l in lines[:10])


def test_all_phases_present():
    content = SKILL_PATH.read_text()
    for phase in ["Phase 1", "Phase 2", "Phase 3", "Phase 4", "Phase 5", "Phase 6", "Phase 7", "Phase 8"]:
        assert phase in content, f"{phase} section missing from SKILL.md"


def test_explore_uses_ollama():
    content = SKILL_PATH.read_text()
    assert "--provider ollama" in content


def test_explore_uses_gemma4():
    content = SKILL_PATH.read_text()
    assert "gemma4" in content


def test_codex_uses_gpt55_high():
    content = SKILL_PATH.read_text()
    assert "gpt-5.5-high" in content


def test_resume_artifacts_present():
    content = SKILL_PATH.read_text()
    for artifact in ["intent-summary.md", "design.md", "route-decision.md", "codex-design-review.md"]:
        assert artifact in content, f"Resume artifact '{artifact}' not mentioned in SKILL.md"


def test_handoff_to_orchestrate_resume():
    content = SKILL_PATH.read_text()
    assert "--resume" in content


def test_opus_sub_agent_for_design():
    content = SKILL_PATH.read_text()
    assert "opus" in content.lower()


def test_failure_report_format_present():
    content = SKILL_PATH.read_text()
    assert "Failure" in content or "실패" in content


def test_user_gate_with_approval_options():
    content = SKILL_PATH.read_text()
    assert "승인" in content or "approval" in content.lower()
