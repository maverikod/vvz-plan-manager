"""On-demand coverage views for the plan tree (CoverageView, C-010).

Coverage is never stored as a matrix file: every report in this module
is computed from the current state of the step, concept, relation, and
paragraph tables at query time, and no derived artifact is ever read
back as input to a check.
"""

import uuid
from dataclasses import dataclass

import psycopg


@dataclass
class CoverageReport:
    """Result of one coverage set comparison (CoverageView, C-010).

    Attributes:
        missing: Sorted ascending list of element identifiers required
            by one side of the comparison but not found on the other
            side. Always a list, never a bare boolean; empty when
            nothing is missing.
        extra: Sorted ascending list of element identifiers found but
            not required. Always a list, never a bare boolean; empty
            when nothing is extra.
    """

    missing: list[str]
    extra: list[str]


def concept_coverage(conn: psycopg.Connection, plan_uuid: uuid.UUID) -> CoverageReport:
    """Compute plan-level concept coverage (CoverageView, C-010).

    Compares the union of the `concepts` column (text[]) of every
    level-3 step of the plan against the set of `concept_id` values in
    the `concept` table for the same plan, for set equality.

    Args:
        conn: Open psycopg 3 database connection to use for the query.
        plan_uuid: Identity of the plan to compute coverage for.

    Returns:
        CoverageReport whose `missing` list holds `concept_id` values
        from the `concept` table not present in the union of
        `concepts` across all level-3 steps of the plan, and whose
        `extra` list holds `concepts` entries from level-3 steps not
        present as a `concept_id` in the `concept` table. Both lists
        are sorted ascending. Set equality holds iff both lists are
        empty.
    """
    gs_cur = conn.execute(
        "SELECT concepts FROM step WHERE plan_uuid = %s AND level = 3",
        (plan_uuid,),
    )
    gs_concepts: set[str] = set()
    for row in gs_cur.fetchall():
        if row[0] is not None:
            gs_concepts.update(row[0])
    concept_cur = conn.execute(
        "SELECT concept_id FROM concept WHERE plan_uuid = %s",
        (plan_uuid,),
    )
    mrs_concept_ids: set[str] = {row[0] for row in concept_cur.fetchall()}
    return CoverageReport(
        missing=sorted(mrs_concept_ids - gs_concepts),
        extra=sorted(gs_concepts - mrs_concept_ids),
    )


def gs_coverage(conn: psycopg.Connection, plan_uuid: uuid.UUID) -> dict[str, CoverageReport]:
    """Compute per-GS concept coverage (CoverageView, C-010).

    For every level-3 step of the plan, compares that step's own
    `concepts` column against the union of the `concepts` columns of
    its level-4 children (rows whose `parent_step_uuid` equals the
    level-3 step's `uuid`).

    Args:
        conn: Open psycopg 3 database connection to use for the query.
        plan_uuid: Identity of the plan to compute coverage for.

    Returns:
        Dict keyed by each level-3 step's `step_id`. Each value is a
        CoverageReport whose `missing` list holds entries of that
        step's own `concepts` column not present in the union of the
        `concepts` columns of its level-4 children, sorted ascending,
        and whose `extra` list is always `[]` (the formula is a
        superset requirement only; concepts present on a level-4 child
        but absent from the level-3 step's own concepts are never a
        finding).
    """
    gs_cur = conn.execute(
        "SELECT uuid, step_id, concepts FROM step WHERE plan_uuid = %s AND level = 3",
        (plan_uuid,),
    )
    gs_rows = gs_cur.fetchall()
    ts_cur = conn.execute(
        "SELECT parent_step_uuid, concepts FROM step WHERE plan_uuid = %s AND level = 4",
        (plan_uuid,),
    )
    ts_rows = ts_cur.fetchall()

    children_concepts: dict[uuid.UUID, set[str]] = {}
    for parent_step_uuid, ts_concepts in ts_rows:
        bucket = children_concepts.setdefault(parent_step_uuid, set())
        if ts_concepts is not None:
            bucket.update(ts_concepts)

    result: dict[str, CoverageReport] = {}
    for gs_uuid, gs_step_id, gs_concepts in gs_rows:
        own = set(gs_concepts) if gs_concepts is not None else set()
        children = children_concepts.get(gs_uuid, set())
        result[gs_step_id] = CoverageReport(missing=sorted(own - children), extra=[])
    return result


def label_coverage(conn: psycopg.Connection, plan_uuid: uuid.UUID) -> CoverageReport:
    """Compute plan-level label coverage (CoverageView, C-010).

    Compares the union of the `fields["source_labels"]` list (strings
    with braces, e.g. "{k2p7}") of every level-3 step of the plan
    against the set formed by wrapping every `paragraph.label` value of
    the plan (four base36 characters, stored without braces; only
    binding paragraphs are stored as rows) in braces, for set equality.

    Args:
        conn: Open psycopg 3 database connection to use for the query.
        plan_uuid: Identity of the plan to compute coverage for.

    Returns:
        CoverageReport whose `missing` list holds braced paragraph
        labels (`"{" + label + "}"`) claimed by no level-3 step's
        `fields["source_labels"]`, and whose `extra` list holds braced
        labels present in some level-3 step's `fields["source_labels"]`
        with no matching `paragraph` row. Both lists are sorted
        ascending. Set equality holds iff both lists are empty.
    """
    gs_cur = conn.execute(
        "SELECT fields FROM step WHERE plan_uuid = %s AND level = 3",
        (plan_uuid,),
    )
    gs_labels: set[str] = set()
    for row in gs_cur.fetchall():
        fields = row[0]
        if fields:
            gs_labels.update(fields.get("source_labels", []))
    paragraph_cur = conn.execute(
        "SELECT label FROM paragraph WHERE plan_uuid = %s",
        (plan_uuid,),
    )
    hrs_labels: set[str] = {"{" + row[0] + "}" for row in paragraph_cur.fetchall()}
    return CoverageReport(
        missing=sorted(hrs_labels - gs_labels),
        extra=sorted(gs_labels - hrs_labels),
    )


def relation_coverage(conn: psycopg.Connection, plan_uuid: uuid.UUID) -> CoverageReport:
    """Compute plan-level relation coverage (CoverageView, C-010).

    Compares the union, over every level-3 step of the plan, of
    `fields.get("relations", [])` entries -- each entry a dict with keys
    "from_concept", "to_concept", "type", rendered as the string
    "from_concept|to_concept|type" -- against the rows of the
    `relation` table for the plan, each rendered the same way from its
    `from_concept`, `to_concept`, `type` columns, for set equality.

    Args:
        conn: Open psycopg 3 database connection to use for the query.
        plan_uuid: Identity of the plan to compute coverage for.

    Returns:
        CoverageReport whose `missing` list holds "from|to|type"
        strings present as `relation` table rows but implemented by no
        level-3 step's `fields["relations"]`, and whose `extra` list
        holds "from|to|type" strings present in some level-3 step's
        `fields["relations"]` with no matching `relation` table row.
        Both lists are sorted ascending. Set equality holds iff both
        lists are empty.
    """
    gs_cur = conn.execute(
        "SELECT fields FROM step WHERE plan_uuid = %s AND level = 3",
        (plan_uuid,),
    )
    gs_relations: set[str] = set()
    for row in gs_cur.fetchall():
        fields = row[0]
        if fields:
            relations = fields.get("relations", [])
            if not isinstance(relations, list):
                gs_relations.add("INVALID_RELATION_SHAPE")
                continue
            for entry in relations:
                if not isinstance(entry, dict) or not {
                    "from_concept",
                    "to_concept",
                    "type",
                } <= set(entry):
                    gs_relations.add("INVALID_RELATION_SHAPE")
                    continue
                gs_relations.add(
                    f"{entry['from_concept']}|{entry['to_concept']}|{entry['type']}"
                )
    relation_cur = conn.execute(
        "SELECT from_concept, to_concept, type FROM relation WHERE plan_uuid = %s",
        (plan_uuid,),
    )
    mrs_relations: set[str] = {
        f"{row[0]}|{row[1]}|{row[2]}" for row in relation_cur.fetchall()
    }
    return CoverageReport(
        missing=sorted(mrs_relations - gs_relations),
        extra=sorted(gs_relations - mrs_relations),
    )
