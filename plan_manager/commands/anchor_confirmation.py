"""Shared live analysis-server anchor confirmation for bug/todo project and file
anchors (bug 5926d536).

``bug_create``, ``bug_reanchor``, ``todo_create``, and ``todo_reanchor`` all
route their candidate project/file anchor through :func:`confirm_anchor`
before persisting it, so a typo'd or since-deleted analysis-server project id
can never be silently attached as a live-looking anchor -- previously
``validate_uuid``/``validate_file_reference`` checked only shape, never
existence (see ``plan_manager.commands.info_reference``'s historical "planmgr
does not verify analysis-server project existence" note, now closed by this
module). Lives in ``commands`` rather than ``domain`` because it depends on
the runtime CA transport and ``AppConfig``, which no ``domain`` module
imports.

Confirmation failure (CA unreachable/unconfigured, or a clean not-found
response) never blocks the create/reanchor: the caller downgrades the
candidate anchor to unanchored (``BugSource(source_type="unidentified")`` /
``PrimaryAnchor(anchor_type="none")``) and reports why via the returned
:class:`AnchorConfirmation`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Callable

from plan_manager.runtime.ca_client import confirm_project_anchor
from plan_manager.runtime.context import AppConfig

# The only BugSource/PrimaryAnchor kinds that carry a project_id and are
# therefore subject to live CA confirmation; every other kind (plan, step,
# command, runtime_service, execution_attempt, review_result, bug, bug_fix,
# todo, none/unidentified) bypasses CA entirely -- it never carries a
# project_id in the first place.
PROJECT_CARRYING_ANCHOR_TYPES: frozenset[str] = frozenset({"project", "file"})


@dataclass(frozen=True)
class AnchorConfirmation:
    """Outcome of a :func:`confirm_anchor` call.

    ``applicable`` is False when the requested type is not project/file (CA
    is never consulted; ``confirmed`` is trivially True and ``reason`` is
    None). When ``applicable`` is True, ``confirmed``/``reason`` come
    straight from the CA transport check (``reason`` is None when confirmed,
    else "ca_unreachable" or "not_found").
    """

    applicable: bool
    confirmed: bool
    reason: str | None

    def to_payload(self, requested_type: str) -> dict[str, object]:
        """Render this outcome as the command-result diagnostic dict.

        Only meaningful when ``applicable`` is True; callers only attach
        this to a command result when that is the case.
        """
        return {
            "requested_type": requested_type,
            "confirmed": self.confirmed,
            "reason": self.reason,
        }


def confirm_anchor(
    app_config_provider: Callable[[], AppConfig],
    *,
    requested_type: str,
    project_id: uuid.UUID | None,
    file_path: str | None,
) -> AnchorConfirmation:
    """Confirm a candidate project/file anchor against the live CA server.

    No-ops (``applicable=False, confirmed=True, reason=None``) for every
    anchor/source kind other than ``"project"``/``"file"``, and for a
    project/file request that is missing its required ``project_id`` --
    that shape defect is the concern of the existing domain validators
    (``validate_anchor`` / ``validate_bug_source``), not of CA confirmation.
    ``app_config_provider`` (typically ``plan_manager.runtime.context.
    app_config`` itself) is called ONLY on that non-no-op path, so a request
    carrying no project/file anchor never requires the runtime to be
    initialized.

    For ``"project"``/``"file"`` requests with a ``project_id``, delegates
    to ``plan_manager.runtime.ca_client.confirm_project_anchor`` using the
    operator-configured CA url/timeout/mTLS material from
    ``app_config_provider()``. ``file_path`` is only forwarded to the CA
    file check when ``requested_type == "file"`` (a "project"-type anchor
    never carries a file to confirm, even if a stray ``file_path`` was
    supplied alongside it).
    """
    if requested_type not in PROJECT_CARRYING_ANCHOR_TYPES or project_id is None:
        return AnchorConfirmation(applicable=False, confirmed=True, reason=None)
    app_cfg = app_config_provider()
    outcome = confirm_project_anchor(
        ca_url=app_cfg.code_analysis_url,
        project_id=project_id,
        file_path=file_path if requested_type == "file" else None,
        timeout=app_cfg.code_analysis_timeout,
        cert=app_cfg.code_analysis_cert,
        key=app_cfg.code_analysis_key,
        ca=app_cfg.code_analysis_ca,
    )
    return AnchorConfirmation(applicable=True, confirmed=outcome.confirmed, reason=outcome.reason)
