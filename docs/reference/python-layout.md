# Python layout in this repository

This page is the **single reference** for how Python dependencies and import paths are organised. Two code areas stay separate: application and Lambda handler code lives under `src/`, the Vis-Connect library lives under `backend/src/backend/`. CDK bundling and import paths are built around that split.

## Root: `requirements.txt`

At the **repository root**, create a virtual environment and install:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

This file is the **development and tooling** set: CDK (`aws-cdk-lib`, API Gateway alpha packages), `boto3`, `pytest`, `hypothesis`, `requests`, and related pins. Use it for `cdk synth` / deploy tasks driven from the Taskfile and for running the test suite from the repo root.

## `backend/`: the `backend` package (`pyproject.toml`)

`backend/pyproject.toml` defines the **installable package** named `backend` (import: `backend…`). Runtime library dependencies declared there include `requests` and `python-dotenv>=1.0`. Entry points expose CLIs such as `api-auth`, `iot-data-config`, and `iot-data-feature`.

If you work on Vis-Connect code or run those CLIs locally, an **editable install** from the repo root is appropriate:

```bash
pip install -e backend/
```

You do **not** need that install only to run `pytest` at the root; see the next section.

## Tests: `tests/conftest.py` and `import backend`

[`tests/conftest.py`](../../tests/conftest.py) prepends `backend/src` to `sys.path` during pytest startup. That way tests can use normal `import backend…` without requiring every contributor to run `pip install -e backend/`. This is **intentional**: it keeps the default developer path to “venv + root `requirements.txt` + pytest” as low-friction as possible.

## Viessmann-related Lambdas: `requirements-heating.txt` and CDK bundling

Heating / Viessmann handlers are bundled with **`requirements-heating.txt`**: the CDK asset step runs `pip install -r requirements-heating.txt` into the Lambda artifact, then copies `src` and `backend` into the bundle (for example in `infrastructure/stacks/api_stack.py` for the heating-live function). At runtime, `PYTHONPATH` includes `backend/src` so the packaged `backend` package is importable next to the handlers.

### Convention: `backend/pyproject.toml` ↔ `requirements-heating.txt`

| File | Role |
|------|------|
| [`backend/pyproject.toml`](../../backend/pyproject.toml) | **Source of truth** for runtime dependencies of the `backend` package that must be present when Vis-Connect code runs inside the heating Lambda bundle (for example `requests`, `python-dotenv`). |
| [`requirements-heating.txt`](../../requirements-heating.txt) | **Install manifest** for that Lambda bundle: CDK runs `pip install -r requirements-heating.txt` in the bundle image. It is **not** generated from `pyproject.toml`; it must be kept in sync **by hand**. |

**Workflow when you add, remove, or change a library dependency that affects those Lambdas:**

1. Edit **[`backend/pyproject.toml`](../../backend/pyproject.toml)** first (`[project].dependencies`).
2. Update **[`requirements-heating.txt`](../../requirements-heating.txt)** so every package you rely on at Lambda runtime is listed there with a spec that does **not** contradict `pyproject.toml` (for example if `pyproject` pins `python-dotenv>=1.0`, heating should use at least that lower bound).
3. Prefer keeping **`>=` lower bounds** aligned between the two files where both specify a version, so drift is obvious in review. If heating intentionally uses a broader range, document why in the PR.

There is no automated sync step in the repo today; contributors are responsible for this pair staying compatible after dependency changes.

## Related documentation

- [`getting-started.md`](../getting-started.md) — deployment overview (Taskfile, frontend).
- [`backend/README.md`](../backend/README.md) — Vis-Connect backend overview.
- [`backend/vis-connect.md`](../backend/vis-connect.md) — Viessmann IoT API, OAuth, CLIs.
- [`reference/testing.md`](testing.md) — how to run tests.
