# NAME

planmgr — plan_manager deployment

# SYNOPSIS

    systemctl start planmgr
    systemctl stop planmgr
    systemctl restart planmgr
    systemctl status planmgr

Configuration paths:

    /etc/default/planmgr           operator environment variables (conffile)
    /etc/planmgr/config.json       rendered server configuration
    /etc/planmgr/config.json.template   configuration template (conffile)
    /etc/planmgr/secrets/           mounted secrets, including the database password

# DESCRIPTION

planmgr is the plan_manager server: a single container process that stores
development plans as a five-level hierarchy — source specification, machine
specification, global steps, tactical steps, and atomic steps — inside an
embedded PostgreSQL database, and exposes that hierarchy through a JSON-RPC
command surface.

Plan storage. Every plan artifact is a versioned row in the database; no
plan data is ever written into the container image or to a flat file outside
the three fixed host mounts. Each mutation produces a new append-only
revision, so any past state of a plan remains addressable by revision id.

Verification gate. Before any semantic measurement runs, a deterministic
mechanical gate checks parsing, identifier uniqueness, cross-references, and
coverage for the affected branch of the plan tree. The gate produces
byte-identical findings for the same tree state and blocks semantic scoring
until unresolved mechanical defects are fixed.

Semantic scoring. Once a branch passes the mechanical gate, a semantic
completeness index in the 0-100 range is computed from an ensemble of
independent estimators and reported together with a trust estimate that
reflects how reliable the measurement itself is, given the state of the
concept basis and the embedding service.

Cascade transactions. Machine-specification-level changes are proposed as a
single transactional cascade anchored at the plan head revision. The cascade
holds the per-plan lock while open, and the head revision advances only when
the verification gate is green for the whole change set, with automatic
invalidation propagation to every affected step.

Exchange format. A plan can be exported to, and imported from, a directory
tree that mirrors the plan hierarchy — the source specification as Markdown
and every other level as YAML. Import is the only path from files back into
the stored truth; export may target a named revision.

# INSTALLATION

planmgr installs from the Ubuntu package produced by the release pipeline:

    apt install ./planmgr_<version>_all.deb

The package installs the systemd unit, configuration templates, operator
documentation, and service lifecycle scripts. The first deployment bootstrap is
performed by the package initialization step described below.

# INITIALIZATION

The package's postinst script initializes the deployment during install:

  1. creates the planmgruser system user and the planmgrgrp system group if
     they do not already exist;
  2. creates /etc/planmgr, /var/planmgr, and /var/log/planmgr with ownership
     planmgruser:planmgrgrp and restrictive modes;
  3. installs /etc/default/planmgr and /etc/planmgr/config.json.template as
     conffiles — an existing, locally modified file triggers the standard
     dpkg overwrite prompt instead of being silently replaced;
  4. reads the operator settings from /etc/default/planmgr, verifies that
     the configured image version is present on Docker Hub and pulls it if
     it is not present locally, and renders /etc/planmgr/config.json from
     those settings;
  5. registers and starts the planmgr systemd service.

# CONFIGURATION

/etc/default/planmgr is a systemd EnvironmentFile (shell-style KEY=value
lines) with these operator variables:

| Variable | Meaning |
| --- | --- |
| PLANMGR_IMAGE_REPO | Docker Hub repository, e.g. vasilyvz/planmgr |
| PLANMGR_IMAGE_VERSION | Image tag to run; equals the package version at install time |
| PLANMGR_PORT | Published host port for the service |
| PLANMGR_ADVERTISED_HOST | Host name or address advertised to the platform proxy |
| PLANMGR_REGISTRATION_ENABLED | true/false — whether the service registers with the proxy |
| PLANMGR_DB_NAME | PostgreSQL database name |
| PLANMGR_DB_USER | PostgreSQL role name |
| PLANMGR_DB_PASSWORD_FILE | Path under /etc/planmgr/secrets to the mounted database password file |
| PLANMGR_EMBEDDING_URL | Optional embedding service base URL used by semantic scoring; empty disables embedding-backed estimators |
| PLANMGR_EMBEDDING_TIMEOUT | Embedding client timeout in seconds |

For example, enable the embedding service on the local deployment network with:

    PLANMGR_EMBEDDING_URL=https://192.168.254.26:8001
    PLANMGR_EMBEDDING_TIMEOUT=60.0

/etc/planmgr/config.json is rendered from config.json.template at install
time and holds the adapter sections plus one plan_manager section validated
by a Pydantic model:

  - adapter sections carry the transport, logging, and other adapter-owned
    runtime settings consumed directly by the server process;
  - plan_manager.database holds the connection parameters for the
    in-container PostgreSQL instance;
  - plan_manager.embedding holds the URL of the optional embedding service
    used for semantic scoring;
  - plan_manager.scoring carries the published defaults: threshold 85,
    aggregation minimum (a plan's score is the minimum of its branch
    scores), uniform concept weights, definition-only concept serialization
    for embeddings, a shared embedding vote, and a trust floor of 0.2 when
    the embedding service is unavailable;
  - plan_manager.schema_overrides holds per-plan identifier-pattern and
    required-field overrides; empty unless a plan uses a non-default
    layout;
  - plan_manager.export_root names the host directory under which
    exchange-format exports and imports are read and written.

The database password is never written into config.json; it is read only
from the mounted secrets file named by PLANMGR_DB_PASSWORD_FILE. An invalid
configuration aborts server startup before any command is served.

# OPERATION

Start, stop, and restart are systemd operations:

    systemctl start planmgr
    systemctl stop planmgr
    systemctl restart planmgr

Readiness and liveness are both reported by the /health endpoint, polled by
both the container healthcheck and the systemd service supervision. The
health command reports overall status as error when the required PostgreSQL
database is unreachable and ok otherwise, and additionally reports the
availability of the optional embedding service for observability without
letting it change the overall status.

Logs are written under /var/log/planmgr, mounted read-write from the host;
the service wrapper's own output is additionally visible through
journalctl -u planmgr.

Data — the PostgreSQL data directory, the plan tables, the version store,
and the embedding cache — lives entirely under /var/planmgr, mounted
read-write. No plan data is ever stored inside the container image or on a
non-mounted path.

Upgrade: edit PLANMGR_IMAGE_VERSION in /etc/default/planmgr to the new
version, then run apt upgrade to install the new package; the service
restarts on the new image with the same three host mounts, so plan data
survives the upgrade unchanged.

Backup: back up the /var/planmgr mount (which includes the PostgreSQL data
directory) while the service is stopped, or with a PostgreSQL-consistent
snapshot mechanism if the service must stay up; back up /etc/planmgr
alongside it for configuration continuity.

# COMMAND SURFACE

The server exposes 60 domain commands over JSON-RPC, grouped into thirteen
families, alongside the platform introspection commands info and health.
The mutating subset within each family requires either an explicit open
cascade (for machine-specification-level changes) or draft status on the
target artifact (for global-step, tactical-step, and atomic-step-level
changes); no mutation bypasses both. Per-command parameters, return values,
usage examples, and stable domain error codes are available at runtime from
the info command (info section=capabilities) and the platform help command,
so this overview never diverges from per-command detail.

  plan                — catalog (showing each plan's bound projects), create, status, soft/hard delete, and project bindings (9 commands).
  exchange            — export a plan at a revision, snapshot live working state, import a plan from files as the sole file-to-truth path, promote completed uploads into export_root, and import/export the human requirement specification (6 commands).
  paragraph           — list, get, assign a label, toggle non-binding markup on requirement paragraphs (4 commands).
  mrs                 — list/get/add/update/delete concepts and list/add/delete relations; every mutation runs inside a cascade (8 commands).
  coverage            — concept coverage report (1 command).
  step                — create, get, tree, update, move, delete, set status, lifecycle transition, and runtime get/report/list, uniform across levels 3-5 (11 commands).
  graph               — dependency edges, execution order, parallel execution waves, and impact report (4 commands).
  prompt              — assemble a branch execution prompt and the whole-plan prompt chain (2 commands).
  context             — compile, common, specific, and bundle context blocks, plus block get/list (6 commands).
  branch              — branch dump view and branch weak-point report (2 commands).
  validation/scoring  — mechanical gate run and semantic index score (2 commands).
  cascade             — begin, preview, commit, abort (4 commands).
  info                — self-description: identity, build metadata, runtime summary, capabilities, planning standards glossary, embedded operator documentation (1 command).

The platform health command is overridden so that, alongside process and
platform liveness, it reports the availability of the services the server
depends on: the required PostgreSQL database and the optional embedding
service, under components.services. Its overall status is error when the
required database is unreachable and ok otherwise; the optional embedding
service is reported for observability and never changes the overall status.

# FILES

  /etc/planmgr/config.json             rendered server configuration (read-only mount)
  /etc/planmgr/config.json.template    conffile template installed by the package
  /etc/planmgr/secrets/                mounted secrets, including the database password file
  /etc/default/planmgr                 operator environment variables, conffile
  /var/planmgr/                        data, including the PostgreSQL data directory (read-write mount)
  /var/log/planmgr/                    logs (read-write mount)
  /lib/systemd/system/planmgr.service  systemd unit
  /usr/share/man/man1/planmgr.1.gz     man page, rendered from this document
  /usr/share/info/planmgr.info.gz      GNU info document, rendered from this document

# SEE ALSO

systemctl(1), journalctl(1), docker(1), dpkg(1)
