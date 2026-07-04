"""Runtime accessors for ServerRuntime (C-027): the database connection
provider and the flat application-configuration projection consumed by
every command of the surface.

Runtime initialization happens once at startup: it loads and validates the
custom configuration section (C-028) via plan_manager.runtime.config, reads
the database password from the mounted secrets file, and holds the
validated section and the password in module state. Using any accessor
before init_runtime is an explicit runtime error. No accessor value is
ever taken from request parameters.
"""

import contextlib
import os
from dataclasses import dataclass

import psycopg
import psycopg.conninfo

from plan_manager.runtime.config import ConfigError, PlanManagerSection, load_config

SECRETS_ENV: str = "PLANMGR_SECRETS"
DEFAULT_SECRETS_PATH: str = "/etc/planmgr/secrets/db_password"

_SECTION: PlanManagerSection | None = None
_PASSWORD: str | None = None


def init_runtime(config_path: str) -> None:
    """Initialize module-level runtime state from a configuration file.

    Loads and validates the custom plan_manager configuration section from
    ``config_path`` via ``load_config``, then reads the database password
    from the mounted secrets file. The secrets file path is taken from the
    environment variable named by ``SECRETS_ENV``, defaulting to
    ``DEFAULT_SECRETS_PATH`` when the environment variable is unset. Stores
    both the validated section and the password in module state.

    Args:
        config_path: Filesystem path to the JSON configuration file passed
            to ``load_config``.

    Returns:
        None.

    Raises:
        ConfigError: If ``load_config`` raises for invalid configuration;
            if the secrets file cannot be opened or read (missing or
            unreadable file), reported as "cannot read database secrets
            file: {secrets_path}"; or if the secrets file content is empty
            after stripping leading and trailing whitespace, reported as
            "database secrets file is empty: {secrets_path}".
    """
    global _SECTION, _PASSWORD
    section = load_config(config_path)
    secrets_path = os.environ.get(SECRETS_ENV, DEFAULT_SECRETS_PATH)
    try:
        with open(secrets_path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as exc:
        raise ConfigError(
            f"cannot read database secrets file: {secrets_path}"
        ) from exc
    password = text.strip()
    if not password:
        raise ConfigError(f"database secrets file is empty: {secrets_path}")
    _SECTION = section
    _PASSWORD = password


def _require_section() -> PlanManagerSection:
    """Return the validated configuration section, requiring initialization.

    Returns:
        PlanManagerSection: The module-level validated configuration
            section stored by ``init_runtime``.

    Raises:
        RuntimeError: If ``init_runtime`` has not been called yet, reported
            as "runtime not initialized: call init_runtime first".
    """
    if _SECTION is None:
        raise RuntimeError("runtime not initialized: call init_runtime first")
    return _SECTION


def _conninfo() -> str:
    """Build a psycopg connection info string from module runtime state.

    Uses the database section of the validated configuration returned by
    ``_require_section()`` (``PlanManagerSection.database``): ``host`` if
    it is not None, otherwise ``socket`` (a unix socket directory passed
    as the psycopg ``host`` parameter), together with ``port``, ``dbname``,
    and ``user``. The password is the module-level value stored by
    ``init_runtime`` from the mounted secrets file.

    Returns:
        str: A connection string built by
            ``psycopg.conninfo.make_conninfo``.

    Raises:
        RuntimeError: If ``init_runtime`` has not been called yet (checked
            both through ``_require_section()`` for the configuration
            section and directly for the password), reported as "runtime
            not initialized: call init_runtime first".
    """
    db = _require_section().database
    if _PASSWORD is None:
        raise RuntimeError("runtime not initialized: call init_runtime first")
    host_value = db.host if db.host is not None else db.socket
    return psycopg.conninfo.make_conninfo(
        host=host_value,
        port=db.port,
        dbname=db.dbname,
        user=db.user,
        password=_PASSWORD,
    )


@contextlib.contextmanager
def db_connection():
    """Yield one open psycopg connection per context entry.

    Connection parameters come from server configuration and the mounted
    secrets file only, never from request parameters (C-028). Commits the
    transaction on clean exit, rolls it back when the body raises, and
    always closes the connection, regardless of outcome.

    Yields:
        psycopg.Connection: One open database connection built from
            ``_conninfo()``.

    Raises:
        RuntimeError: If ``init_runtime`` has not been called yet.
    """
    conn = psycopg.connect(_conninfo())
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


@dataclass(frozen=True)
class AppConfig:
    """Flat application-configuration projection consumed by the command layer.

    Attributes:
        embedding_url: The configured embedding service URL, or None when
            the embedding service is not configured.
        export_root: The default export root directory used when a caller
            passes a relative export path.
        scoring_threshold: The configured scoring pass/fail threshold.
        scoring_aggregation: The configured plan-level score aggregation
            mode.
        trust_floor: The configured trust floor applied when embeddings
            are unavailable.
        concept_weight: The configured uniform per-concept weight used in
            scoring.
    """

    embedding_url: str | None
    export_root: str
    scoring_threshold: float
    scoring_aggregation: str
    trust_floor: float
    concept_weight: float


def app_config() -> AppConfig:
    """Project the validated configuration section into an AppConfig.

    Returns:
        AppConfig: The flat projection built from the validated
            configuration section returned by ``_require_section()``:
            ``embedding_url`` from ``section.embedding.url``,
            ``export_root`` from ``section.export_root``,
            ``scoring_threshold`` from ``section.scoring.threshold``,
            ``scoring_aggregation`` from ``section.scoring.aggregation``,
            ``trust_floor`` from ``section.scoring.trust_floor``, and
            ``concept_weight`` from ``section.scoring.concept_weights``.

    Raises:
        RuntimeError: If ``init_runtime`` has not been called yet.
    """
    section = _require_section()
    return AppConfig(
        embedding_url=section.embedding.url,
        export_root=section.export_root,
        scoring_threshold=section.scoring.threshold,
        scoring_aggregation=section.scoring.aggregation,
        trust_floor=section.scoring.trust_floor,
        concept_weight=section.scoring.concept_weights,
    )
