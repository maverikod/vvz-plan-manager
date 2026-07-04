"""On-demand object/work-axis inventory view for the plan tree
(CoverageView, C-010).

The inventory in this module is derived from the object declarations of
atomic steps; it is never stored as a file and is recomputed from the
step table at query time.
"""

import uuid

import psycopg


def module_of(target_file: str) -> str:
    """Derive the classification module of an object from its declaring file.

    Normative module rule: split `target_file` on "/"; within the final
    path segment only, if it contains a ".", strip the extension by
    keeping the part before the last "." (`rsplit(".", 1)` applied to
    that final segment only); a final segment without a "." is kept
    whole; join all segments - with the final segment as computed above
    - using "." in place of "/". Example: target file "a/b/c.py" yields
    module "a.b.c". The resulting module is a classification key: it
    carries no UUID and is never used as an identity.

    Args:
        target_file: Project-relative path to a code file, e.g.
            "plan_manager/views/coverage.py".

    Returns:
        The dotted module string derived from `target_file` per the
        rule above.
    """
    parts = target_file.split("/")
    last_segment = parts[-1]
    if "." in last_segment:
        last_segment = last_segment.rsplit(".", 1)[0]
    parts[-1] = last_segment
    return ".".join(parts)


def object_inventory(conn: psycopg.Connection, plan_uuid: uuid.UUID) -> dict[str, dict]:
    """Build the object/work-axis inventory for the plan (CoverageView, C-010).

    Reads every level-5 step of the plan together with its level-4
    parent and that parent's level-3 parent, to compute each level-5
    step's tactical step path "<GS step_id>/<TS step_id>" and full
    artifact path "<GS step_id>/<TS step_id>/<AS step_id>". For every
    entry in each level-5 step's `fields.get("objects", [])` list -
    each entry a dict with keys "name" (str) and "concepts"
    (list[str]) - accumulates, per distinct object `name`, the owner
    keys, artifact paths, and concept sets contributed by every
    declaring level-5 step.

    Args:
        conn: Open psycopg 3 database connection to use for the query.
        plan_uuid: Identity of the plan to build the inventory for.

    Returns:
        Dict keyed by object name. Each value is a dict with keys:
            "owner_keys": sorted list of [module, tactical_step_path]
                two-element lists, deduplicated, where
                tactical_step_path is "<GS step_id>/<TS step_id>" and
                module is module_of(target_file) of the declaring
                level-5 step's fields["target_file"].
            "modules": sorted list of the distinct modules among this
                object's owner_keys.
            "artifact_paths": sorted list of the distinct full artifact
                paths "<GS step_id>/<TS step_id>/<AS step_id>" of every
                level-5 step that declares this object.
            "declared_concepts": sorted list of the union of the
                "concepts" list of every declaration entry for this
                object name.
            "as_concepts": sorted list of the union of the `concepts`
                column (text[]) of every level-5 step that declares
                this object.
        An object name absent from every level-5 step's
        fields["objects"] never appears as a key.
    """
    gs_cur = conn.execute(
        "SELECT uuid, step_id FROM step WHERE plan_uuid = %s AND level = 3",
        (plan_uuid,),
    )
    gs_step_id_by_uuid: dict[uuid.UUID, str] = {row[0]: row[1] for row in gs_cur.fetchall()}

    ts_cur = conn.execute(
        "SELECT uuid, parent_step_uuid, step_id FROM step "
        "WHERE plan_uuid = %s AND level = 4",
        (plan_uuid,),
    )
    ts_path_by_uuid: dict[uuid.UUID, str] = {}
    for ts_uuid, ts_parent_uuid, ts_step_id in ts_cur.fetchall():
        gs_step_id = gs_step_id_by_uuid[ts_parent_uuid]
        ts_path_by_uuid[ts_uuid] = f"{gs_step_id}/{ts_step_id}"

    as_cur = conn.execute(
        "SELECT parent_step_uuid, step_id, fields, concepts FROM step "
        "WHERE plan_uuid = %s AND level = 5",
        (plan_uuid,),
    )

    accum: dict[str, dict[str, set]] = {}
    for as_parent_uuid, as_step_id, as_fields, as_concepts in as_cur.fetchall():
        ts_path = ts_path_by_uuid[as_parent_uuid]
        artifact_path = f"{ts_path}/{as_step_id}"
        target_file = (as_fields or {}).get("target_file")
        module = module_of(target_file) if target_file else ""
        declaring_concepts = set(as_concepts) if as_concepts is not None else set()
        declarations = (as_fields or {}).get("objects", [])
        for declaration in declarations:
            name = declaration["name"]
            bucket = accum.setdefault(
                name,
                {
                    "owner_keys": set(),
                    "artifact_paths": set(),
                    "declared_concepts": set(),
                    "as_concepts": set(),
                },
            )
            bucket["owner_keys"].add((module, ts_path))
            bucket["artifact_paths"].add(artifact_path)
            bucket["declared_concepts"].update(declaration.get("concepts", []))
            bucket["as_concepts"].update(declaring_concepts)

    inventory: dict[str, dict] = {}
    for name, bucket in accum.items():
        inventory[name] = {
            "owner_keys": sorted(list(pair) for pair in bucket["owner_keys"]),
            "modules": sorted({module for module, _ in bucket["owner_keys"]}),
            "artifact_paths": sorted(bucket["artifact_paths"]),
            "declared_concepts": sorted(bucket["declared_concepts"]),
            "as_concepts": sorted(bucket["as_concepts"]),
        }
    return inventory


def object_findings(inventory: dict[str, dict]) -> list[dict]:
    """Compute object inventory findings (CoverageView, C-010).

    For every object name in `inventory`, taken in ascending sorted
    order, emits zero or more findings from three checks, evaluated in
    this order per object: multiple_owner_keys, multiple_modules,
    concepts_not_covered.

    Args:
        inventory: The dict returned by object_inventory(conn,
            plan_uuid): keyed by object name, each value a dict with
            keys "owner_keys" (list of [module, tactical_step_path]
            pairs), "modules" (list of distinct modules),
            "artifact_paths" (list of full artifact paths),
            "declared_concepts" (list of concept ids declared for the
            object), "as_concepts" (list of concept ids of the
            declaring atomic steps).

    Returns:
        List of finding dicts, each with keys:
            "object": the object name.
            "check": one of "multiple_owner_keys", "multiple_modules",
                "concepts_not_covered".
            "artifact_paths": the object's "artifact_paths" list from
                `inventory`, unchanged.
            "detail": prose naming the offending elements.
        A "multiple_owner_keys" finding is emitted when
        len(inventory[name]["owner_keys"]) > 1, naming every owner
        key. A "multiple_modules" finding is emitted when
        len(inventory[name]["modules"]) > 1, naming every module. A
        "concepts_not_covered" finding is emitted when
        inventory[name]["declared_concepts"] is not a subset of
        inventory[name]["as_concepts"], naming every concept id
        present in "declared_concepts" but absent from "as_concepts".
        Findings are classified by the object's full artifact paths,
        never by a bare step number. An object triggering none of the
        three conditions emits no finding.
    """
    findings: list[dict] = []
    for name in sorted(inventory.keys()):
        entry = inventory[name]
        owner_keys = entry["owner_keys"]
        modules = entry["modules"]
        artifact_paths = entry["artifact_paths"]
        declared_concepts = entry["declared_concepts"]
        as_concepts = entry["as_concepts"]

        if len(owner_keys) > 1:
            owner_key_text = ", ".join(f"({m}, {t})" for m, t in owner_keys)
            findings.append(
                {
                    "object": name,
                    "check": "multiple_owner_keys",
                    "artifact_paths": artifact_paths,
                    "detail": (
                        f"Object '{name}' has multiple owner keys: "
                        f"{owner_key_text}."
                    ),
                }
            )

        if len(modules) > 1:
            findings.append(
                {
                    "object": name,
                    "check": "multiple_modules",
                    "artifact_paths": artifact_paths,
                    "detail": (
                        f"Object '{name}' spans multiple modules: "
                        f"{', '.join(modules)}."
                    ),
                }
            )

        uncovered = sorted(set(declared_concepts) - set(as_concepts))
        if uncovered:
            findings.append(
                {
                    "object": name,
                    "check": "concepts_not_covered",
                    "artifact_paths": artifact_paths,
                    "detail": (
                        f"Object '{name}' declares concepts not covered "
                        f"by its declaring atomic steps: "
                        f"{', '.join(uncovered)}."
                    ),
                }
            )
    return findings

