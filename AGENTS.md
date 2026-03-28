# Supervisor playbook (AI agents)

Short guide for a **supervisor** coordinating work in this repo: who touches what, when to split work across areas, and what to verify before treating a change as ready.

## Project context

- **IaC:** AWS CDK (Python) under `infrastructure/`; root `cdk.json` drives synth/deploy tasks.
- **Lambda entry points:** `lambdas/<function>/handler.py` (or equivalent module) exposing the handler symbol wired in CDK (often `lambda_handler`).
- **Domain and integrations:** Python package `backend/` (`shared`, `viessmann`, `heating`, …) — see `docs/architecture/repo-layout.md` and `docs/reference/python-layout.md`.
- **UI:** Static frontend under `frontend/` (build and deploy scripts live there).

## Canonical documentation

Start from **`docs/README.md`** (table of contents). Deep dives: **`docs/getting-started.md`** (venv, Taskfile deploy order, env notes), **`docs/architecture/repo-layout.md`**, ADR **`docs/decisions/0001-repo-python-and-lambda-packaging.md`**.

## Cursor rules and skills (path-scoped guidance)

When present, numbered rules under **`.cursor/rules/*.mdc`** complement this file. Typical mapping:

| Area | Paths (primary) | Rule file (when added) |
|------|-----------------|-------------------------|
| Repo boundaries | all | `00-repo-boundaries.mdc` |
| Backend / domain | `backend/**/*.py` | `10-backend-python.mdc` |
| Lambda handlers | `lambdas/**/*.py` | `20-lambda-handlers.mdc` |
| CDK | `infrastructure/**/*.py` | `30-cdk-infrastructure.mdc` |
| Frontend | `frontend/src/**` | `40-frontend-ui.mdc` |

Skills under **`.cursor/skills/<name>/SKILL.md`** (when added): `deploy-cdk`, `viessmann-debug`, `lambda-contract-check`, `frontend-static-ui`. Use the skill that matches the task instead of re-deriving workflows from scratch.

## Delegation matrix (sub-agents)

Assign **one primary scope** per sub-agent to reduce conflicting edits:

- **`backend/`** — domain logic, validators, Viessmann/heating libraries; respect pytest import layout in `docs/reference/python-layout.md`.
- **`lambdas/`** — thin handlers, correct `lambda_handler` and imports from `backend`; align with `infrastructure/config/lambda_assets.py` and stacks when bundling changes.
- **`infrastructure/`** — stacks, constructs, handler strings, env-dependent table wiring; keep synth inputs documented in Taskfile comments / getting-started.
- **`frontend/`** — static UI and tests; follow existing patterns under `frontend/src/`; do not modify `node_modules/`.

## Cross-cutting changes

Some tasks **must not** be owned by a single narrow agent in one shot, for example:

- New or changed **API routes** → CDK/API stack, one or more **`lambdas/*`**, and often **`frontend/`** (URLs, auth, payloads).
- **DynamoDB / SSM** naming or pointer changes → **`infrastructure/`** plus any Lambda or backend code that assumes resource names.

**Supervisor:** either run sub-agents **in sequence** (infra → handlers → frontend, or the order that minimizes rework) with explicit handoffs, or one agent with a written checklist covering all touched trees. Avoid parallel edits to the same files.

## Checks before recommending merge

Run what applies to the change; **do not** commit or paste secrets, tokens, or real parameter values into chat or repo files.

1. **`task doctor`** — use when the change touches Python/CDK/Lambda expectations; it checks tooling, required DynamoDB name env vars, and heating dependency alignment (see `Taskfile.yml`).
2. **`task test`** — backend (`pytest`) and frontend (`npm test` in `frontend/`). Prefer green tests for modules you changed.
3. **`task cdk:synth`** (or `task cdk:diff` when appropriate) — requires the same **non-secret** inputs as documented: `taskfile.env` is loaded by Task; set **`ACTIVE_SUBMISSIONS_TABLE_NAME`** and **`PASSIVE_SUBMISSIONS_TABLE_NAME`** (and related vars per `docs/getting-started.md` and `Taskfile.yml` comments). Example pattern for ad-hoc synth is shown at the top of `Taskfile.yml`.

If the change is frontend-only, `task test-frontend` may suffice; if backend-only, `task test-backend`. When unsure, run **`task test`** and **`task cdk:synth`** after `task doctor` passes.

## Sub-agent prompt pattern (optional)

One line of repo context, **path scope**, task, **exit criterion** (e.g. “pytest green for `tests/unit/test_foo.py`” or “`task cdk:synth` succeeds with env from `taskfile.env`”). Keeps handoffs reviewable.
