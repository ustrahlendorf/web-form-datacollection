# getting started

This is the **canonical** deployment + configuration guide for the app.

## mental model (what you’re deploying)

- **infrastructure**: AWS CDK stacks (Cognito, DynamoDB, API, Frontend infra, DataLake)
- **frontend assets**: static files uploaded to S3 and served through CloudFront
- **configuration**: frontend `.env` / generated `config.js` (from stack outputs)

## recommended: deploy infrastructure via Taskfile (repo root)

From the repo root (`web-form-verbrauch/`):

```bash
task doctor

# one-time: creates static SSM parameters under /HeatingDataCollection
task deploy-init

# deploy/update DynamoDB pointers and API wiring
task deploy-dynamodb
task deploy-api
task deploy-frontend
```

Notes:
- The Taskfile loads `taskfile.env` automatically (including `SSM_NAMESPACE_PREFIX=/HeatingDataCollection`).
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

## year roll-over (two DynamoDB tables)

If you are switching active ↔ passive tables via SSM pointers, follow:
- `runbooks/year-rollover.md`

## backups / exports

Monthly snapshot exports to S3:
- `runbooks/datalake-backup.md`

## troubleshooting

Start here for common symptoms and first checks:
- `operations/troubleshooting.md`


