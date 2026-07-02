# Plan Completeness Instrument — Design Approach

**Status:** design specification (no implementation yet)
**Author:** Vasiliy Zdanovskiy / assistant
**Scope:** a project-agnostic instrument that scores how completely a development
plan (the five-level `HRS -> MRS -> GS -> TS -> AS` hierarchy of
`plan_standard_machine.yaml`) realizes its source specification. Replaces the
ad-hoc `tools/plan_audit.py` / `plan_validate.py` / `plan_locate.py` family with
a single, decoupled, numerically-scored tool.

---

## 1. Purpose and the problem it solves

A development plan is correct when **every branch `HRS -> AS` is a self-sufficient
task**: an executor reading one branch top-to-bottom has everything needed to act,
with no reference sideways to sibling branches. The standards already define this
(consistency `c7`, tactical `t7`/`t8`, atomic `a4`). What is missing is a way to
**measure** it at scale, because manual verification collapses: intermediate
results get evicted from context across ~50 concepts and a hundred objects.

The prior tool family (`plan_audit`, `plan_validate`) materialized that knowledge
into side-car **matrix files** (`concept_atomic_matrix.yaml`, `object_matrix.yaml`,
`t_concept_matrix.yaml`) and checked the tree against them. This created a second
source of truth that drifts from the tree, and the two tools diverged onto
different matrix schemas. Matrices are a workaround for a context limit, not part
of the method. **This instrument removes them entirely.**

The instrument must obey one usability law: **a human runs an instrument, reads
one number, and decides hit / miss.** Replacing the rutine of manual verification
with the rutine of reading twenty sub-scores per branch is no win. The output is
**one normalized index**; the internals are exposed only on demand, only for a
branch that failed.

---

## 2. The governing identity

```
HRS  ==  MRS + SUM over branches ( GS_i + SUM ( TS_ij + SUM ( AS_ijk ) ) )
```

read not as textual equality but as: **the descent adds resolution, not meaning.**
With unlimited context, HRS plus restructuring would be directly executable; the
lower levels exist only because an executor cannot hold all of HRS at once. Each
descent step both *expands* (detail) and *partitions* (non-overlapping branches,
`t13`). Therefore:

- one branch is **not** all of HRS projected down — it is **one slice** of HRS
  (the binding paragraphs it claims via `source_labels`) expanded to code;
- the sum of branches reproduces HRS without gaps or duplicates;
- the unit of work is the **AS**: there are exactly as many assembled prompts as
  there are AS steps.

### The Star-of-David picture (two opposed triangles)

- **Downward triangle = decomposition.** Apex HRS, widening down. Slice meaning
  into ever smaller non-overlapping pieces. This produces the tree. Truth:
  "sum of pieces == original meaning, no gaps, no overlap."
- **Upward triangle = assembly.** Apex the concrete AS prompt, widening up. To
  build one executor prompt, do not re-write everything: take the AS delta + its
  TS + its GS + the HRS ranges (by `source_labels`) + the MRS excerpt, and
  **concatenate by reference.** Truth: "prompt == own delta + inherited path up."

Each AS sits at the crossing: it is simultaneously a **leaf of decomposition** and
a **root of assembly**. The economy: upper levels repeat between sibling branches,
so storing them once and assembling on demand keeps the per-AS delta minimal.

### Consequence: separate the two processes

The instrument distinguishes two objects that are easy to conflate:

1. **AS delta** — what is authored during decomposition. Minimal, lowest layer
   only. Stored in the tree.
2. **AS prompt** — what the executor receives. Assembled from delta + inherited
   path. Ephemeral; the single source of truth is the tree, never a stored prompt.

The prompt is fully derivable from the tree, so — by the same logic that kills the
matrices — it must **not** be persisted as truth. It is built on demand by a pure,
deterministic function `build_prompt(AS) -> delta + path-up + HRS-slice + MRS-excerpt`.
Optionally a `dump_prompts()` may materialize all prompts as a **derived snapshot**
(for human reading / archive / handoff), but the snapshot is never read back as input.

---

## 3. Concepts as an orthogonal basis (the key idea)

HRS is produced by a human (intuition + stereo vision) and a model (formalizing the
set of descriptors). The descriptors chosen are the **concepts**, and they are
selected to be **as orthogonal as possible**. This reframes a concept from "an
entity with behavior" (a consequence) to **a basis axis** of the meaning-space.

Therefore:

- **MRS is the basis** — a set of (ideally orthonormal) concept axes.
- **each HRS binding paragraph is a point** in that basis — a combination of
  concepts; its `source_labels` record which axes define it.
- **a branch is a point expanded down to code.**

Completeness then stops being a fuzzy "are these texts similar" question and
becomes **coordinate-wise presence**: for each concept that defines a branch's
HRS slice, is that concept present in the branch? In an orthogonal basis, a lost
facet of a multi-meaning paragraph is a **missing coordinate** — visible — rather
than a slightly-lower similarity that a coarse cosine would swallow.

**This only holds to the degree the basis is actually orthogonal.** Non-orthogonal
concepts (semantically overlapping) hide loss: a branch covering `C-A` passes the
"connection exists" check while a facet that `C-B` was meant to add is silently
gone, because `C-B` is indistinguishable from `C-A`. Hence basis quality must
itself be measured (Section 5).

---

## 4. The core metric: cosine in the concept basis

The semantic readiness of a branch is **the cosine between what the branch must
express and what it does express, expressed in the concept basis** — not between
raw HRS text and raw branch text (which would measure lexicon and raise false
alarms on the legitimate WHAT->HOW translation distance).

For each branch:

- `c_required` = the vector of concepts that define the branch's HRS slice
  (its `source_labels` -> the set of MRS axes). The target point.
- `c_actual`   = the vector of concepts actually unfolded in the branch
  (what is genuinely present across GS + TS + AS).
- **branch index** = `cos(c_required, c_actual)`, normalized to `[0,1]` (or `*100`).

In an orthogonal basis this degenerates toward a weighted coordinate-wise coverage
check, but cosine keeps it **smooth**: a partially-unfolded concept yields an
intermediate value rather than 0 or 1. That smoothness is the soft `0..100` scale
the instrument reports.

**Plan index** = an aggregate over branch indices (minimum, or fraction of
branches above a threshold — to be decided during development; minimum is the
conservative choice because one weak branch should not be averaged away).

### Honest limit of the cosine

`c_actual` is built from what a branch **engages/mentions**, not from what it
**correctly implements**. A high cosine means "all required axes are engaged," not
"engaged correctly." The residual class — **coherent but semantically wrong**
content (right topic, all references intact, executor finds it clear, yet it does
not do what HRS actually requires; the `c1`/`c2` fidelity question) — passes every
automaton and remains for a human reviewer. But the reviewer now works a **narrow
front**, ranked by low/middle index, instead of reading the whole tree.

---

## 5. The instrument is an ensemble of weak, independent estimators

No single criterion is reliable alone. Their power is that their **errors are
independent** — different blind spots that do not coincide — so when independent
weak estimators agree, confidence multiplies (an ensemble / random-forest logic).
Crucially, criteria of the **same physics** (e.g. two embedding-based ones) share a
blind mode and must **not** be counted as two independent votes.

Estimators, by physics:

| # | criterion | physics | output | catches |
|---|-----------|---------|--------|---------|
| 0 | basis orthogonality | embedding geometry | `det(Gram)`, pairwise cosines, spectrum | indistinct / overlapping concepts |
| 1 | concept coverage of slice | set logic (deterministic) | covered fraction | unfilled coordinate |
| 2 | reference resolution | syntax (deterministic) | resolves y/n | broken link up the path |
| 3 | core cosine (Sec. 4) | embedding geometry | `cos(c_required, c_actual)` | drift, lying `source_labels`, lost facet |
| 4 | executor simulation | generative (cheap model) | undefined-entity fraction | "existing pattern" not shown, missing signature |

Estimators 0 and 3 are both embedding-based — correlated, **not** two independent
votes. Estimator 4 (a cheap model asked the *closed* question "name every entity
the prompt uses but does not define") is non-deterministic; its output is
**suspicion**, filtered deterministically against the prompt text (machine discards
a "missing X" when X is in fact present). The model is a **detector, never a judge**.

---

## 6. Output discipline: one number, internals on demand

### Mechanical errors are a gate, not a term of the index

Broken reference, duplicate `step_id`, malformed YAML, `dir != step_id`,
non-unique priority, empty/multiple `target_file` — these are **always caught and
trivially fixed**. They carry no uncertainty (resolve or not), so they have **no
place in a confidence index**. They are a cheap **precondition gate before the
instrument runs**: a branch with a mechanical fault is not measured; the gate
returns "fix this here," the human fixes it, re-runs. Mechanics must never be
averaged against semantics — a branch with perfect semantics and one broken
reference is a broken branch, full stop, not a 96.

### The index is purely semantic

The reported number measures **only the non-obvious** — semantic completeness of a
branch that has already passed the mechanical gate. This is the cosine of Section 4,
the place where genuine uncertainty lives and where reducing-to-a-number is worth it.

### Reading the instrument

- In the normal case the human sees **one normalized number and a colour**
  (e.g. `>=85` hit / below it miss). Decision is binary, by one glance.
- The internal estimator vector is hidden; it is surfaced **only when a branch
  misses**, and only for that branch — like switching a multimeter to diagnostic
  mode when the main reading is bad: "index 71, pulled down by basis orthogonality."
- Plan-level: a readiness number plus the few weak branches, ranked.

### One index or two

A second number — **confidence in the measurement itself** — is justified, driven
by `det(Gram)` and embedding-service liveness: if the basis is non-orthogonal or
embeddings are unavailable, the semantic estimators are computed on sand. Options
to decide during development:

- **two numbers** — readiness + trust ("readiness 92, but trust 60: embeddings
  noisy, verify by hand"); distinguishes *fix the plan* from *fix the instrument*;
- **one number** — fold trust into readiness as a penalty (conservative: low when
  the plan is bad *and* when the plan cannot be measured); simpler glance, but
  merges "plan is weak" with "could not assess."

Recommendation: keep them separable internally; default the human view to one
number, reveal trust on a miss (same discipline as the estimator vector).

---

## 7. Pipeline (the linear process)

```
1. tree           given: HRS -> MRS -> GS -> TS -> AS (human+model, semi-intuitive)
2. assemble       build one prompt per AS = delta + path-up + HRS-slice + MRS-excerpt
                  (ephemeral; tree is the only source of truth)
3. mechanical     gate: parse / resolve / uniqueness / layout. FAIL -> "fix here", stop.
   gate
4. basis trust    det(Gram), pairwise concept cosines, spectrum -> measurement trust
5. core metric    per branch: cos(c_required, c_actual) in the concept basis
6. ensemble        + coverage, executor simulation; combine independent votes
7. index          one normalized semantic index per branch; aggregate per plan
8. report         one number + colour; internals & ranked weak branches on demand
```

---

## 8. Decoupling from any specific project

Nothing project-specific is hard-coded in the engine. The algorithms (cosine in a
basis, coverage, reference resolution, orthogonality, simulation) are properties of
**any** plan that follows `plan_standard_machine.yaml`. Project specifics live in a
single `PlanSchema` configuration object:

- **layout**: `plans_root` (run parameter), level definitions
  (`{kind, dir_glob, node_file}` per level), `spec_file`, `spec_concepts_key`,
  `spec_relations_key`;
- **identifiers**: `concept_id_pattern`, per-level `step_id_pattern`,
  `dir_equals_step_id`;
- **artifact fields**: `concept_required_fields`, `artifact_concepts_key`,
  `object_name_keys`, `as_target_file_key`, `as_priority_key`, `as_depends_on_key`,
  `as_step_id_key`, `dunder_objects_excluded`;
- **relation types**: the seven allowed types (from the standard, not the project).

Matrices are **absent** from the schema — they are computed from the tree on the
fly when needed (coverage, object realization), never read as input. The MRS excerpt
for a prompt is assembled from the AS delta's declared `concepts` (the engine
resolves them against MRS; it does not *choose* them — keeping assembly dumb and
deterministic, and making "correct concept selection" a checkable property of the
tree rather than hidden engine logic).

The schema lives as defaults matching the standard (so the instrument works
out-of-the-box on any conforming plan), overridable only for exotic cases.

---

## 9. What was reused vs. discarded from the prior tools

**Reused (project-agnostic algorithmic core):**
- `Findings`-style collector (severity error/warn/info);
- YAML-load-with-finding;
- five set primitives: set-resolve, coverage, uniqueness-in-scope,
  single-realization/no-collision, cross-artifact equality;
- recursive concept-id / object-name collectors over arbitrary YAML;
- JSON / exit-code reporting and CLI path resolution (`plan_validate` style,
  better than `plan_audit`'s hard-coded `PLANS = "docs/plans"`).

**Discarded:**
- all three matrix files and the two divergent matrix schemas — replaced by
  on-the-fly computation from the tree;
- hard-coded baselines (`!= 49 concepts`, `BASELINE` counts) — project-specific;
- `plan_locate.py` entirely — an ad-hoc, single-bug locator
  (`CalibrationObservation`, fixed scopes `G-005/T-003` / `G-003/T-003`),
  not a reusable algorithm.

**Newly added (absent from the prior tools):**
- basis orthogonality measurement (`det(Gram)`, pairwise, spectrum) as the trust
  precondition for the whole semantic layer;
- the core cosine-in-basis branch metric;
- ensemble aggregation to a single normalized index with mechanical errors as a
  pre-gate rather than an index term;
- deterministic on-demand prompt assembly (`build_prompt`) as the single object of
  the self-sufficiency check and as the matrix replacement.

---

## 10. Open parameters for the development phase

These are deliberately left unfixed; they are tuning choices, not architecture:

1. **plan-level aggregation** — minimum branch index (conservative) vs. fraction
   above threshold.
2. **slice granularity for the core cosine** — whole HRS-slice as one vector
   (cheap, catches drift / lying labels, blind to a lost facet) vs. per-tezis
   (catches lost facets too, but requires cutting the slice into tezises — a
   semantic act: human-authored at HRS time, or model-assisted).
3. **embedding source for concepts** — full concept text (`name`+`definition`+
   `properties`, rich but noisy from shared terminology) vs. `definition` only
   (cleaner meaning, sparser) — affects `det(Gram)` false-alarm rate.
4. **aggregator form** — transparent weighted fold (auditable; assumes
   independence) vs. a learned aggregator calibrated on the human's past verdicts
   (catches "low det forgiven by high coverage" but becomes a black box). For a
   "conscience" instrument, transparency is likely preferred over accuracy.
5. **one index vs. two** (readiness vs. readiness+trust) — see Section 6.
6. **weights and independence** — votes of the same physics (the two
   embedding-based estimators) must be down-weighted so the ensemble does not
   double-count one signal and overstate confidence.

---

## 11. Calibration principle

The instrument does not replace the human's stereo-vision verdict — it **tiles** it
across a volume the human cannot cover by hand. Run it on branches the human has
**already** judged good, observe the estimator profiles those branches produce,
fit weights and threshold so the index predicts the human's verdict, then apply to
new branches. This is the matrices' original goal (context cannot hold a hundred
branches) without their disease: not a cached truth, but an estimate calibrated on,
and accountable to, the human's own judgments.
