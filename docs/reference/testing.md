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
```

## what the tests cover (at a glance)

- validators (date/time/number normalization & range checks)
- handlers (`/submit`, `/recent`, `/history`) including pagination and user isolation
- security posture checks (HTTPS, JWT authorizer, CORS, encryption-at-rest, least-privilege IAM)

## legacy snapshots

Historical “test count / checkpoint” reports were moved under `docs/legacy/` to avoid drift.


