from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class ConfigError(ValueError):
    """Raised when the plan_manager configuration section is invalid.

    The exception message is the explicit startup report describing every
    unknown key, missing required key, and type violation found in the
    configuration.
    """


class DatabaseSection(BaseModel):
    """Database connection parameters for the in-container PostgreSQL (C-035).

    Exactly one of ``host`` or ``socket`` must be set. No password field is
    defined here: the password is taken only from a mounted secrets file and
    is never part of configuration.
    """

    model_config = ConfigDict(extra="forbid")

    host: str | None = None
    socket: str | None = None
    port: int = 5432
    dbname: str
    user: str

    @model_validator(mode="after")
    def check_host_xor_socket(self) -> DatabaseSection:
        """Require exactly one of ``host`` or ``socket`` to be set.

        :return: ``self`` unchanged when validation passes.
        :raises ValueError: If both ``host`` and ``socket`` are ``None``, or
            if both are set.
        """
        if (self.host is None) == (self.socket is None):
            raise ValueError("exactly one of 'host' or 'socket' must be set")
        return self


class EmbeddingSection(BaseModel):
    """Optional embedding service settings.

    All fields are optional; the embedding service is the sole optional
    external integration and its absence degrades only semantic scoring.
    """

    model_config = ConfigDict(extra="forbid")

    url: str | None = None
    model: str | None = None
    timeout: float = 30.0


class CodeAnalysisSection(BaseModel):
    """Optional Code Analysis server (CA) settings, used for live anchor confirmation.

    All fields are optional; the CA server is an optional external integration
    (bug 5926d536) whose absence degrades project/file anchor confirmation
    only: a project/file anchor whose target cannot be confirmed against CA
    (unconfigured, unreachable, or a clean not-found response) is never
    persisted unverified -- the caller downgrades it to unanchored instead of
    refusing the create.

    ``url`` carries scheme, host, and port together (e.g.
    ``"mtls://casmgr:15010"``), the same shape as ``EmbeddingSection.url``.
    ``cert``/``key``/``ca`` are mTLS client-identity and trust material paths,
    required only when ``url`` uses the ``mtls`` scheme.
    """

    model_config = ConfigDict(extra="forbid")

    url: str | None = None
    timeout: float = 10.0
    cert: str | None = None
    key: str | None = None
    ca: str | None = None


class ScoringSection(BaseModel):
    """Optional scoring settings carrying the published defaults (C-028).

    ``aggregation`` admits only ``"minimum"`` or
    ``"fraction_above_threshold"``. ``embedding_serialization`` admits only
    ``"definition"``, the single implemented serialization.
    ``estimator_weights`` is the implemented fold: deterministic coverage
    1.0, deterministic references 1.0, and the model-based pair (embedding,
    simulation) sharing one vote of 1.0.
    """

    model_config = ConfigDict(extra="forbid")

    threshold: float = 85.0
    aggregation: str = "minimum"
    concept_weights: float = 1.0
    embedding_serialization: str = "definition"
    estimator_weights: dict[str, float] = Field(
        default_factory=lambda: {"coverage": 1.0, "references": 1.0, "model_pair": 1.0}
    )
    trust_floor: float = 0.2

    @field_validator("aggregation")
    @classmethod
    def check_aggregation(cls, value: str) -> str:
        """Validate that ``aggregation`` is an admitted value.

        :param value: The candidate aggregation name.
        :return: ``value`` unchanged when valid.
        :raises ValueError: If ``value`` is not ``"minimum"`` or
            ``"fraction_above_threshold"``, naming the invalid value.
        """
        if value not in ("minimum", "fraction_above_threshold"):
            raise ValueError(f"invalid aggregation: {value!r}")
        return value

    @field_validator("embedding_serialization")
    @classmethod
    def check_embedding_serialization(cls, value: str) -> str:
        """Validate that ``embedding_serialization`` is the admitted value.

        :param value: The candidate serialization name.
        :return: ``value`` unchanged when valid.
        :raises ValueError: If ``value`` is not ``"definition"``, naming the
            invalid value.
        """
        if value != "definition":
            raise ValueError(f"invalid embedding_serialization: {value!r}")
        return value


class PlanManagerSection(BaseModel):
    """Root model of the single custom plan_manager configuration section.

    Realizes Configuration (C-028): one top-level custom section of the
    platform's single JSON configuration file, validated by this Pydantic
    model performing an allowed-keys check via ``extra="forbid"`` at every
    level.
    """

    model_config = ConfigDict(extra="forbid")

    database: DatabaseSection
    embedding: EmbeddingSection = Field(default_factory=EmbeddingSection)
    code_analysis: CodeAnalysisSection = Field(default_factory=CodeAnalysisSection)
    scoring: ScoringSection = Field(default_factory=ScoringSection)
    schema_overrides: dict = Field(default_factory=dict)
    export_root: str


def load_raw(path: str) -> dict:
    """Read and parse the configuration file at ``path`` as a JSON object.

    :param path: Filesystem path to the JSON configuration file.
    :return: The parsed JSON document as a ``dict``.
    :raises ConfigError: If the file cannot be opened or read, if its
        contents are not valid JSON, or if the parsed document is not a JSON
        object (a ``dict``).
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read configuration file {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise ConfigError("configuration root must be a JSON object")
    return document


def load_config(path: str) -> PlanManagerSection:
    """Load and validate the plan_manager configuration section from ``path``.

    Platform-owned sections of the raw configuration document are never
    validated here; only the ``"plan_manager"`` top-level key is extracted
    and validated.

    :param path: Filesystem path to the JSON configuration file.
    :return: The validated :class:`PlanManagerSection`.
    :raises ConfigError: If the file cannot be read (propagated from
        :func:`load_raw`), if the ``"plan_manager"`` key is missing from the
        parsed document or is not a JSON object, or if the section fails
        Pydantic validation.
    """
    raw = load_raw(path)
    section = raw.get("plan_manager")
    if not isinstance(section, dict):
        raise ConfigError("configuration missing 'plan_manager' section")
    try:
        return PlanManagerSection.model_validate(section)
    except ValidationError as exc:
        raise ConfigError("invalid plan_manager configuration:\n" + str(exc)) from exc
