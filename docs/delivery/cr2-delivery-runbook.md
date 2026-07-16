# CR-2 Delivery Runbook: Consuming Project-Path Results From Git

## Purpose

This document tells an external code-analysis project's maintainer how to find and verify a plan_manager export that was delivered into their project by the plan_manager client library's project-path delivery.

## Preconditions for a project-path delivery

Every code-analysis project root carries a `projectid` file and the code-analysis service reports exactly that UUID as its project id, so a plan's bound primary project IS the code-analysis project and no mapping step exists. The delivery is refused when the plan has no bound project and no explicit override is supplied.

## What lands: a tree, not a bundle

The delivery writes the export tree into the project's documentation area as its own subdirectory, under a destination subdirectory that is a caller-supplied parameter with a sane default named after the plan. Every file keeps its original name and its relative position: `source_spec.md` and `spec.yaml` at the top of the delivered subtree, `G-NNN-<slug>/README.yaml` per global step, `T-NNN-<slug>/README.yaml` beneath its global step, and `atomic_steps/A-NNN-<slug>.yaml` beneath its tactical step. Names such as `README.yaml` repeat across directories, so entries are addressed by their full relative path and nothing is ever flattened to a bare name. Destination paths are project-relative POSIX paths and traversal is refused.

## How the delivery is committed

After the writes, the client library issues an explicit staging of the written paths and an explicit commit through the code-analysis service's own client, never relying on that service's commit-on-write configuration setting (which defaults to false); explicit staging and commit work regardless of its state.

## Verifying a delivery by its commit hash

The commit message is deterministic, carrying the plan name, the export revision uuid, and one `sha256` line per delivered entry keyed by that entry's export-root-relative path (not its bare name, which would collide), sorted by that path so a retried delivery produces a byte-identical message and is recognisable in the project's git log. The returned commit hash is the delivery's receipt: locate it in the project's own git history and confirm each committed file's sha256 matches the digest recorded for its relative path in the commit message.

## Where the delivery is recorded on the planner side

Each success is recorded in the exported plan's runtime overlay as an execution-note comment with public-summary visibility, carrying the export revision, the target project and subdirectory, the per-entry digest set and the returned commit hash, so what-was-delivered-where stays queryable from the planner without git access.

## Failure atomicity

A delivery that fails partway reports exactly which files were written and whether a commit was made, and never half-commits silently. The report distinguishes the stage at which it aborted — archive verification, a refused archive entry, per-entry digest verification, upload, or commit — and an abort at archive verification or on a refused entry means nothing was uploaded at all. That partial-write report is the operator's precise remediation surface for a retry.
