# web-form-verbrauch

Web-App zur Erfassung/Anzeige von Gastherme-Verbrauchsdaten (Viessmann API). AWS-Stack: Cognito, DynamoDB, S3, CloudFront, Lambda, CDK (Python). Frontend: vanilla JS SPA.

## Repo-Grenzen

- **`lambdas/<function>/`** — Lambda-Entry-Points (`handler.py`, `lambda_handler`). Ein snake_case-Ordner pro deployter Funktion; CDK `handler=` zeigt hierher. Domänenlogik gehört nach `backend`, nicht hierher.
- **`backend/`** — installierbares Package `backend` (`backend/src/backend/`): `shared` (Models/Validators), `viessmann` (OAuth/Submit), `heating.iot_data`. Von Handlern und Tests genutzt.
- **`infrastructure/`** — AWS CDK (Stacks, Constructs, Bundling). Root `cdk.json` steuert synth/deploy.
- **`frontend/`** — statische UI. Code unter `frontend/src/` (JS/CSS) und `frontend/public/` (HTML). Nicht `node_modules` editieren.
- **`tests/`** — `unit`, `integration`, `e2e`; gemeinsames `tests/conftest.py`.

Canonical docs: [docs/README.md](docs/README.md), [docs/architecture/repo-layout.md](docs/architecture/repo-layout.md), [docs/getting-started.md](docs/getting-started.md), [docs/decisions/0001-repo-python-and-lambda-packaging.md](docs/decisions/0001-repo-python-and-lambda-packaging.md).

## AWS-Umgebung

- **AWS-Profil:** `uwes_priv`
- **Region:** `eu-central-1`
- Nur **dev**-Environment wird unterstützt (kein prod/staging via Taskfile).
- Für ad-hoc AWS-CLI-/CDK-Befehle: `AWS_PROFILE=uwes_priv AWS_REGION=eu-central-1 <command>` (Env-Vars in separaten Bash-Calls nicht persistent — immer inline voranstellen).

## Infrastruktur-Deploy (Taskfile, Repo-Root)

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
task doctor
export PFX="${SSM_NAMESPACE_PREFIX:-/HeatingDataCollection}"

task deploy-init        # einmalig: SSM-Parameter
task deploy-dynamodb
task deploy-api
task deploy-frontend
```

- `ACTIVE_SUBMISSIONS_TABLE_NAME` / `PASSIVE_SUBMISSIONS_TABLE_NAME` müssen in `taskfile.env` gesetzt sein.
- `task deploy-api` deployt nur den API-Stack; `task deploy-api-with-deps` zieht Abhängigkeiten mit.

## Frontend Build & Deploy

Aus `frontend/`:

```bash
AWS_PROFILE=uwes_priv AWS_REGION=eu-central-1 bash setup-env.sh dev   # generiert .env aus CDK-Outputs
bash build.sh                                                          # baut nach frontend/build (cache-busted)
AWS_PROFILE=uwes_priv AWS_REGION=eu-central-1 bash deploy.sh dev       # S3-Sync + CloudFront-Invalidation
```

## Tests

- Frontend: `cd frontend && npx jest`
- Python: `pytest` (venv aktiv, siehe `tests/conftest.py`)

## Konventionen

- Lambda-Handler bleiben dünn; Logik in `backend`-Subpackages.
- CDK `handler=`-Strings müssen mit `lambdas/`-Modulpfaden synchron bleiben.
- Frontend: bestehende Patterns in `frontend/src/app.js` folgen (Template-Literals, `innerHTML`-Rendering, Helper-Funktionen für Formatierung, `module.exports`-Block am Dateiende für Jest).
- Keine Secrets in `taskfile.env` committen.
