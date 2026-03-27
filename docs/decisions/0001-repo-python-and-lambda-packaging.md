# ADR 0001: Repository Python packaging and Lambda assets

- **Status:** Accepted
- **Date:** 2025-03-26
- **Context:** Planned incremental repo restructuring (handlers under `lambdas/`, optional domain consolidation, clearer CDK bundling). See [`docs/architecture/repo-layout.md`](../architecture/repo-layout.md) for the full blueprint.

## Context

The repository today has:

- Lambda handler code under `lambdas/<function>/handler.py`, referenced by CDK as `lambdas.<function>.handler.lambda_handler` (with transitional `src/handlers/*` re-exports).
- A separate installable Python package **`backend`** under `backend/src/backend/`, used by Viessmann/heating flows and bundled into Lambda artifacts with `PYTHONPATH` including `backend/src`.
- Multiple bundling paths: typical root-based assets with excludes, and Docker-based bundling for heating with `requirements-heating.txt`.

We need agreed rules for **package naming**, **what goes into each Lambda asset**, and **how to name `lambdas/*` directories** so later phases (CDK updates, test import rewrites) do not thrash.

## Decision

1. **Package name** — Retain the installable package name **`backend`** for the duration of the handler and asset migration. A future rename (for example to a domain-specific name) will be a **separate**, explicit decision and change set.

2. **Lambda asset model** — Adopt **Option A** from the architecture doc: prefer a **shared runtime root** per bundle class (standard vs heating Docker), with an explicit copy list of `backend`, handler tree, and shared `src` modules as needed. **Do not**, in the first migration wave, require a separate minimal `Code.from_asset` per function unless a stack already needs it for size or isolation.

3. **`lambdas/` naming** — One **snake_case** directory per logical Lambda entry point, aligned with **function purpose** (for example `submit`, `heating_live`, `auto_retrieval`), not internal Python class names. Use the mapping table in [`repo-layout.md`](../architecture/repo-layout.md).

4. **`requirements-heating.txt`** — Continue to treat it as the heating Lambda bundle install list, **manually** kept consistent with `backend/pyproject.toml` as documented in [`reference/python-layout.md`](../reference/python-layout.md).

5. **Transition** — Optional thin re-exports (for example under `src/legacy/`) are allowed until all references to old module paths are updated; remove when migration is complete.

## Consequences

### Positive

- One clear default for CDK authors: **broad bundle + explicit copies** instead of many one-off asset layouts.
- Handler moves to `lambdas/` can proceed **without** renaming the `backend` package, reducing diff size and risk.
- Naming is predictable for operators and code search.

### Negative / trade-offs

- Function ZIPs may remain **larger** than a per-function minimal asset until Option B (per-function assets or layers) is adopted later.
- **Two import roots** (`src` and `backend`) remain until domain consolidation phases finish; contributors must still read `python-layout.md`.

### Follow-up

- When implementing physical moves, update **CDK handler strings**, **tests** (`@patch` targets), and **`docs/reference/python-layout.md`** in the same delivery as the code change.
- Revisit **Option B** (layers or per-function assets) if cold-start size or independent deployment of shared code becomes a measured problem.
