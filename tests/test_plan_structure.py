import re
from collections import defaultdict
from pathlib import Path

import yaml


PLAN_ROOT = Path("docs/plans/2026-07-02-plan-manager")
STEP_ID_RE = re.compile(r"^A-\d{3}$")


def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text())
    assert isinstance(data, dict), f"{path} must contain a YAML object"
    return data


def _step_prefix(path: Path) -> str:
    return "-".join(path.stem.split("-", 2)[:2])


def test_active_plan_tree_has_consistent_atomic_references() -> None:
    assert (PLAN_ROOT / "source_spec.md").is_file()
    assert (PLAN_ROOT / "spec.yaml").is_file()

    global_readmes = sorted(PLAN_ROOT.glob("G-*/README.yaml"))
    tactical_readmes = sorted(PLAN_ROOT.glob("G-*/T-*/README.yaml"))
    atomic_files = sorted(PLAN_ROOT.glob("G-*/T-*/atomic_steps/A-*.yaml"))

    assert len(global_readmes) == 8
    assert len(tactical_readmes) == 48
    assert len(atomic_files) == 407

    for tactical_readme in tactical_readmes:
        tactical = _load_yaml(tactical_readme)
        listed = tactical.get("atomic_steps")
        assert isinstance(listed, list), f"{tactical_readme}: atomic_steps must be a list"
        assert all(isinstance(step_id, str) for step_id in listed)
        assert all(STEP_ID_RE.fullmatch(step_id) for step_id in listed), tactical_readme

        actual = {
            _step_prefix(path)
            for path in (tactical_readme.parent / "atomic_steps").glob("A-*.yaml")
        }
        assert set(listed) == actual, tactical_readme


def test_active_plan_atomic_step_fields_are_mechanically_valid() -> None:
    spec = _load_yaml(PLAN_ROOT / "spec.yaml")
    concept_ids = {
        item["concept_id"]
        for item in spec.get("concepts", [])
        if isinstance(item, dict) and "concept_id" in item
    }
    assert concept_ids

    priorities: dict[tuple[Path, str], set[int]] = defaultdict(set)
    allowed_operations = {"create_file", "modify_file", "delete_file", "rename_file"}
    allowed_verifications = {"pytest", "import", "static_analysis", "manual"}

    for atomic_path in sorted(PLAN_ROOT.glob("G-*/T-*/atomic_steps/A-*.yaml")):
        atomic = _load_yaml(atomic_path)
        assert STEP_ID_RE.fullmatch(atomic.get("step_id", "")), atomic_path
        assert atomic.get("operation") in allowed_operations, atomic_path
        assert atomic.get("status") == "draft", atomic_path

        target_file = atomic.get("target_file")
        assert isinstance(target_file, str) and target_file.strip(), atomic_path
        target = Path(target_file)
        assert not target.is_absolute(), atomic_path
        assert ".." not in target.parts, atomic_path
        if atomic.get("operation") in {"create_file", "modify_file"}:
            assert target.exists(), (atomic_path, target_file)
            assert target.is_file(), (atomic_path, target_file)
            assert sum(1 for _ in target.open(errors="ignore")) <= 400, (
                atomic_path,
                target_file,
            )

        verification = atomic.get("verification")
        assert isinstance(verification, dict), atomic_path
        assert verification.get("type") in allowed_verifications, atomic_path
        assert verification.get("target"), atomic_path
        assert verification.get("expected"), atomic_path

        for concept_id in atomic.get("concepts", []):
            assert concept_id in concept_ids, (atomic_path, concept_id)

        key = (atomic_path.parents[1], target_file)
        priority = atomic.get("priority")
        assert isinstance(priority, int), atomic_path
        assert priority not in priorities[key], atomic_path
        priorities[key].add(priority)
