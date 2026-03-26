# Repository layout: Python packages, Lambdas, and CDK assets

This document is the **architecture blueprint** for how we organise Python code, Lambda entry points, and deployment bundles. It complements the operational detail in [`reference/python-layout.md`](../reference/python-layout.md) (dependencies, `PYTHONPATH`, `requirements-heating.txt`). When the tree is refactored (for example handlers under `lambdas/`), update `python-layout.md` in the same change set so both stay aligned.

## Goals

- Clear separation of **entry points** (Lambda handlers), **domain and integrations** (forms, DynamoDB, Viessmann), and **IaC** (`infrastructure/`).
- **Incremental** migration: small, reviewable steps; each phase should still pass `cdk synth`, `pytest`, and affected builds.
- Predictable **CDK asset** behaviour: everyone knows what lands in a function ZIP and why.

## Current state (summary)

| Area | Location | Role |
|------|----------|------|
| Handlers | `src/handlers/*.py` | Lambda `handler=` modules (see CDK stacks). |
| Form / API domain | `src/models.py`, `src/validators.py`, `src/viessmann_submit.py` | Shared logic used by handlers (not all of it is Viessmann-specific). |
| Vis-Connect library | `backend/src/backend/` (package name **`backend`**) | OAuth, IoT config, feature data; CLIs from `backend/pyproject.toml`. |
| CDK | `infrastructure/` | Stacks define Lambdas, bundling, and handler strings such as `src.handlers.submit_handler.lambda_handler`. |
| Tests | `tests/unit/`, `tests/integration/`, `tests/e2e/` | Pytest layout: fast isolated tests vs CDK/template and multi-handler flows; `e2e/` reserved for opt-in live tests. Shared `tests/conftest.py` applies to all. |

Most Lambdas use a **repository-root** (or similarly broad) asset with excludes; the **heating live** function uses **Docker bundling** plus `requirements-heating.txt` and copies `src` and `backend` into the image output. Details remain documented in `reference/python-layout.md` and in `infrastructure/stacks/api_stack.py`.

## Package strategy

### Two import roots today

1. **`src`** — not installed as a package; available on `PYTHONPATH` inside bundles that copy the `src` tree.
2. **`backend`** — installable package (`pip install -e backend/`); tests also expose it via `tests/conftest.py` prepending `backend/src` to `sys.path`.

### Decisions (see ADR 0001)

- **Keep the published package name `backend` through the planned refactor phases** unless a dedicated rename initiative is approved. Renaming touches every `import backend…`, CLIs, CDK paths, and documentation; it is deferred to reduce moving parts during handler and asset migration.
- **Domain consolidation under `backend/`** (for example subpackages for Viessmann, heating, shared form logic) is a **later** phase, after handler placement is stable. Until then, `src/` may remain the home for form-centric modules even if the long-term target is to fold them into `backend` (or a clearly named `backend/shared`).

### `requirements-heating.txt`

- Remains the **install manifest** for the heating/Viessmann-heavy Lambda bundle.
- Stays **manually** aligned with `backend/pyproject.toml` as described in `reference/python-layout.md`; no change to that workflow from this ADR.

## Lambda asset model

We distinguish three **strategic** options (full comparison in ADR 0001):

| Option | Idea | Use when |
|--------|------|----------|
| **A — Shared runtime root (recommended for migration)** | One logical runtime tree per bundle (often repo root or a shared `_bundle/`): CDK copies `backend/` and the handler tree into the asset. Handlers may **physically** live under `lambdas/<name>/` while imports and bundling commands are updated together. | Incremental Phase E: fewer packaging variants to maintain. |
| **B — One asset per function** | `Code.from_asset("lambdas/foo")` with an explicit file list per function; optional **Lambda layer** for `backend`. | Smaller ZIPs, stricter isolation; more CDK and release complexity. |
| **C — Document only** | No code moves; only docs and peripheral layout. | Minimal effort; dual `src` + `backend` world remains. |

**Chosen direction for upcoming work:** **Option A** — prefer a **single, well-defined copy list** per bundle type (standard vs heating Docker) over many per-function assets, until there is a concrete need for Option B (size, compliance, or independent release cadence).

## Naming convention: `lambdas/*`

When handlers are moved under `lambdas/`, **one directory per deployed function** (or per logical Lambda resource), using **snake_case** names that match the product name, not internal class names.

Suggested mapping from **current** handler modules (as of CDK configuration):

| CDK handler module (today) | Suggested `lambdas/` directory |
|----------------------------|--------------------------------|
| `src.handlers.submit_handler` | `lambdas/submit/` |
| `src.handlers.history_handler` | `lambdas/history/` |
| `src.handlers.recent_handler` | `lambdas/recent/` |
| `src.handlers.heating_live_handler` | `lambdas/heating_live/` |
| `src.handlers.auto_retrieval_handler` | `lambdas/auto_retrieval/` |
| `src.handlers.auto_retrieval_config_handler` | `lambdas/auto_retrieval_config/` |
| `src.handlers.auto_retrieval_config_validator` | `lambdas/auto_retrieval_config_validator/` |

**Conventions:**

- Each folder exposes a **`lambda_handler`** (or the symbol referenced by CDK) in a small module such as `handler.py` or `__init__.py`; the exact file name is chosen when implementing Phase E.
- **Do not** invent separate Lambdas for concerns that are **library-only** today (for example token refresh inside `backend`); keep those in the `backend` package.
- If two stacks share the **same** handler code (for example scheduled vs daily auto retrieval using `auto_retrieval_handler`), they still use **one** `lambdas/auto_retrieval/` tree and two CDK `Function` resources pointing at the same handler string.

## Compatibility shims (transition)

During migration, a thin **`src/legacy/`** (or equivalent re-export layer) may re-export moved handlers so external runbooks and deep links to module paths break less abruptly. This is **temporary**; remove shims once grep shows no remaining `src.handlers` references in tests, docs, and CDK.

## Related documents

- [`docs/decisions/0001-repo-python-and-lambda-packaging.md`](../decisions/0001-repo-python-and-lambda-packaging.md) — formal ADR for the decisions above.
- [`docs/reference/python-layout.md`](../reference/python-layout.md) — dependencies, venv, pytest, heating bundle.
- [`docs/specification.md`](../specification.md) — functional requirements.
