# documentation

This folder contains the **canonical documentation** for `web-form-verbrauch/`.

## quick start (recommended path)

If you are deploying from the repo root (`web-form-verbrauch/`), prefer the Taskfile workflow:

- `task doctor`
- `task deploy-init` (one-time “SSM contract” parameters)
- `task deploy-dynamodb`
- `task deploy-api`
- `task deploy-frontend`

Then deploy frontend assets from `web-form-verbrauch/frontend/`:

- `bash setup-env.sh dev`
- `bash build.sh`
- `bash deploy.sh dev`

For the full, canonical guide, see `getting-started.md`.

## table of contents

### getting started / day-1 operations

- `getting-started.md` — deploy, configure, verify, rollback (Taskfile + CDK + scripts)
- `operations/troubleshooting.md` — common symptoms and where to look first

### architecture & requirements

- `architecture/repo-layout.md` — Python packages, Lambda `lambdas/*` naming, CDK asset strategy (blueprint; complements `reference/python-layout.md`)
- `decisions/0001-repo-python-and-lambda-packaging.md` — ADR: keep `backend` package name through migration, shared runtime bundle default, heating requirements workflow
- `specification.md` — functional specification / requirements (release 1)

### runbooks

- `runbooks/year-rollover.md` — switch active ↔ passive DynamoDB tables via SSM pointers
- `runbooks/datalake-backup.md` — DynamoDB → S3 “datalake” snapshots
- `runbooks/auto-retrieval-deployment.md` — scheduled Viessmann data retrieval
- `runbooks/appconfig-agent-fit.md` — AppConfig Agent adoption notes (complements auto-retrieval runbook)

### reference

- `reference/python-layout.md` — Python dependencies: root `requirements.txt`, `backend/pyproject.toml`, Lambda `requirements-heating.txt` (manual sync with pyproject), pytest `sys.path`
- `reference/testing.md` — how to run tests + where coverage comes from
- `reference/security.md` — security controls (high-level) + where they are enforced/tested

### backend (Vis-Connect)

- `backend/README.md` — overview of the Vis-Connect backend package
- `backend/vis-connect.md` — Viessmann IoT API: OAuth, config, feature fetching, CLI tools

### legacy

`legacy/` contains **time-bound reports, incident write-ups, and historical chronicles** kept for audit trail/context.
These are not meant to be “how-to” docs.
