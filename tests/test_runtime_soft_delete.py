"""Runtime store soft-delete and archive signature test coverage (C-035, HRS {d118} bullet 24)."""

import importlib
import inspect

RUNTIME_STORE_SOFT_DELETE_TARGETS = (
    ("plan_manager.storage.todo_store", "soft_delete_todo", "list_todos"),
    ("plan_manager.storage.runtime_comment_store", "soft_delete_comment", "list_comments"),
    ("plan_manager.storage.bug_report_store", "soft_delete_bug", "list_bugs"),
    ("plan_manager.storage.bug_impact_store", "soft_delete_bug_impact", "list_bug_impacts"),
    ("plan_manager.storage.bug_fix_store", "soft_delete_bug_fix", "list_bug_fixes"),
    ("plan_manager.storage.bug_fix_propagation_store", "soft_delete_bug_fix_propagation", "list_bug_fix_propagations"),
)

def test_every_runtime_store_exposes_soft_delete_function() -> None:
    for module_path, soft_delete_name, _list_name in RUNTIME_STORE_SOFT_DELETE_TARGETS:
        module = importlib.import_module(module_path)
        assert hasattr(module, soft_delete_name), f"{module_path} is missing {soft_delete_name}"
        func = getattr(module, soft_delete_name)
        assert callable(func), f"{module_path}.{soft_delete_name} is not callable"

        signature = inspect.signature(func)
        parameters = signature.parameters
        param_names = list(parameters)
        assert param_names[0] == "conn", (
            f"{module_path}.{soft_delete_name} must take conn as its first parameter"
        )
        assert "changed_by" in parameters, (
            f"{module_path}.{soft_delete_name} must accept a changed_by parameter"
        )
        changed_by_param = parameters["changed_by"]
        assert changed_by_param.kind == inspect.Parameter.KEYWORD_ONLY, (
            f"{module_path}.{soft_delete_name} changed_by must be keyword-only"
        )
        assert changed_by_param.default is inspect.Parameter.empty, (
            f"{module_path}.{soft_delete_name} changed_by must have no default (required)"
        )

def test_every_runtime_store_list_function_defaults_to_excluding_deleted() -> None:
    for module_path, _soft_delete_name, list_name in RUNTIME_STORE_SOFT_DELETE_TARGETS:
        module = importlib.import_module(module_path)
        assert hasattr(module, list_name), f"{module_path} is missing {list_name}"
        func = getattr(module, list_name)
        assert callable(func), f"{module_path}.{list_name} is not callable"

        signature = inspect.signature(func)
        parameters = signature.parameters
        assert "include_deleted" in parameters, (
            f"{module_path}.{list_name} must accept an include_deleted parameter"
        )
        include_deleted_param = parameters["include_deleted"]
        assert include_deleted_param.default is False, (
            f"{module_path}.{list_name} include_deleted must default to False "
            f"(deleted records excluded by default)"
        )

def test_registry_lists_six_distinct_runtime_stores() -> None:
    module_paths = [entry[0] for entry in RUNTIME_STORE_SOFT_DELETE_TARGETS]
    soft_delete_names = [entry[1] for entry in RUNTIME_STORE_SOFT_DELETE_TARGETS]

    assert len(RUNTIME_STORE_SOFT_DELETE_TARGETS) == 6
    assert len(module_paths) == len(set(module_paths)), "duplicate module path in registry"
    assert len(soft_delete_names) == len(set(soft_delete_names)), "duplicate soft-delete function name in registry"
