"""Regression tests for the embedded-code-block-parsing gate check (C-008)."""

from uuid import uuid4

from plan_manager.domain.step import Step
from plan_manager.verify.gate import CHECK_IDS, GROUP_ORDER
from plan_manager.verify.gate_code import check_embedded_code_parses
from plan_manager.verify.gate_data import GateTree

_ORIGINAL_GROUP_ORDER = ["parse", "identity", "uniqueness", "references", "coverage"]

_ORIGINAL_CHECK_IDS = {
    "parse": [
        "parse.required_fields",
        "parse.inputs_outputs",
        "parse.target_file",
        "parse.sanity_counts",
    ],
    "identity": [
        "identity.step_id",
        "identity.slug",
        "identity.concept_id",
        "identity.label",
    ],
    "uniqueness": [
        "uniqueness.step_id",
        "uniqueness.concept_id",
        "uniqueness.label",
        "uniqueness.priority",
    ],
    "references": [
        "references.depends_on",
        "references.concepts",
        "references.relations",
        "references.source_labels",
    ],
    "coverage": [
        "coverage.concepts",
        "coverage.gs",
        "coverage.labels",
        "coverage.relations",
    ],
}


def _atomic(prompt):
    return Step(
        uuid=uuid4(),
        plan_uuid=uuid4(),
        parent_step_uuid=uuid4(),
        level=5,
        step_id="A-001",
        slug="fixture",
        fields={"prompt": prompt},
        depends_on=[],
        concepts=[],
        project_id=None,
        status="draft",
    )


def _tree(steps):
    return GateTree(
        steps={step.uuid: step for step in steps},
        concept_ids=[],
        relations=[],
        labels=[],
        counts={},
    )


def test_invalid_python_block_is_error():
    prompt = "Example.\n\n```python\ndef broken(\n    return 1\n```\n"
    step = _atomic(prompt)
    tree = _tree([step])

    findings = check_embedded_code_parses(tree, [step])

    assert len(findings) == 1
    assert findings[0].check_id == "embedded_code.parses"
    assert findings[0].severity == "error"
    assert "python" in findings[0].message


def test_invalid_sql_block_is_error():
    prompt = "Example.\n\n```sql\nSELECT * FROM (\n```\n"
    step = _atomic(prompt)
    tree = _tree([step])

    findings = check_embedded_code_parses(tree, [step])

    assert len(findings) == 1
    assert findings[0].check_id == "embedded_code.parses"
    assert findings[0].severity == "error"
    assert "sql" in findings[0].message


def test_unrecognized_language_fence_is_ignored():
    prompt = "Example.\n\n```yaml\nkey: value\n```\n"
    step = _atomic(prompt)
    tree = _tree([step])

    findings = check_embedded_code_parses(tree, [step])

    assert findings == []


def test_untagged_fence_with_junk_is_ignored():
    prompt = "Example.\n\n```\nthis is not code at all ) ( } { garbage\n```\n"
    step = _atomic(prompt)
    tree = _tree([step])

    findings = check_embedded_code_parses(tree, [step])

    assert findings == []


def test_python_block_with_backticks_in_content_parses_as_one_block():
    prompt = (
        "Example.\n\n"
        "```python\n"
        'FENCE_RE = r"```([^\\n]*)\\n(.*?)```"\n'
        "def add(a, b):\n"
        "    return a + b\n"
        "```\n"
    )
    step = _atomic(prompt)
    tree = _tree([step])

    findings = check_embedded_code_parses(tree, [step])

    assert findings == []


def test_python_block_with_unterminated_regex_string_still_one_block():
    # The mid-line backtick run must never be mistaken for a closing
    # fence; the block's real closer is the standalone ``` line below.
    prompt = (
        "Example.\n\n"
        "```python\n"
        "PATTERN = \"```([^\\\\n]*)\\\\n(.*?)```\"\n"
        "value = 1\n"
        "```\n"
    )
    step = _atomic(prompt)
    tree = _tree([step])

    findings = check_embedded_code_parses(tree, [step])

    assert findings == []


def test_valid_python_and_sql_blocks_pass():
    prompt = (
        "Example.\n\n"
        "```python\n"
        "def add(a, b):\n"
        "    return a + b\n"
        "```\n\n"
        "```sql\n"
        "SELECT id, name FROM users WHERE id = 1;\n"
        "```\n"
    )
    step = _atomic(prompt)
    tree = _tree([step])

    findings = check_embedded_code_parses(tree, [step])

    assert findings == []


def test_original_twenty_checks_unchanged():
    assert GROUP_ORDER[:5] == _ORIGINAL_GROUP_ORDER
    for group, check_ids in _ORIGINAL_CHECK_IDS.items():
        assert CHECK_IDS[group] == check_ids


def test_embedded_code_group_is_wired():
    assert "embedded_code" in GROUP_ORDER
    assert CHECK_IDS["embedded_code"] == ["embedded_code.parses"]
