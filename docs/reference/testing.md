# testing

## how to run tests

From the repo root (`web-form-verbrauch/`):

```bash
# Run all tests (backend + frontend)
task test

# Backend only (pytest)
python3 -m pytest
# or: task test-backend

# Frontend only
cd frontend && npm test
# or: task test-frontend

# Focused settings/AppConfig checks
python3 -m pytest tests/test_auto_retrieval_config_handler.py
cd frontend && npm test -- app.settings.test.js
```

## what the tests cover (at a glance)

- validators (date/time/number normalization & range checks)
- handlers (`/submit`, `/recent`, `/history`) including pagination and user isolation
- auto-retrieval config API semantics (`GET/PUT /config/auto-retrieval`) including deployment trigger metadata
- settings tab payload validation and normalization rules (UUID, active window limits, HH:MM ordering)
- security posture checks (HTTPS, JWT authorizer, CORS, encryption-at-rest, least-privilege IAM)

## legacy snapshots

Historical “test count / checkpoint” reports were moved under `docs/legacy/` to avoid drift.
