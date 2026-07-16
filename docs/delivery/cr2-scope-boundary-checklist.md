# CR-2 Scope Boundary Checklist

## Server-side additions are exactly two

This change request adds exactly two commands to the plan_manager surface: the export archive command and the export cleanup command, and nothing else. Verification: `tests/test_cr2_scope_boundary_contract.py` asserts both command modules exist and that no push-, deliver- or schedule-shaped command module sits alongside them; a reviewer additionally diffs the live command catalog against the pre-CR-2 baseline and confirms exactly those two names are new.

## The existing export operations are not modified

The export production, byte-serving and inbound-save operations keep their current behaviour byte-for-byte; the archive is served by the shipped byte-serving command with no new transfer machinery. Verification: `git diff` against the pre-CR-2 baseline shows no change to those three command modules, and their existing characterization suites stay green.

## No change to the code-analysis service or the mcp-proxy-adapter

Both surfaces and their clients suffice as already verified. Verification: `git status` and `git diff` in the code-analysis and mcp-proxy-adapter repositories show no change attributable to this change request.

## No reimplementation of the code-analysis client transfer or git functionality

Every write, stage and commit against that service goes through its own client package. Verification: the subprocess-plus-git scan in `tests/test_cr2_scope_boundary_contract.py` passes, and a manual review of the project-path composition confirms every upload, staging and commit call is made through the code-analysis client's own file-session facade and git commands.

## No server-to-server push from plan_manager

Plan_manager never pushes to the code-analysis service; project-path delivery is composed entirely client-side. Verification: the outbound-POST scan in `tests/test_cr2_scope_boundary_contract.py` over the plan_manager package passes.

## No proxy routing inside the client library

Every client connection is direct to its server by design. Verification: `tests/test_cr2_scope_boundary_contract.py` scans every module under `client/` for `call_server(` and finds none, and fails rather than passing vacuously if the client package is absent.

## No batch or scheduled deliveries, and no retrieval of non-export files

A delivery is always one explicit call, and only files inside a plan's own export directory are ever served or delivered. Verification: the scheduler-import scan in `tests/test_cr2_scope_boundary_contract.py` finds no apscheduler, croniter or celery import in either package; and the export-root boundary refusal, enforced by the shared path resolver that keeps every resolved path strictly inside the plan's export directory, is exercised by the archive, cleanup and fetch suites, including the archive-entry escape refusal that leaves nothing behind.
