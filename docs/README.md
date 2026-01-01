# documentation

This folder contains the **canonical documentation** for `web-form-verbrauch/`.

## quick start (recommended path)

If you are deploying from the repo root (`AWS-kiro/`), prefer the Taskfile workflow:

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

- `architecture.md` — system architecture, flows, component details
- `specification.md` — functional specification / requirements (release 1)

### runbooks

- `runbooks/year-rollover.md` — switch active ↔ passive DynamoDB tables via SSM pointers
- `runbooks/datalake-backup.md` — DynamoDB → S3 “datalake” snapshots

### reference

- `reference/testing.md` — how to run tests + where coverage comes from
- `reference/security.md` — security controls (high-level) + where they are enforced/tested

### legacy

`legacy/` contains **time-bound reports, incident write-ups, and historical chronicles** kept for audit trail/context.
These are not meant to be “how-to” docs.
