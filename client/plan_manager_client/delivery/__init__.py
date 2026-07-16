"""Delivery module boundary for the plan_manager client library.

Author: Vasiliy Zdanovskiy
email: vasilyvz@gmail.com

This sub-package establishes the two-path delivery model (C-001) structurally: the module boundary where Path A (a code-analysis project specified; delivered by a later G-005 branch) and Path B (no project specified; delivered by a later G-004 branch) each add their own composition module, both consuming the plan_manager_client facade (client/plan_manager_client/client.py) and, for Path A, the code-analysis-client dependency. This package intentionally defines no dataclasses, function signatures, or interface contracts here: those are the design decisions of the G-004 and G-005 branches that will populate this sub-package, per the L1 ruling (decision comment 10eba9c2 resolving escalation 4f4a04bb) that this branch (G-003) must make the module boundary explicit without pre-empting their design.
"""
