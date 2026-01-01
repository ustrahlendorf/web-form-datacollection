# testing

## how to run tests

From `web-form-verbrauch/`:

```bash
pytest
```

From `web-form-verbrauch/frontend/`:

```bash
npm test
```

## what the tests cover (at a glance)

- validators (date/time/number normalization & range checks)
- handlers (`/submit`, `/recent`, `/history`) including pagination and user isolation
- security posture checks (HTTPS, JWT authorizer, CORS, encryption-at-rest, least-privilege IAM)

## legacy snapshots

Historical “test count / checkpoint” reports were moved under `docs/legacy/` to avoid drift.


