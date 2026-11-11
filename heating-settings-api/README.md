# Heizung Settings API

API Gateway (HTTP API, IAM-Auth) → Lambda (Python 3.13, arm64) → DynamoDB (On-Demand, PITR, Löschschutz).

## Tabelle

| Attribut | Beispiel | Hinweis |
|---|---|---|
| `PK` | `SYSTEM#haus` | Anlage, per Stack-Parameter `system_id` |
| `SK` | `EVT#2026-10-29T07:40#a1b2c3d4e5` | `event_at` + Request-ID (Idempotenz) |
| `event_at` | `2026-10-29T07:40` | wann die Änderung wirksam wurde (Ortszeit) |
| `created_at` | `2026-10-29T06:41:12Z` | Server-Zeit (UTC) |
| `komfort`, `normal`, `reduziert` | `23` | ganze °C, 5–30 |
| `neigung` | `1.4` | 0.2–3.5, eine Nachkommastelle, immer Punkt |
| `niveau` | `0.0` | -10–10, eine Nachkommastelle |
| `prev` | `{"neigung": 1.2}` | Alt-Werte der geänderten Parameter (serverseitig berechnet) |
| `changed` | `["neigung"]` | |
| `quality` | `["time_unknown"]` | z. B. `time_unknown`, `backdated_before_later_events` |

## Endpunkte (alle mit IAM/SigV4, `execute-api:Invoke`)

- `POST /changes` – Body: ein oder mehrere Parameter, optional `event_at`
  (`YYYY-MM-DD[THH:MM]`) und `request_id`. Fehlende Parameter werden aus dem
  Vorgängerzustand übernommen; der erste Eintrag braucht alle fünf.
  - `201` angelegt, `200` `unchanged`/`duplicate`, `400` Validierungsfehler, `409` Konflikt.
- `GET /current` – letzter Zustand.
- `GET /changes?from=&to=&limit=&order=&next_token=` – Historie.

Idempotenz: gleicher Body mit festem `event_at` (oder gleiche `request_id`) erzeugt keinen zweiten Eintrag.

## Entwickeln

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
cdk synth --strict
```

## Deployment (bewusst noch nicht ausgeführt)

```bash
cdk bootstrap aws://<ACCOUNT>/<REGION>   # einmalig pro Account/Region
cdk diff
cdk deploy
```
