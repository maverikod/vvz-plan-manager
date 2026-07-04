# G-006/T-001 Config Model Execution Context

Inherited base context:
- `docs/plans/2026-07-02-plan-manager/execution_context/base.md`

Inherited G context:
- `docs/plans/2026-07-02-plan-manager/execution_context/G-006-runtime-config/context.md`

Execution standard:
- `docs/standards/planning/atomic_step_execution_standard.yaml`

Active plan root:
- `docs/plans/2026-07-02-plan-manager`

Current target file state:
- `plan_manager/runtime/config.py`: missing

Allowed write scope:
- Exactly one file: `plan_manager/runtime/config.py`
- No other file may be edited unless an explicit escalation is required
- Preserve unrelated dirty changes
- Do not touch HRS/MRS/GS/TS artifacts

T README content:

```yaml
step_id: T-001
parent_global_step: G-006
name: config-model
description: >
  Create the configuration model of the single custom section (C-028). The
  section is one top-level entry of the platform's single JSON configuration
  file; platform-owned sections pass through unchanged, and the custom
  section is validated at startup by an own Pydantic model performing an
  allowed-keys check — an unknown key, a missing required key, or a
  type-invalid value aborts startup with an explicit report naming every
  violation. The model carries: the required database (C-035) connection
  parameters — exactly one of host or socket path, port, database name, and
  user — with no password field anywhere in configuration, since the password
  comes only from the mounted secrets file; the optional embedding service
  settings (URL, model name, request timeout); the optional scoring settings
  carrying the published defaults — threshold 85, aggregation minimum with
  fraction-above-threshold as the only alternative value, uniform concept
  weight 1.0, definition-only embedding serialization as the only admitted
  value, the estimator weights of the implemented fold (deterministic
  coverage 1.0, deterministic references 1.0, the model-based pair sharing
  one vote of 1.0), and trust floor 0.2; the optional PlanSchema overrides
  mapping for the exchange layout; and the required default export root. The
  per-plan context budget is plan data, not a configuration field, and no
  value of this section is ever taken from request parameters. This step
  defines the section model, its sub-models, defaults, validators, the
  loading of the JSON file with platform-native dictionary access, and the
  typed configuration error carrying the explicit startup report; it opens
  no database connection and starts no server.
concepts: [C-028, C-027, C-035]
inputs:
- name: configuration_file
  type: file datum
  description: >
    The single JSON configuration file whose custom section is extracted by
    platform-native dictionary access and validated by the model.
outputs:
- name: validated_section
  type: configuration object
  description: >
    The validated custom-section object with defaults applied, consumed by
    the runtime accessors and the bootstrap.
- name: configuration_error
  type: typed condition
  description: >
    The explicit startup-abort report naming every unknown key, missing
    required key, and type violation of the custom section.
atomic_steps:
- A-001-module-header-and-config-error
- A-002-database-section
- A-003-embedding-section
- A-004-scoring-section
- A-005-plan-manager-section
- A-006-load-raw
- A-007-load-config
status: draft
```

Relevant parallelization map entry:

```yaml
- branch_id: G-006
  name: runtime-config
  status: draft
  depends_on:
  - G-001
  tactical_steps:
  - branch_id: G-006/T-001
    name: config-model
    status: draft
    mini_assignment:
      model: gpt-5.4-mini
      context:
      - docs/plans/2026-07-02-plan-manager/G-006-runtime-config/README.yaml
      - docs/plans/2026-07-02-plan-manager/G-006-runtime-config/T-001-config-model/README.yaml
      - docs/plans/2026-07-02-plan-manager/G-006-runtime-config/T-001-config-model/atomic_steps
      forbidden_context:
      - sibling TS directories
      - other GS directories unless owner escalates
    counts:
      atomic_steps: 7
      target_files: 1
      parallel_waves: 7
    target_file_sequences:
    - target_file: plan_manager/runtime/config.py
      sequence:
      - G-006/T-001/A-001
      - G-006/T-001/A-002
      - G-006/T-001/A-003
      - G-006/T-001/A-004
      - G-006/T-001/A-005
      - G-006/T-001/A-006
      - G-006/T-001/A-007
    parallel_waves:
    - - G-006/T-001/A-001
    - - G-006/T-001/A-002
    - - G-006/T-001/A-003
    - - G-006/T-001/A-004
    - - G-006/T-001/A-005
    - - G-006/T-001/A-006
    - - G-006/T-001/A-007
    unresolved_cycles: []
```

Target-file sequence:
1. `G-006/T-001/A-001`
2. `G-006/T-001/A-002`
3. `G-006/T-001/A-003`
4. `G-006/T-001/A-004`
5. `G-006/T-001/A-005`
6. `G-006/T-001/A-006`
7. `G-006/T-001/A-007`

Verification commands:
1. `python` import and smoke-check after `A-001`:
   ```bash
   python - <<'PY'
   import plan_manager.runtime.config as m
   assert hasattr(m, "ConfigError")
   assert issubclass(m.ConfigError, ValueError)
   PY
   ```
2. `python` import and validation checks after `A-002`:
   ```bash
   python - <<'PY'
   import plan_manager.runtime.config as m
   ok = m.DatabaseSection(dbname="p", user="u", host="localhost")
   assert ok.port == 5432 and ok.socket is None
   assert m.DatabaseSection(dbname="p", user="u", socket="/tmp/x").host is None
   PY
   ```
3. `python` import and defaults after `A-003`:
   ```bash
   python - <<'PY'
   import plan_manager.runtime.config as m
   e = m.EmbeddingSection()
   assert e.url is None and e.model is None and e.timeout == 30.0
   PY
   ```
4. `python` import and validator checks after `A-004`:
   ```bash
   python - <<'PY'
   import plan_manager.runtime.config as m
   s = m.ScoringSection()
   assert s.threshold == 85.0
   assert s.aggregation == "minimum"
   assert s.embedding_serialization == "definition"
   assert s.estimator_weights == {"coverage": 1.0, "references": 1.0, "model_pair": 1.0}
   PY
   ```
5. `python` import and root-model checks after `A-005`:
   ```bash
   python - <<'PY'
   import plan_manager.runtime.config as m
   pm = m.PlanManagerSection(database={"dbname": "p", "user": "u", "host": "h"}, export_root="/tmp")
   assert pm.embedding.model is None
   assert pm.scoring.threshold == 85.0
   PY
   ```
6. `python` raw-load checks after `A-006`:
   ```bash
   python - <<'PY'
   import tempfile
   from pathlib import Path
   import plan_manager.runtime.config as m
   with tempfile.TemporaryDirectory() as d:
       p = Path(d) / "cfg.json"
       p.write_text('{"a": 1}', encoding="utf-8")
       assert m.load_raw(str(p)) == {"a": 1}
   PY
   ```
7. `python` full-config load checks after `A-007`:
   ```bash
   python - <<'PY'
   import tempfile
   from pathlib import Path
   import plan_manager.runtime.config as m
   with tempfile.TemporaryDirectory() as d:
       p = Path(d) / "cfg.json"
       p.write_text('{"plan_manager": {"database": {"dbname": "p", "user": "u", "host": "h"}, "export_root": "/tmp"}}', encoding="utf-8")
       cfg = m.load_config(str(p))
       assert cfg.database.dbname == "p"
   PY
   ```

AS file contents:

### A-001-module-header-and-config-error.yaml

```yaml
step_id: A-001
parent_tactical_step: T-001
name: module-header-and-config-error
target_file: plan_manager/runtime/config.py
operation: create_file
priority: 1
depends_on: []
concepts: [C-028]
status: draft
prompt: |
  Create the new Python file at the exact project-relative path
  `plan_manager/runtime/config.py`.

  This is a `create_file` operation: the file does not exist yet. Do not
  assume any pre-existing content. Write exactly the following content,
  byte-identical, as the complete content of the new file:

  ```python
  from __future__ import annotations

  import json

  from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


  class ConfigError(ValueError):
      """Raised when the plan_manager configuration section is invalid.

      The exception message is the explicit startup report describing every
      unknown key, missing required key, and type violation found in the
      configuration.
      """
  ```

  Requirements, all explicit, no open decisions:

  - Module-level imports, in this exact order, each on its own line:
    1. `from __future__ import annotations`
    2. `import json`
    3. `from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator`
  - Exactly one blank line after `from __future__ import annotations`,
    separating it from `import json`.
  - Exactly two blank lines after the pydantic import line, before the
    `class ConfigError(ValueError):` definition (PEP 8 two-blank-lines
    convention before a top-level class).
  - `ConfigError` is a class named exactly `ConfigError`, inheriting from the
    builtin `ValueError` (no other base classes, no `__init__` override, no
    additional methods or attributes).
  - `ConfigError` has no body other than the docstring shown above, quoted
    verbatim, using triple double-quotes.
  - Do not add any other classes, functions, constants, or `__all__` in this
    file. Later modification steps will append to this file; only the exact
    content shown above must be present after this step.
  - Do not add a trailing module docstring; the file starts directly with
    `from __future__ import annotations`.

  MRS excerpt (only the concept relevant to this step):

  ```yaml
  - concept_id: C-028
    name: Configuration
    definition: Single JSON configuration with adapter sections plus one plan_manager section validated by a Pydantic model.
    properties:
    - fields database, embedding, scoring, schema_overrides, export_root
    - scoring carries published defaults (threshold 85, aggregation minimum, uniform concept weights, definition-only serialization, shared embedding vote, trust floor 0.2)
    - the per-plan context budget is plan data, not a configuration field
    - password only from mounted secrets; invalid config aborts startup
    - no configuration value is ever taken from request parameters
    source_labels: ["{n6a4}", "{c3k8}", "{d8o2}", "{e5m7}", "{b3e6}"]
  ```

  `ConfigError` realizes the "invalid config aborts startup" property of
  C-028: it is the typed condition whose message carries the explicit
  startup report (the report text itself is assembled by later functions in
  this same file, appended by subsequent modification steps to this file).
verification:
  type: import
  target: plan_manager.runtime.config
  expected: >
    Importing the module plan_manager.runtime.config succeeds without
    raising any exception. The module defines a class named ConfigError
    that is a subclass of the builtin ValueError, has no additional base
    classes, and has no methods or attributes beyond its docstring. The
    module's source file starts with the line
    "from __future__ import annotations" followed by "import json" and the
    single pydantic import line listing BaseModel, ConfigDict, Field,
    ValidationError, field_validator, and model_validator, in that order,
    with no other top-level names defined.
```

### A-002-database-section.yaml

```yaml
step_id: A-002
parent_tactical_step: T-001
name: database-section
target_file: plan_manager/runtime/config.py
operation: modify_file
priority: 2
depends_on: [A-001]
concepts: [C-028, C-035]
status: draft
prompt: |
  Modify the existing Python file at the exact project-relative path
  `plan_manager/runtime/config.py`.

  This is a `modify_file` operation. The full current content of the file,
  exactly as it exists after all lower-priority atomic steps on this file
  have been applied, is:

  ```python
  from __future__ import annotations

  import json

  from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


  class ConfigError(ValueError):
      """Raised when the plan_manager configuration section is invalid.

      The exception message is the explicit startup report describing every
      unknown key, missing required key, and type violation found in the
      configuration.
      """
  ```

  Append the following new class to the end of the file, separated from the
  `ConfigError` class above by exactly two blank lines:

  ```python
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
  ```

  Requirements, all explicit, no open decisions:

  - `DatabaseSection` is a class named exactly `DatabaseSection`, inheriting
    from `BaseModel` (imported at the top of the file from `pydantic`; do not
    add any new import statements — `BaseModel`, `ConfigDict`, and
    `model_validator` are already imported at the top of the file).
  - `model_config = ConfigDict(extra="forbid")` is the first statement in the
    class body after the docstring; this is the allowed-keys check: any
    field in the input data not declared below raises a pydantic
    `ValidationError`.
  - Fields, in this exact order, with these exact type annotations and
    defaults:
    - `host: str | None = None`
    - `socket: str | None = None`
    - `port: int = 5432`
    - `dbname: str` (required, no default)
    - `user: str` (required, no default)
  - No `password` field of any name or type is defined on this class, and no
    comment or code references a password. This is deliberate: the password
    comes only from a mounted secrets file outside this model.
  - A `model_validator` with `mode="after"` named exactly
    `check_host_xor_socket`, taking only `self`, returning type
    `DatabaseSection` (written as a bare name, relying on the
    `from __future__ import annotations` already active at the top of the
    file — do not quote the return type as a string).
  - The validator body: if `(self.host is None) == (self.socket is None)`
    (i.e. both are `None`, or both are set) it raises
    `ValueError("exactly one of 'host' or 'socket' must be set")`, this
    exact message string; otherwise it returns `self` unchanged.
  - Do not add any fields, methods, or validators beyond what is shown.
  - Do not modify the existing `ConfigError` class or the module-level
    imports in any way.
  - After this change, the file ends with the `DatabaseSection` class shown
    above; no further content follows it in this step.

  MRS excerpt (only the concepts and relation relevant to this step):

  ```yaml
  - concept_id: C-028
    name: Configuration
    definition: Single JSON configuration with adapter sections plus one plan_manager section validated by a Pydantic model.
    properties:
    - fields database, embedding, scoring, schema_overrides, export_root
    - scoring carries published defaults (threshold 85, aggregation minimum, uniform concept weights, definition-only serialization, shared embedding vote, trust floor 0.2)
    - the per-plan context budget is plan data, not a configuration field
    - password only from mounted secrets; invalid config aborts startup
    - no configuration value is ever taken from request parameters
    source_labels: ["{n6a4}", "{c3k8}", "{d8o2}", "{e5m7}", "{b3e6}"]

  - concept_id: C-035
    name: Database
    definition: In-container PostgreSQL with pgvector serving as the single source of truth for all plan data.
    properties:
    - entities as rows; referential integrity at write time
    - every stored entity carries an immutable UUID identity; human-readable ids are scoped names mapped to it
    - hosts the version store, locks, and embedding cache
    - accessed via psycopg 3 with plain SQL; no ORM; runtime code never emits DDL
    source_labels: ["{z8c3}", "{q2r9}", "{z6n1}", "{t6s8}", "{b8j5}", "{x3o9}"]
  ```

  Relation relevant to this step: `{ from_concept: C-027, to_concept: C-035,
  type: uses }` — the server runtime uses the database; `DatabaseSection`
  supplies the connection parameters (socket or host, port, database name,
  user) that C-028's `database` field carries, matching C-035's stated
  access pattern of psycopg 3 with plain SQL and no ORM (the connection
  parameters here do not themselves open a connection).
verification:
  type: import
  target: plan_manager.runtime.config
  expected: >
    Importing the module plan_manager.runtime.config succeeds. The module
    now defines DatabaseSection in addition to ConfigError.
    DatabaseSection(dbname="p", user="u", host="localhost") constructs
    successfully with port defaulting to 5432 and socket None.
    DatabaseSection(dbname="p", user="u", socket="/tmp/x") constructs
    successfully with host None. Constructing DatabaseSection(dbname="p",
    user="u") with neither host nor socket set raises a pydantic
    ValidationError whose message includes "exactly one of 'host' or
    'socket' must be set". Constructing DatabaseSection(dbname="p",
    user="u", host="localhost", socket="/tmp/x") with both set raises the
    same ValidationError. Passing any additional unknown keyword (for
    example password="x") raises a ValidationError due to extra="forbid".
```

### A-003-embedding-section.yaml

```yaml
step_id: A-003
parent_tactical_step: T-001
name: embedding-section
target_file: plan_manager/runtime/config.py
operation: modify_file
priority: 3
depends_on: [A-002]
concepts: [C-028]
status: draft
prompt: |
  Modify the existing Python file at the exact project-relative path
  `plan_manager/runtime/config.py`.

  This is a `modify_file` operation. The full current content of the file,
  exactly as it exists after all lower-priority atomic steps on this file
  have been applied, is:

  ```python
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
  ```

  Append the following new class to the end of the file, separated from the
  `DatabaseSection` class above by exactly two blank lines:

  ```python
  class EmbeddingSection(BaseModel):
      """Optional embedding service settings.

      All fields are optional; the embedding service is the sole optional
      external integration and its absence degrades only semantic scoring.
      """

      model_config = ConfigDict(extra="forbid")

      url: str | None = None
      model: str | None = None
      timeout: float = 30.0
  ```

  Requirements, all explicit, no open decisions:

  - `EmbeddingSection` is a class named exactly `EmbeddingSection`,
    inheriting from `BaseModel` (already imported at the top of the file; do
    not add any new import statements).
  - `model_config = ConfigDict(extra="forbid")` is the first statement in
    the class body after the docstring.
  - Fields, in this exact order, with these exact type annotations and
    defaults:
    - `url: str | None = None`
    - `model: str | None = None`
    - `timeout: float = 30.0`
  - No validators, no additional fields, no methods.
  - Do not modify any earlier class (`ConfigError`, `DatabaseSection`) or the
    module-level imports in any way.
  - After this change, the file ends with the `EmbeddingSection` class shown
    above; no further content follows it in this step.

  MRS excerpt (only the concept relevant to this step):

  ```yaml
  - concept_id: C-028
    name: Configuration
    definition: Single JSON configuration with adapter sections plus one plan_manager section validated by a Pydantic model.
    properties:
    - fields database, embedding, scoring, schema_overrides, export_root
    - scoring carries published defaults (threshold 85, aggregation minimum, uniform concept weights, definition-only serialization, shared embedding vote, trust floor 0.2)
    - the per-plan context budget is plan data, not a configuration field
    - password only from mounted secrets; invalid config aborts startup
    - no configuration value is ever taken from request parameters
    source_labels: ["{n6a4}", "{c3k8}", "{d8o2}", "{e5m7}", "{b3e6}"]
  ```

  `EmbeddingSection` realizes the "embedding" field named in C-028's fields
  property (database, embedding, scoring, schema_overrides, export_root):
  the optional embedding service settings sub-model.
verification:
  type: import
  target: plan_manager.runtime.config
  expected: >
    Importing the module plan_manager.runtime.config succeeds. The module
    now defines EmbeddingSection in addition to ConfigError and
    DatabaseSection. EmbeddingSection() constructs successfully with url
    None, model None, and timeout 30.0. EmbeddingSection(url="http://x",
    model="m", timeout=5.0) constructs successfully with those exact
    values. Passing any additional unknown keyword raises a pydantic
    ValidationError due to extra="forbid".
```

### A-004-scoring-section.yaml

```yaml
step_id: A-004
parent_tactical_step: T-001
name: scoring-section
target_file: plan_manager/runtime/config.py
operation: modify_file
priority: 4
depends_on: [A-003]
concepts: [C-028]
status: draft
prompt: |
  Modify the existing Python file at the exact project-relative path
  `plan_manager/runtime/config.py`.

  This is a `modify_file` operation. The full current content of the file,
  exactly as it exists after all lower-priority atomic steps on this file
  have been applied, is:

  ```python
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
  ```

  Append the following new class to the end of the file, separated from the
  `EmbeddingSection` class above by exactly two blank lines:

  ```python
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
  ```

  Requirements, all explicit, no open decisions:

  - `ScoringSection` is a class named exactly `ScoringSection`, inheriting
    from `BaseModel` (already imported at the top of the file; `Field` and
    `field_validator` are also already imported at the top of the file — do
    not add any new import statements).
  - `model_config = ConfigDict(extra="forbid")` is the first statement in
    the class body after the docstring.
  - Fields, in this exact order, with these exact type annotations and
    defaults:
    - `threshold: float = 85.0`
    - `aggregation: str = "minimum"`
    - `concept_weights: float = 1.0`
    - `embedding_serialization: str = "definition"`
    - `estimator_weights: dict[str, float] = Field(default_factory=lambda: {"coverage": 1.0, "references": 1.0, "model_pair": 1.0})`
      — written exactly as shown, wrapped across two lines with the closing
      parenthesis on its own line as shown in the code block above.
    - `trust_floor: float = 0.2`
  - A `field_validator` decorated method named exactly `check_aggregation`,
    validating the `aggregation` field, decorated with
    `@field_validator("aggregation")` then `@classmethod` (in that order),
    taking `(cls, value: str)`, returning `str`. Body: if `value` is not in
    the tuple `("minimum", "fraction_above_threshold")`, raise
    `ValueError(f"invalid aggregation: {value!r}")`; otherwise return
    `value`.
  - A `field_validator` decorated method named exactly
    `check_embedding_serialization`, validating the
    `embedding_serialization` field, decorated with
    `@field_validator("embedding_serialization")` then `@classmethod` (in
    that order), taking `(cls, value: str)`, returning `str`. Body: if
    `value != "definition"`, raise
    `ValueError(f"invalid embedding_serialization: {value!r}")`; otherwise
    return `value`.
  - Do not add any fields, methods, or validators beyond what is shown. Do
    not add a validator for `threshold`, `concept_weights`, `trust_floor`,
    or `estimator_weights` — none is required.
  - Do not modify any earlier class (`ConfigError`, `DatabaseSection`,
    `EmbeddingSection`) or the module-level imports in any way.
  - After this change, the file ends with the `ScoringSection` class shown
    above; no further content follows it in this step.

  MRS excerpt (only the concept relevant to this step):

  ```yaml
  - concept_id: C-028
    name: Configuration
    definition: Single JSON configuration with adapter sections plus one plan_manager section validated by a Pydantic model.
    properties:
    - fields database, embedding, scoring, schema_overrides, export_root
    - scoring carries published defaults (threshold 85, aggregation minimum, uniform concept weights, definition-only serialization, shared embedding vote, trust floor 0.2)
    - the per-plan context budget is plan data, not a configuration field
    - password only from mounted secrets; invalid config aborts startup
    - no configuration value is ever taken from request parameters
    source_labels: ["{n6a4}", "{c3k8}", "{d8o2}", "{e5m7}", "{b3e6}"]
  ```

  `ScoringSection` realizes the "scoring" field and its published defaults
  named directly in C-028's properties: threshold 85, aggregation minimum,
  uniform concept weights (1.0), definition-only serialization, the shared
  embedding vote (folded here as the `model_pair` entry of
  `estimator_weights`, worth 1.0 alongside `coverage` 1.0 and `references`
  1.0), and trust floor 0.2.
verification:
  type: import
  target: plan_manager.runtime.config
  expected: >
    Importing the module plan_manager.runtime.config succeeds. The module
    now defines ScoringSection in addition to ConfigError, DatabaseSection,
    and EmbeddingSection. ScoringSection() constructs successfully with
    threshold 85.0, aggregation "minimum", concept_weights 1.0,
    embedding_serialization "definition", estimator_weights equal to
    {"coverage": 1.0, "references": 1.0, "model_pair": 1.0}, and trust_floor
    0.2. ScoringSection(aggregation="fraction_above_threshold") constructs
    successfully. ScoringSection(aggregation="bogus") raises a pydantic
    ValidationError whose message includes "invalid aggregation: 'bogus'".
    ScoringSection(embedding_serialization="raw") raises a ValidationError
    whose message includes "invalid embedding_serialization: 'raw'".
    Passing any additional unknown keyword raises a ValidationError due to
    extra="forbid".
```

### A-005-plan-manager-section.yaml

```yaml
step_id: A-005
parent_tactical_step: T-001
name: plan-manager-section
target_file: plan_manager/runtime/config.py
operation: modify_file
priority: 5
depends_on: [A-004]
concepts: [C-028, C-035]
status: draft
prompt: |
  Modify the existing Python file at the exact project-relative path
  `plan_manager/runtime/config.py`.

  This is a `modify_file` operation. The full current content of the file,
  exactly as it exists after all lower-priority atomic steps on this file
  have been applied, is:

  ```python
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
  ```

  Append the following new class to the end of the file, separated from the
  `ScoringSection` class above by exactly two blank lines:

  ```python
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
      scoring: ScoringSection = Field(default_factory=ScoringSection)
      schema_overrides: dict = Field(default_factory=dict)
      export_root: str
  ```

  Requirements, all explicit, no open decisions:

  - `PlanManagerSection` is a class named exactly `PlanManagerSection`,
    inheriting from `BaseModel`. `DatabaseSection`, `EmbeddingSection`, and
    `ScoringSection` are the classes already defined earlier in this same
    file (shown in full above); `Field` is already imported at the top of
    the file. Do not add any new import statements.
  - `model_config = ConfigDict(extra="forbid")` is the first statement in
    the class body after the docstring.
  - Fields, in this exact order, with these exact type annotations and
    defaults:
    - `database: DatabaseSection` (required, no default; references the
      `DatabaseSection` class defined earlier in this file)
    - `embedding: EmbeddingSection = Field(default_factory=EmbeddingSection)`
      (references the `EmbeddingSection` class defined earlier in this
      file)
    - `scoring: ScoringSection = Field(default_factory=ScoringSection)`
      (references the `ScoringSection` class defined earlier in this file)
    - `schema_overrides: dict = Field(default_factory=dict)`
    - `export_root: str` (required, no default)
  - Do not add any validators, methods, or fields beyond what is shown.
  - Do not modify any earlier class (`ConfigError`, `DatabaseSection`,
    `EmbeddingSection`, `ScoringSection`) or the module-level imports in any
    way.
  - After this change, the file ends with the `PlanManagerSection` class
    shown above; no further content follows it in this step.

  MRS excerpt (only the concepts and relation relevant to this step):

  ```yaml
  - concept_id: C-028
    name: Configuration
    definition: Single JSON configuration with adapter sections plus one plan_manager section validated by a Pydantic model.
    properties:
    - fields database, embedding, scoring, schema_overrides, export_root
    - scoring carries published defaults (threshold 85, aggregation minimum, uniform concept weights, definition-only serialization, shared embedding vote, trust floor 0.2)
    - the per-plan context budget is plan data, not a configuration field
    - password only from mounted secrets; invalid config aborts startup
    - no configuration value is ever taken from request parameters
    source_labels: ["{n6a4}", "{c3k8}", "{d8o2}", "{e5m7}", "{b3e6}"]

  - concept_id: C-035
    name: Database
    definition: In-container PostgreSQL with pgvector serving as the single source of truth for all plan data.
    properties:
    - entities as rows; referential integrity at write time
    - every stored entity carries an immutable UUID identity; human-readable ids are scoped names mapped to it
    - hosts the version store, locks, and embedding cache
    - accessed via psycopg 3 with plain SQL; no ORM; runtime code never emits DDL
    source_labels: ["{z8c3}", "{q2r9}", "{z6n1}", "{t6s8}", "{b8j5}", "{x3o9}"]
  ```

  `PlanManagerSection` realizes C-028's fields property in full: `database`
  (typed as `DatabaseSection`, carrying the C-035 connection parameters),
  `embedding`, `scoring`, `schema_overrides`, and `export_root` — exactly
  these five fields and no others, matching "fields database, embedding,
  scoring, schema_overrides, export_root".
verification:
  type: import
  target: plan_manager.runtime.config
  expected: >
    Importing the module plan_manager.runtime.config succeeds. The module
    now defines PlanManagerSection in addition to ConfigError,
    DatabaseSection, EmbeddingSection, and ScoringSection.
    PlanManagerSection(database={"dbname": "p", "user": "u", "host": "h"},
    export_root="/tmp") constructs successfully, with embedding defaulting
    to an EmbeddingSection() instance, scoring defaulting to a
    ScoringSection() instance, and schema_overrides defaulting to an empty
    dict. Omitting database or export_root raises a pydantic
    ValidationError naming the missing field. Passing any additional
    unknown top-level keyword raises a ValidationError due to
    extra="forbid".
```

### A-006-load-raw.yaml

```yaml
step_id: A-006
parent_tactical_step: T-001
name: load-raw
target_file: plan_manager/runtime/config.py
operation: modify_file
priority: 6
depends_on: [A-005]
concepts: [C-028]
status: draft
prompt: |
  Modify the existing Python file at the exact project-relative path
  `plan_manager/runtime/config.py`.

  This is a `modify_file` operation. The full current content of the file,
  exactly as it exists after all lower-priority atomic steps on this file
  have been applied, is:

  ```python
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
      scoring: ScoringSection = Field(default_factory=ScoringSection)
      schema_overrides: dict = Field(default_factory=dict)
      export_root: str
  ```

  Append the following new function to the end of the file, separated from
  the `PlanManagerSection` class above by exactly two blank lines:

  ```python
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
  ```

  Requirements, all explicit, no open decisions:

  - `load_raw` is a module-level function named exactly `load_raw`, taking
    one parameter `path: str`, returning `dict`.
  - It opens `path` with the builtin `open(path, "r", encoding="utf-8")`
    used as a context manager (`with ... as handle:`), then parses its
    contents with `json.load(handle)` (the `json` module is already
    imported at the top of the file; do not add any new import statements),
    assigning the result to a local variable `document`.
  - The `open`/`json.load` call is wrapped in a `try` block. The `except`
    clause catches exactly the tuple `(OSError, json.JSONDecodeError)` as
    `exc`, and raises
    `ConfigError(f"cannot read configuration file {path}: {exc}")` with
    `from exc` (exception chaining). `ConfigError` is the class already
    defined earlier in this same file.
  - After the `try`/`except`, if `document` is not an instance of `dict`
    (checked with `isinstance(document, dict)`), raise
    `ConfigError("configuration root must be a JSON object")`, this exact
    message string.
  - Otherwise, return `document`.
  - Do not add any other statements, helper functions, or logic.
  - Do not modify any earlier class (`ConfigError`, `DatabaseSection`,
    `EmbeddingSection`, `ScoringSection`, `PlanManagerSection`) or the
    module-level imports in any way.
  - After this change, the file ends with the `load_raw` function shown
    above; no further content follows it in this step.

  MRS excerpt (only the concept relevant to this step):

  ```yaml
  - concept_id: C-028
    name: Configuration
    definition: Single JSON configuration with adapter sections plus one plan_manager section validated by a Pydantic model.
    properties:
    - fields database, embedding, scoring, schema_overrides, export_root
    - scoring carries published defaults (threshold 85, aggregation minimum, uniform concept weights, definition-only serialization, shared embedding vote, trust floor 0.2)
    - the per-plan context budget is plan data, not a configuration field
    - password only from mounted secrets; invalid config aborts startup
    - no configuration value is ever taken from request parameters
    source_labels: ["{n6a4}", "{c3k8}", "{d8o2}", "{e5m7}", "{b3e6}"]
  ```

  `load_raw` realizes the "Single JSON configuration" reading step of
  C-028: platform-native dictionary access to the JSON document, and the
  "invalid config aborts startup" property by raising `ConfigError` — the
  typed condition carrying the explicit report — on any read or parse
  failure or non-object root.
verification:
  type: import
  target: plan_manager.runtime.config
  expected: >
    Importing the module plan_manager.runtime.config succeeds. The module
    now defines load_raw in addition to ConfigError, DatabaseSection,
    EmbeddingSection, ScoringSection, and PlanManagerSection. Calling
    load_raw with a path to a file containing the JSON text '{"a": 1}'
    returns the dict {"a": 1}. Calling load_raw with a path to a
    nonexistent file raises ConfigError with a message starting "cannot
    read configuration file". Calling load_raw with a path to a file
    containing invalid JSON text (for example the text "not json") raises
    ConfigError with a message starting "cannot read configuration file".
    Calling load_raw with a path to a file containing the JSON text "[1,
    2]" (a JSON array, not an object) raises ConfigError with the exact
    message "configuration root must be a JSON object".
```

### A-007-load-config.yaml

```yaml
step_id: A-007
parent_tactical_step: T-001
name: load-config
target_file: plan_manager/runtime/config.py
operation: modify_file
priority: 7
depends_on: [A-006]
concepts: [C-028, C-027]
status: draft
prompt: |
  Modify the existing Python file at the exact project-relative path
  `plan_manager/runtime/config.py`.

  This is a `modify_file` operation. The full current content of the file,
  exactly as it exists after all lower-priority atomic steps on this file
  have been applied, is:

  ```python
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
  ```

  Append the following new function to the end of the file, separated from
  the `load_raw` function above by exactly two blank lines:

  ```python
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
  ```

  Requirements, all explicit, no open decisions:

  - `load_config` is a module-level function named exactly `load_config`,
    taking one parameter `path: str`, returning `PlanManagerSection` (the
    class already defined earlier in this same file).
  - First statement: `raw = load_raw(path)`, calling the `load_raw`
    function already defined earlier in this same file. Any `ConfigError`
    raised by `load_raw` propagates unchanged (no `try`/`except` around
    this call).
  - Second statement: `section = raw.get("plan_manager")` — platform-native
    dictionary access (`dict.get`), extracting exactly the top-level key
    `"plan_manager"`.
  - Third: if `section` is not an instance of `dict` (checked with
    `isinstance(section, dict)` — this covers both the key being absent,
    which makes `raw.get` return `None`, and the key being present but not
    a JSON object), raise
    `ConfigError("configuration missing 'plan_manager' section")`, this
    exact message string.
  - Otherwise, wrap `PlanManagerSection.model_validate(section)` in a `try`
    block, `return` its result directly from within the `try`. The `except`
    clause catches exactly `ValidationError` (already imported at the top
    of the file) as `exc`, and raises
    `ConfigError("invalid plan_manager configuration:\n" + str(exc))` with
    `from exc` (exception chaining) — the string concatenation of the fixed
    prefix `"invalid plan_manager configuration:\n"` with `str(exc)`, where
    `\n` is a literal newline character in the string.
  - Do not add any other statements, helper functions, or logic. Do not
    validate or touch any other top-level key of `raw` besides
    `"plan_manager"`; platform-owned sections of the raw dict are never
    validated by this function.
  - Do not modify any earlier class or function (`ConfigError`,
    `DatabaseSection`, `EmbeddingSection`, `ScoringSection`,
    `PlanManagerSection`, `load_raw`) or the module-level imports in any
    way.
  - After this change, the file ends with the `load_config` function shown
    above; this is the final content of the file for this tactical step —
    no further content follows it.

  MRS excerpt (concepts and relation relevant to this step):

  ```yaml
  - concept_id: C-028
    name: Configuration
    definition: Single JSON configuration with adapter sections plus one plan_manager section validated by a Pydantic model.
    properties:
    - fields database, embedding, scoring, schema_overrides, export_root
    - scoring carries published defaults (threshold 85, aggregation minimum, uniform concept weights, definition-only serialization, shared embedding vote, trust floor 0.2)
    - the per-plan context budget is plan data, not a configuration field
    - password only from mounted secrets; invalid config aborts startup
    - no configuration value is ever taken from request parameters
    source_labels: ["{n6a4}", "{c3k8}", "{d8o2}", "{e5m7}", "{b3e6}"]

  - concept_id: C-027
    name: ServerRuntime
    definition: Adapter-owned runtime hosting the command registry, transport, queue, and bootstrap sequence.
    properties:
    - entry point main --config; AppFactory create_app; hypercorn engine
    - adapter owns JSON-RPC, health, commands, heartbeat, OpenAPI surface
    - hook-based registration; auto-import modules for spawned workers
    - long operations use the adapter queue with job semantics
    - implemented in Python 3.12+; production package root plan_manager/ at the repository root, modules as dotted paths beneath it
    source_labels: ["{h9s1}", "{f2x7}", "{g5j8}", "{w7l3}", "{u1p9}", "{y1j5}"]
  ```

  Relation relevant to this step: `{ from_concept: C-027, to_concept: C-028,
  type: consumes }` — the server runtime's bootstrap sequence consumes the
  validated configuration; `load_config` is the function the bootstrap
  calls with the configuration file path (given as context by C-027's "entry
  point main --config" property) to obtain the validated
  `PlanManagerSection` before the application factory runs, aborting startup
  via `ConfigError` on any failure per C-028's "invalid config aborts
  startup" property.
verification:
  type: import
  target: plan_manager.runtime.config
  expected: >
    Importing the module plan_manager.runtime.config succeeds. The module
    now defines load_config in addition to ConfigError, DatabaseSection,
    EmbeddingSection, ScoringSection, PlanManagerSection, and load_raw.
    Calling load_config with a path to a file containing the JSON text
    '{"plan_manager": {"database": {"dbname": "p", "user": "u", "host":
    "h"}, "export_root": "/tmp"}}' returns a PlanManagerSection instance
    whose database.dbname equals "p" and whose scoring and embedding fields
    hold their published defaults. Calling load_config with a path to a
    file containing the JSON text '{"server": {}}' (no "plan_manager" key)
    raises ConfigError with the exact message "configuration missing
    'plan_manager' section". Calling load_config with a path to a file
    containing the JSON text '{"plan_manager": {"database": {"dbname": "p",
    "user": "u"}, "export_root": "/tmp"}}' (database with neither host nor
    socket) raises ConfigError whose message starts with "invalid
    plan_manager configuration:" and contains a report naming the
    violation. Calling load_config with a path to a nonexistent file
    propagates a ConfigError from load_raw with a message starting "cannot
    read configuration file".
```

Notes for spawned A agents:
- Begin by reading `docs/standards/planning/atomic_step_execution_standard.yaml` in full.
- Then read this file, the inherited base context, the G context, the T README, the exact AS file content for the assigned step, and the current target-file state above.
- Edit only `plan_manager/runtime/config.py`.
- If the step cannot proceed because the current target-file state or required context conflicts with the prompt, escalate upward instead of guessing.
