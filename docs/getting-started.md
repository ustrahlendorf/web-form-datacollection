# getting started

This is the **canonical** deployment + configuration guide for the app.

## mental model (what you’re deploying)

- **infrastructure**: AWS CDK stacks (Cognito, DynamoDB, API, Frontend infra, DataLake)
- **frontend assets**: static files uploaded to S3 and served through CloudFront
- **configuration**: frontend `.env` / generated `config.js` (from stack outputs)

## Python environment

From the repo root, use a virtual environment and root dependencies for CDK and pytest:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Roles of `requirements.txt`, `backend/pyproject.toml`, Lambda `requirements-heating.txt`, and how tests import `backend` without an editable install are described in `reference/python-layout.md`.

## recommended: deploy infrastructure via Taskfile (repo root)

From the repo root (`web-form-verbrauch/`):

```bash
task doctor
export PFX="${SSM_NAMESPACE_PREFIX:-/HeatingDataCollection}"

# one-time: creates static SSM parameters under ${PFX}
task deploy-init

# deploy/update DynamoDB pointers and API wiring
task deploy-dynamodb
task deploy-api
task deploy-frontend
```

Notes:
- The Taskfile loads `taskfile.env` automatically (default: `SSM_NAMESPACE_PREFIX=/HeatingDataCollection`).
- Use `PFX="${SSM_NAMESPACE_PREFIX:-/HeatingDataCollection}"` in ad-hoc CLI commands to avoid hardcoded namespace paths.
- For `deploy-dynamodb`, `deploy-api`, and `deploy-frontend`, set `ACTIVE_SUBMISSIONS_TABLE_NAME` and `PASSIVE_SUBMISSIONS_TABLE_NAME` in `taskfile.env` (e.g. `submissions-2025` / `submissions-2026`). `deploy-init` uses placeholders when these are unset.
- Frontend asset upload is still performed from `web-form-verbrauch/frontend/` (next section).

## deploy frontend assets (S3 + CloudFront)

From `web-form-verbrauch/frontend/`:

```bash
bash setup-env.sh dev
bash build.sh
bash deploy.sh dev
```

## verify (smoke checks)

- Open the CloudFront URL (printed by deploy scripts) and confirm:
  - login via Cognito Hosted UI works
  - submit works (POST `/submit`)
  - recent works (GET `/recent`)
  - history works (GET `/history`, pagination)

## auto-retrieval (Viessmann API → DynamoDB)

To enable scheduled daily retrieval of heating data from the Viessmann API:
- `runbooks/auto-retrieval-deployment.md`

## year roll-over (two DynamoDB tables)

If you are switching active ↔ passive tables via SSM pointers, follow:
- `runbooks/year-rollover.md`

## backups / exports

Monthly snapshot exports to S3:
- `runbooks/datalake-backup.md`

## troubleshooting

Start here for common symptoms and first checks:
- `operations/troubleshooting.md`


