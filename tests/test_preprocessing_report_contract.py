"""The preprocessing contract: score first, one table, numbered selection.

The user-facing flow is: infer content type and demand, score every source,
print one table with dimensions + basis + recommended plan, then wait for the
user to reply with numbers. These tests keep a later edit from reintroducing the
old questionnaire-before-scoring flow.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SKILL = (ROOT / "SKILL.md").read_text(encoding="utf-8")
TRIAGE_DOC = (ROOT / "docs" / "triage.md").read_text(encoding="utf-8")


def _between(start: str, end: str) -> str:
    assert start in SKILL, f"missing section marker: {start}"
    assert end in SKILL, f"missing section marker: {end}"
    return SKILL[SKILL.index(start):SKILL.index(end)]


def test_step_2_4_prints_one_preprocessing_table():
    step = _between("## Step 2.4", "## Step 2.5")
    assert "preprocessing" in step and "table" in step
    assert "Demand (assumed)" in step
    assert "Recommended plan" in step
    assert "Basis" in step
    assert "reply with numbers" in step


def test_step_2_4_no_longer_opens_with_a_questionnaire():
    step = _between("## Step 2.4", "## Step 2.5")
    assert "Two quick questions before I estimate cost" not in step
    assert "Ask both questions once" not in step


def test_skill_lite_scope_is_part_of_the_numbered_choice():
    step = _between("## Step 2.4", "## Step 2.5")
    assert "3–6 chapter scope in the numbered choice" in step


def test_step_1_5_infers_content_type_instead_of_asking():
    step = _between("## Step 1.5", "## Step 2 ")
    assert "Infer `BOOK_TYPE`" in step
    assert "What kind of content do these sources have?" not in step


def test_step_4_infers_depth_instead_of_asking_purpose():
    step = _between("## Step 4", "## Step 5 ")
    assert "Infer `DEPTH`" in step
    assert "What should this skill help you do?" not in step


def test_library_sweep_preprocesses_then_waits_for_numbered_selection():
    sweep = _between("### 6. Library Sweep", "## Skill Locations")
    assert "Preprocess the pending books" in sweep
    assert "preprocessing table" in sweep
    assert "reply with numbers" in sweep


def test_docs_describe_the_same_flow():
    assert "Preprocessing report" in TRIAGE_DOC
    assert "Demand (assumed)" in TRIAGE_DOC
    assert "one table" in TRIAGE_DOC
