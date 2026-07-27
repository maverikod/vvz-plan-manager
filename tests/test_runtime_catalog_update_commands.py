from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import pytest

from plan_manager.commands import (
    invocation_profile_create_command,
    invocation_profile_get_command,
    invocation_profile_update_command,
    model_binding_get_command,
    model_binding_set_command,
    model_binding_update_command,
    model_create_command,
    model_get_command,
    model_update_command,
    project_dependency_add_command,
    project_dependency_update_command,
    provider_create_command,
    provider_get_command,
    provider_update_command,
    role_create_command,
    role_get_command,
    role_update_command,
    tool_create_command,
    tool_get_command,
    tool_update_command,
    toolset_create_command,
    toolset_get_command,
    toolset_update_command,
)


@contextmanager
def _fake_db():
    yield object()


class _Record:
    def __init__(self, payload: dict[str, Any] | None = None, **attrs: Any) -> None:
        self._payload = payload or {"uuid": "stub"}
        for key, value in attrs.items():
            setattr(self, key, value)

    def to_payload(self) -> dict[str, Any]:
        return dict(self._payload)


@dataclass(frozen=True)
class _UpdateSpec:
    name: str
    module: Any
    command_cls: type
    getter_name: str
    updater_name: str
    id_arg: str
    actor_arg: str
    actor_value: str
    mutable_arg: str
    mutable_value: Any
    expected_key: str
    not_found_code: str
    base_kwargs: dict[str, Any]
    existing_attrs: dict[str, Any]
    setup_name: str | None = None
    setup_impl: Any | None = None
    wrapped_payload_key: str | None = None


SPECS: tuple[_UpdateSpec, ...] = (
    _UpdateSpec(
        name="tool",
        module=tool_update_command,
        command_cls=tool_update_command.ToolUpdateCommand,
        getter_name="get_tool",
        updater_name="update_tool",
        id_arg="tool_uuid",
        actor_arg="changed_by",
        actor_value="owner",
        mutable_arg="description",
        mutable_value="updated tool",
        expected_key="description",
        not_found_code="TOOL_NOT_FOUND",
        base_kwargs={},
        existing_attrs={},
    ),
    _UpdateSpec(
        name="toolset",
        module=toolset_update_command,
        command_cls=toolset_update_command.ToolsetUpdateCommand,
        getter_name="get_toolset",
        updater_name="update_toolset",
        id_arg="toolset_uuid",
        actor_arg="changed_by",
        actor_value="owner",
        mutable_arg="description",
        mutable_value="updated toolset",
        expected_key="description",
        not_found_code="TOOLSET_NOT_FOUND",
        base_kwargs={},
        existing_attrs={},
    ),
    _UpdateSpec(
        name="provider",
        module=provider_update_command,
        command_cls=provider_update_command.ProviderUpdateCommand,
        getter_name="get_provider",
        updater_name="update_provider",
        id_arg="provider_uuid",
        actor_arg="changed_by",
        actor_value="owner",
        mutable_arg="status",
        mutable_value="active",
        expected_key="status",
        not_found_code="PROVIDER_NOT_FOUND",
        base_kwargs={},
        existing_attrs={},
    ),
    _UpdateSpec(
        name="model",
        module=model_update_command,
        command_cls=model_update_command.ModelUpdateCommand,
        getter_name="get_model",
        updater_name="update_model",
        id_arg="model_uuid",
        actor_arg="changed_by",
        actor_value="owner",
        mutable_arg="cost_class",
        mutable_value="economy",
        expected_key="cost_class",
        not_found_code="MODEL_NOT_FOUND",
        base_kwargs={},
        existing_attrs={},
    ),
    _UpdateSpec(
        name="role",
        module=role_update_command,
        command_cls=role_update_command.RoleUpdateCommand,
        getter_name="get_role",
        updater_name="update_role",
        id_arg="role_uuid",
        actor_arg="changed_by",
        actor_value="owner",
        mutable_arg="description",
        mutable_value="updated role",
        expected_key="description",
        not_found_code="ROLE_NOT_FOUND",
        base_kwargs={},
        existing_attrs={},
    ),
    _UpdateSpec(
        name="invocation_profile",
        module=invocation_profile_update_command,
        command_cls=invocation_profile_update_command.InvocationProfileUpdateCommand,
        getter_name="get_invocation_profile",
        updater_name="update_invocation_profile",
        id_arg="profile_uuid",
        actor_arg="changed_by",
        actor_value="owner",
        mutable_arg="temperature",
        mutable_value=0.5,
        expected_key="temperature",
        not_found_code="INVOCATION_PROFILE_NOT_FOUND",
        base_kwargs={},
        existing_attrs={},
    ),
    _UpdateSpec(
        name="model_binding",
        module=model_binding_update_command,
        command_cls=model_binding_update_command.ModelBindingUpdateCommand,
        getter_name="get_model_binding",
        updater_name="update_model_binding",
        id_arg="binding_uuid",
        actor_arg="changed_by",
        actor_value="owner",
        mutable_arg="timeout",
        mutable_value=900,
        expected_key="timeout",
        not_found_code="MODEL_BINDING_NOT_FOUND",
        base_kwargs={},
        existing_attrs={"plan_uuid": None},
        setup_name="refuse_if_model_binding_plan_completed",
        setup_impl=lambda conn, binding: None,
    ),
    _UpdateSpec(
        name="project_dependency",
        module=project_dependency_update_command,
        command_cls=project_dependency_update_command.ProjectDependencyUpdateCommand,
        getter_name="get_project_dependency",
        updater_name="update_project_dependency",
        id_arg="dependency_uuid",
        actor_arg="actor",
        actor_value="owner",
        mutable_arg="active",
        mutable_value=False,
        expected_key="active",
        not_found_code="PROJECT_DEPENDENCY_NOT_FOUND",
        base_kwargs={"plan": "scratch-plan"},
        existing_attrs={},
        setup_name="resolve_plan",
        setup_impl=lambda conn, plan: object(),
        wrapped_payload_key="project_dependency",
    ),
)


def _run(coro):
    return asyncio.run(coro)


def _assert_domain_code(result: Any, expected: str) -> None:
    payload = result.to_dict()
    assert "error" in payload, payload
    assert payload["error"]["data"]["domain_code"] == expected, payload["error"]["data"]


@pytest.mark.parametrize("spec", SPECS, ids=[spec.name for spec in SPECS])
def test_runtime_catalog_update_success(monkeypatch, spec: _UpdateSpec) -> None:
    monkeypatch.setattr(spec.module, "db_connection", _fake_db)
    if spec.setup_name is not None:
        monkeypatch.setattr(spec.module, spec.setup_name, spec.setup_impl)
    monkeypatch.setattr(
        spec.module,
        spec.getter_name,
        lambda conn, entity_uuid: _Record(**spec.existing_attrs),
    )

    captured: dict[str, Any] = {}

    def _update(conn, entity_uuid, **kwargs):
        captured.update(kwargs)
        return _Record({spec.expected_key: kwargs[spec.mutable_arg], "uuid": str(entity_uuid)})

    monkeypatch.setattr(spec.module, spec.updater_name, _update)

    result = _run(
        spec.command_cls().execute(
            **{
                spec.id_arg: str(uuid.uuid4()),
                spec.actor_arg: spec.actor_value,
                spec.mutable_arg: spec.mutable_value,
                **spec.base_kwargs,
            }
        )
    ).to_dict()

    assert result["success"] is True
    data = result["data"]
    if spec.wrapped_payload_key is not None:
        data = data[spec.wrapped_payload_key]
    assert data[spec.expected_key] == spec.mutable_value
    assert captured["changed_by"] == spec.actor_value
    assert captured[spec.mutable_arg] == spec.mutable_value


@pytest.mark.parametrize("spec", SPECS, ids=[spec.name for spec in SPECS])
def test_runtime_catalog_update_rejects_empty_patch(monkeypatch, spec: _UpdateSpec) -> None:
    monkeypatch.setattr(spec.module, "db_connection", _fake_db)
    if spec.setup_name is not None:
        monkeypatch.setattr(spec.module, spec.setup_name, spec.setup_impl)
    monkeypatch.setattr(
        spec.module,
        spec.getter_name,
        lambda conn, entity_uuid: _Record(**spec.existing_attrs),
    )

    result = _run(
        spec.command_cls().execute(
            **{
                spec.id_arg: str(uuid.uuid4()),
                spec.actor_arg: spec.actor_value,
                **spec.base_kwargs,
            }
        )
    )

    _assert_domain_code(result, "RUNTIME_VALIDATION_ERROR")


@pytest.mark.parametrize("spec", SPECS, ids=[spec.name for spec in SPECS])
def test_runtime_catalog_update_rejects_missing_record(monkeypatch, spec: _UpdateSpec) -> None:
    monkeypatch.setattr(spec.module, "db_connection", _fake_db)
    if spec.setup_name is not None:
        monkeypatch.setattr(spec.module, spec.setup_name, spec.setup_impl)
    monkeypatch.setattr(spec.module, spec.getter_name, lambda conn, entity_uuid: None)

    result = _run(
        spec.command_cls().execute(
            **{
                spec.id_arg: str(uuid.uuid4()),
                spec.actor_arg: spec.actor_value,
                spec.mutable_arg: spec.mutable_value,
                **spec.base_kwargs,
            }
        )
    )

    _assert_domain_code(result, spec.not_found_code)


def test_invocation_profile_update_converts_dialogue_chain_ref_to_uuid(monkeypatch) -> None:
    monkeypatch.setattr(invocation_profile_update_command, "db_connection", _fake_db)
    monkeypatch.setattr(
        invocation_profile_update_command,
        "get_invocation_profile",
        lambda conn, profile_uuid: _Record(),
    )

    captured: dict[str, Any] = {}

    def _update(conn, profile_uuid, **kwargs):
        captured.update(kwargs)
        return _Record({"uuid": str(profile_uuid)})

    monkeypatch.setattr(invocation_profile_update_command, "update_invocation_profile", _update)

    dialogue_chain_ref = str(uuid.uuid4())
    result = _run(
        invocation_profile_update_command.InvocationProfileUpdateCommand().execute(
            profile_uuid=str(uuid.uuid4()),
            changed_by="owner",
            dialogue_chain_ref=dialogue_chain_ref,
        )
    ).to_dict()

    assert result["success"] is True
    assert captured["dialogue_chain_ref"] == uuid.UUID(dialogue_chain_ref)


@dataclass(frozen=True)
class _GetSpec:
    name: str
    module: Any
    command_cls: type
    getter_name: str
    id_arg: str
    not_found_code: str


GET_SPECS: tuple[_GetSpec, ...] = (
    _GetSpec("tool", tool_get_command, tool_get_command.ToolGetCommand, "get_tool", "tool_uuid", "TOOL_NOT_FOUND"),
    _GetSpec("toolset", toolset_get_command, toolset_get_command.ToolsetGetCommand, "get_toolset", "toolset_uuid", "TOOLSET_NOT_FOUND"),
    _GetSpec("provider", provider_get_command, provider_get_command.ProviderGetCommand, "get_provider", "provider_uuid", "PROVIDER_NOT_FOUND"),
    _GetSpec("model", model_get_command, model_get_command.ModelGetCommand, "get_model", "model_uuid", "MODEL_NOT_FOUND"),
    _GetSpec("role", role_get_command, role_get_command.RoleGetCommand, "get_role", "role_uuid", "ROLE_NOT_FOUND"),
    _GetSpec(
        "invocation_profile",
        invocation_profile_get_command,
        invocation_profile_get_command.InvocationProfileGetCommand,
        "get_invocation_profile",
        "profile_uuid",
        "INVOCATION_PROFILE_NOT_FOUND",
    ),
    _GetSpec(
        "model_binding",
        model_binding_get_command,
        model_binding_get_command.ModelBindingGetCommand,
        "get_model_binding",
        "binding_uuid",
        "MODEL_BINDING_NOT_FOUND",
    ),
)


@pytest.mark.parametrize("spec", GET_SPECS, ids=[spec.name for spec in GET_SPECS])
def test_runtime_catalog_get_success(monkeypatch, spec: _GetSpec) -> None:
    monkeypatch.setattr(spec.module, "db_connection", _fake_db)
    monkeypatch.setattr(spec.module, spec.getter_name, lambda conn, entity_uuid: _Record({"uuid": str(entity_uuid)}))

    result = _run(spec.command_cls().execute(**{spec.id_arg: str(uuid.uuid4())})).to_dict()

    assert result["success"] is True
    assert "uuid" in result["data"]


@pytest.mark.parametrize("spec", GET_SPECS, ids=[spec.name for spec in GET_SPECS])
def test_runtime_catalog_get_missing_record(monkeypatch, spec: _GetSpec) -> None:
    monkeypatch.setattr(spec.module, "db_connection", _fake_db)
    monkeypatch.setattr(spec.module, spec.getter_name, lambda conn, entity_uuid: None)

    result = _run(spec.command_cls().execute(**{spec.id_arg: str(uuid.uuid4())}))

    _assert_domain_code(result, spec.not_found_code)


@dataclass(frozen=True)
class _CreateSpec:
    name: str
    module: Any
    command_cls: type
    kwargs: dict[str, Any]
    create_name: str
    expected_field: str
    expected_value: Any


CREATE_SPECS: tuple[_CreateSpec, ...] = (
    _CreateSpec(
        "tool",
        tool_create_command,
        tool_create_command.ToolCreateCommand,
        {
            "name": "tool-a",
            "server_id": "srv-1",
            "command": "search",
            "pinned_options": {"limit": 5},
            "created_by": "owner",
        },
        "create_tool",
        "name",
        "tool-a",
    ),
    _CreateSpec(
        "toolset",
        toolset_create_command,
        toolset_create_command.ToolsetCreateCommand,
        {"name": "toolset-a", "created_by": "owner"},
        "create_toolset",
        "name",
        "toolset-a",
    ),
    _CreateSpec(
        "role",
        role_create_command,
        role_create_command.RoleCreateCommand,
        {"name": "role-a", "created_by": "owner"},
        "create_role",
        "name",
        "role-a",
    ),
    _CreateSpec(
        "provider",
        provider_create_command,
        provider_create_command.ProviderCreateCommand,
        {
            "name": "provider-a",
            "type": "cloud_api",
            "rented_hardware": False,
            "status": "active",
            "created_by": "owner",
        },
        "create_provider",
        "name",
        "provider-a",
    ),
    _CreateSpec(
        "model",
        model_create_command,
        model_create_command.ModelCreateCommand,
        {
            "name": "model-a",
            "provider_uuid": str(uuid.uuid4()),
            "level": "frontier",
            "execution_mode": "interactive",
            "created_by": "owner",
        },
        "create_model",
        "name",
        "model-a",
    ),
    _CreateSpec(
        "invocation_profile",
        invocation_profile_create_command,
        invocation_profile_create_command.InvocationProfileCreateCommand,
        {"scope": "role", "role": "as_author", "created_by": "owner"},
        "create_invocation_profile",
        "scope",
        "role",
    ),
)


@pytest.mark.parametrize("spec", CREATE_SPECS, ids=[spec.name for spec in CREATE_SPECS])
def test_runtime_catalog_create_success(monkeypatch, spec: _CreateSpec) -> None:
    monkeypatch.setattr(spec.module, "db_connection", _fake_db)

    captured: dict[str, Any] = {}

    def _create(conn, **kwargs):
        captured.update(kwargs)
        return _Record({"uuid": "created-1", spec.expected_field: kwargs[spec.expected_field]})

    monkeypatch.setattr(spec.module, spec.create_name, _create)

    result = _run(spec.command_cls().execute(**spec.kwargs)).to_dict()

    assert result["success"] is True
    assert result["data"][spec.expected_field] == spec.expected_value
    assert captured[spec.expected_field] == spec.expected_value


def test_model_create_converts_provider_uuid(monkeypatch) -> None:
    monkeypatch.setattr(model_create_command, "db_connection", _fake_db)
    captured: dict[str, Any] = {}

    def _create(conn, **kwargs):
        captured.update(kwargs)
        return _Record({"uuid": "created-model"})

    monkeypatch.setattr(model_create_command, "create_model", _create)

    provider_uuid = str(uuid.uuid4())
    result = _run(
        model_create_command.ModelCreateCommand().execute(
            name="model-a",
            provider_uuid=provider_uuid,
            level="frontier",
            execution_mode="interactive",
            created_by="owner",
        )
    ).to_dict()

    assert result["success"] is True
    assert captured["provider_uuid"] == uuid.UUID(provider_uuid)


def test_invocation_profile_create_converts_dialogue_chain_ref_to_uuid(monkeypatch) -> None:
    monkeypatch.setattr(invocation_profile_create_command, "db_connection", _fake_db)
    captured: dict[str, Any] = {}

    def _create(conn, **kwargs):
        captured.update(kwargs)
        return _Record({"uuid": "created-profile"})

    monkeypatch.setattr(invocation_profile_create_command, "create_invocation_profile", _create)

    dialogue_chain_ref = str(uuid.uuid4())
    result = _run(
        invocation_profile_create_command.InvocationProfileCreateCommand().execute(
            scope="role",
            role="as_author",
            created_by="owner",
            dialogue_chain_ref=dialogue_chain_ref,
        )
    ).to_dict()

    assert result["success"] is True
    assert captured["dialogue_chain_ref"] == uuid.UUID(dialogue_chain_ref)


def test_model_binding_set_success(monkeypatch) -> None:
    monkeypatch.setattr(model_binding_set_command, "db_connection", _fake_db)
    monkeypatch.setattr(model_binding_set_command, "refuse_if_completed", lambda conn, plan_uuid: None)
    captured: dict[str, Any] = {}

    def _create(conn, **kwargs):
        captured.update(kwargs)
        return _Record({"uuid": "binding-1", "scope": kwargs["scope"], "provider": kwargs["provider"]})

    monkeypatch.setattr(model_binding_set_command, "create_model_binding", _create)

    result = _run(
        model_binding_set_command.ModelBindingSetCommand().execute(
            scope="role",
            provider="anthropic",
            model="haiku",
            max_retries=1,
            timeout=60,
            created_by="owner",
            role="as_author",
        )
    ).to_dict()

    assert result["success"] is True
    assert result["data"]["provider"] == "anthropic"
    assert captured["role"] == "as_author"


def test_project_dependency_add_success(monkeypatch) -> None:
    monkeypatch.setattr(project_dependency_add_command, "db_connection", _fake_db)
    monkeypatch.setattr(project_dependency_add_command, "resolve_plan", lambda conn, plan: object())
    captured: dict[str, Any] = {}

    def _create(conn, **kwargs):
        captured.update(kwargs)
        return _Record({"uuid": "dep-1", "active": kwargs["active"]})

    monkeypatch.setattr(project_dependency_add_command, "create_project_dependency", _create)

    dependent_project_id = str(uuid.uuid4())
    depends_on_project_id = str(uuid.uuid4())
    result = _run(
        project_dependency_add_command.ProjectDependencyAddCommand().execute(
            plan="scratch-plan",
            dependent_project_id=dependent_project_id,
            depends_on_project_id=depends_on_project_id,
            dependency_type="library",
            discovery_source="manual",
            actor="owner",
            active=False,
        )
    ).to_dict()

    assert result["success"] is True
    assert result["data"]["project_dependency"]["active"] is False
    assert captured["dependent_project_id"] == uuid.UUID(dependent_project_id)
    assert captured["depends_on_project_id"] == uuid.UUID(depends_on_project_id)
