# Heizung Settings API

API Gateway (HTTP API, IAM-Auth) → Lambda (Python 3.13, arm64) → DynamoDB (On-Demand, PITR, Löschschutz).
Erfasst Änderungen der Heizungseinstellungen (Komfort/Normal/Reduziert, Heizkurve Neigung/Niveau).

Code-Orte im Repo:

| Teil | Ort |
| --- | --- |
| CDK-Stack `HeizungSettingsStack` | `infrastructure/stacks/heating_settings_stack.py` (registriert in `infrastructure/app.py`) |
| Handler (POST `/changes`) | `lambdas/heating_settings_writer/handler.py` |
| Handler (GET `/current`, GET `/changes`) | `lambdas/heating_settings_reader/handler.py` |
| Validierung und Datenmodell | `backend/src/backend/heating_settings/logic.py` |
| Tests | `tests/unit/test_heating_settings_*.py`, `tests/integration/test_heating_settings_stack.py` |

## Tabelle `Settings-HeizungParameter`

| Attribut | Beispiel | Hinweis |
| --- | --- | --- |
| `PK` | `SYSTEM#haus` | Anlage, per Stack-Parameter `system_id` |
| `SK` | `EVT#2026-10-29T07:40#a1b2c3d4e5` | `event_at` + Request-ID (Idempotenz) |
| `event_at` | `2026-10-29T07:40` | wann die Änderung wirksam wurde (Ortszeit) |
| `created_at` | `2026-10-29T07:41` | Erstellzeit in Ortszeit (Europe/Berlin), Format wie `event_at`, auf Minuten genau |
| `komfort`, `normal`, `reduziert` | `23` | ganze °C, 5–30 |
| `neigung` | `1.4` | 0.2–3.5, eine Nachkommastelle, immer Punkt |
| `niveau` | `0.0` | -10–10, eine Nachkommastelle |
| `prev` | `{"neigung": 1.2}` | Alt-Werte der geänderten Parameter (serverseitig berechnet); die Schlüssel zeigen, was sich geändert hat |
| `source` | `api` | Herkunft des Eintrags |

Der Stack hat die Tabelle mit festem Namen, PITR, Löschschutz und `RemovalPolicy.RETAIN`.

## Endpunkte (alle mit IAM/SigV4, `execute-api:Invoke`)

- `POST /changes` – Body: ein oder mehrere Parameter, optional `event_at`
  (`YYYY-MM-DD[THH:MM]`) und `request_id`. Fehlende Parameter werden aus dem
  Vorgängerzustand übernommen; der erste Eintrag braucht alle fünf.
  - `201` angelegt, `200` `unchanged`/`duplicate`, `400` Validierungsfehler, `409` Konflikt.
- `GET /current` – letzter Zustand.
- `GET /changes?from=&to=&limit=&order=&next_token=` – Historie.

Idempotenz: gleicher Body mit festem `event_at` (oder gleiche `request_id`) erzeugt keinen zweiten Eintrag.

## JWT-Route für das Frontend: `GET /heating/parameters`

Der Browser hat nur ein Cognito-JWT und kann die IAM-geschützte API oben nicht aufrufen.
Deshalb gibt es im `APIStack` (`DataCollectionAPI`, JWT-Authorizer, CORS bereits vorhanden)
eine schreibgeschützte Route `GET /heating/parameters`:

- Lambda `lambdas/heating_parameters/handler.py` (Logik in `backend/src/backend/heating_settings/reader.py`).
- Eigene Rolle mit nur `dynamodb:Query` auf `Settings-HeizungParameter` (Referenz per festem
  Tabellennamen/ARN, keine Stack-Abhängigkeit zu `HeizungSettingsStack`). Deploy: `task deploy-api`.
- Query: `limit` (1–100, Default 50), `next_token` (opak, aus der vorigen Antwort).
- Antwort `200`: `{"items": [...], "count": N, "next_token": "..."}`; `next_token` nur, wenn weitere
  Einträge existieren. Sortierung immer neueste zuerst.
- Items enthalten ausschließlich `event_at`, `created_at`, `komfort`, `normal`, `reduziert`, `neigung`,
  `niveau`, `prev` (`{}` falls leer), `source` – `PK` und `SK` werden nie ausgeliefert (Allowlist).
- `400` bei ungültigem `limit`/`next_token`, `500` generisch (`{"error": "interner Fehler"}`).

## Entwickeln und Deployen

Das Projekt nutzt wie alle anderen Teile das Repo-venv und die Root-`requirements.txt`
(`aws-cdk-lib` 2.276, `moto` für die Handler-Tests):

```bash
source .venv/bin/activate
pytest tests/unit/test_heating_settings_logic.py tests/unit/test_heating_settings_handlers.py \
       tests/integration/test_heating_settings_stack.py
task deploy-heating-settings
```

Der Stack ist unabhängig von den anderen Stacks. Die Lambdas nutzen das gemeinsame
Repo-Asset mit `PYTHONPATH=backend/src` (siehe `reference/python-layout.md`). Beim Ändern
der Handler gilt: `handler=`-Strings in CDK und Modulpfade unter `lambdas/` müssen übereinstimmen.
