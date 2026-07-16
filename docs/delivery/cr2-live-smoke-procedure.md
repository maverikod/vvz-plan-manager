# CR-2 Live Smoke Procedure

## Purpose

This is the mandatory post-deployment smoke for CR-2 ("delivery integration"), run after CR-2 ships to production, entirely through the plan-manager MCP proxy transport (server_id `planmgr`), with no other tooling. It proves on a live server that a whole export tree can be delivered and reproduced byte-identically.

## Part 1: The full archive chain, verified per file

Per-file verification is the point: an archive digest alone proves only that the container survived transit, not that each file inside it is the file the server holds.

1. Call `plan_export` on a real plan through the MCP proxy; record the returned file COUNT and revision. Note that no command enumerates the export, which is why the archive exists.

2. Call `export_archive` with only that plan; record the returned `archive` name, `size_bytes`, `sha256` and `file_count`. Confirm `file_count` equals the count `plan_export` reported.

3. Loop `export_read` on the plan with `file` set to the `archive` name returned in step 2, requesting successive chunks until `eof`; reassemble the base64 chunks in order and compute the sha256 of the reassembled bytes. Confirm it equals the `sha256` the archive command declared. This is the archive-level check and it MUST pass before step 4.

4. Only after step 3 passes, unpack the reassembled archive locally. Record every unpacked file's relative path; confirm the number of unpacked files equals `file_count`, and confirm the tree shape is reproduced (`source_spec.md` and `spec.yaml` at the top; `G-NNN-<slug>/README.yaml`; `T-NNN-<slug>/README.yaml`; `atomic_steps/A-NNN-<slug>.yaml`), with files sharing a bare name across directories present as distinct files.

5. For EVERY unpacked file, compute its sha256, then call `export_read` a SECOND time directly against that same file by its export-root-relative path and compare the digest the server declares for it against the digest of the unpacked copy. Record pass/fail per file. Part 1 passes only when every file matches; a single mismatch fails the smoke.

## Part 2: export_cleanup dry run and real run on a throwaway export

1. Produce a throwaway export for a disposable plan and archive it, so the directory contains an archive alongside the tree.

2. Call `export_cleanup` with that plan and a `changed_by` identity, relying on the `dry_run` default; record the reported classified directories, their file manifests (confirming the archive is listed like any other file) and byte counts. Confirm nothing was removed by re-reading a file of that export via `export_read`.

3. Soft-delete the disposable plan, then call `export_cleanup` again for it with `dry_run=false` and a `changed_by`; confirm the reported directories and files are now gone.

4. Confirm an audit record exists for BOTH the dry run and the real run, each carrying the `changed_by` identity.

## Part 3: one real project-path delivery with commit-hash verification (conditional)

When a code-analysis test project is available, perform one real project-path delivery for a plan bound to that project, record the returned commit hash, and verify that commit exists in the target project's git history with each committed file's content matching the digest recorded for its relative path in the deterministic commit message. When no code-analysis test project is available, record this part as SKIPPED with that reason — the smoke as a whole remains mandatory per the standing cycle order.

## Completion

The procedure is complete when Part 1 shows the archive digest matching AND every unpacked file's digest matching a second direct read, Part 2 shows a truthful dry-run preview followed by a real removal with both runs audited, and Part 3 is either passed with a verified commit hash or explicitly recorded as skipped with its reason.
