# Heizungsparameter ↔ Viessmann-API (Vertrag)

Branch `feature/heizungs-parameter-api-connect`. Dieser Vertrag ist die gemeinsame Basis für Backend, Lambda/Infra und Frontend.

## Entscheidungen

- Nur Heizkreis 0 (`heating.circuits.0`).
- Grenzen und Plausibilität unverändert (`backend.heating_settings.logic.LIMITS`, `reduziert ≤ normal ≤ komfort`); serverseitig erneut prüfen.
- "No change"-Regel bleibt: kein Schreiben, wenn alle Werte dem Ist-Zustand entsprechen.
- Schreiben nur für **geänderte** Parameter. Ablauf bei `POST`: validieren → Live lesen → Diff → Commands → Verifikations-Read → DynamoDB-Eintrag mit den **verifizierten** Werten.
- Teilfehler: Abbruch beim ersten fehlgeschlagenen Command, Verifikations-Read, Eintrag der tatsächlichen Werte, Antwort 502 mit `partial: true`.
- Bestätigungsdialog (Frontend) vor jedem Schreiben in die Therme.
- Gruppe: Cognito-Gruppe `heating-parameter-writers`. Pflicht für `POST /heating/parameters` und `POST /heating/parameters/sync`. Lesen (`GET …/live`) darf jeder angemeldete User. Prüfung über Claim `cognito:groups` im Lambda (403 sonst).
- `source` in DynamoDB: `web` (Submit aus GUI), `viessmann` (Sync von Live-Werten). Bei Teilfehler weiterhin `web`.
- Zeitstempel: Server setzt `event_at` auf "jetzt" (Europe/Berlin); ein vom Client gesendetes `event_at` wird bei `POST /heating/parameters` ignoriert.
- Rate-Limits: pro Request höchstens 1× `get_device_features` (Batch) plus je 1 Command pro geändertem Parameter plus 1 Verifikations-Read. Token-Cache `/tmp/viessmann/tokens.json` nutzen (existiert bereits).
- API-Gateway-Limit 30 s: Command-Timeouts so wählen, dass der Gesamtpfad < 28 s bleibt (z. B. 8 s je Call).

## Viessmann-Mapping (zu verifizieren, siehe offene Punkte)

| Parameter | Feature | Command |
|---|---|---|
| komfort | `heating.circuits.0.operating.programs.comfort` | `setTemperature` `{targetTemperature}` |
| normal | `heating.circuits.0.operating.programs.normal` | `setTemperature` `{targetTemperature}` |
| reduziert | `heating.circuits.0.operating.programs.reduced` | `setTemperature` `{targetTemperature}` |
| neigung | `heating.circuits.0.heating.curve` (`properties.slope`) | `setCurve` `{slope, shift}` |
| niveau | `heating.circuits.0.heating.curve` (`properties.shift`) | `setCurve` `{slope, shift}` |

`setCurve` braucht immer beide Werte: fehlt einer der beiden Änderungen, den aktuellen Live-Wert mitsenden. Offen: Viessmann-`shift` ist evtl. ganzzahlig, unser `niveau` hat 1 Nachkommastelle → gegen reale Feature-Antwort (`commands.setCurve.params` Constraints) prüfen, Ergebnis dokumentieren, nicht raten.

## Zeitstempel in der Feature-Antwort (Untersuchung 2026-11-16)

Frage: Enthält die Viessmann-Leseantwort für `comfort`/`normal`/`reduced` und `heating.curve` (`slope`/`shift`) einen Zeitpunkt, wann der Wert gesetzt wurde?

**Ergebnis:** Ja, als `timestamp` auf **Feature-Ebene** (ISO 8601, UTC, Millisekunden, `Z`). Auf Property- und Command-Ebene gibt es keinen Zeitstempel. `slope` und `shift` teilen sich den Zeitstempel von `heating.curve`.

```json
{ "feature": "heating.circuits.0.heating.curve", "timestamp": "2026-11-16T09:11:02.765Z",
  "properties": { "slope": { "value": 1.4 }, "shift": { "value": 0 } } }
```

**Semantik (empirisch, die offizielle Doku nennt sie nicht):** `timestamp` ist der Zeitpunkt, an dem die Therme den Wert übernommen hat (Änderungszeitpunkt).

- Bei unveränderten Werten bleibt er über mehrere Abrufe stabil (3 Abrufe über 10 min). Er ist weder die Abfragezeit noch ein Sync-Takt.
- Nach einer Änderung springt nur der Zeitstempel des geänderten Features, ca. 1–2 s nach dem Schreibbefehl bzw. zum Zeitpunkt der Änderung in ViCare. Die anderen Features bleiben unverändert.
- Belegt für `reduced` und `heating.curve`, jeweils beim Schreiben über `apply_heating_parameters` und bei Änderung in der ViCare-App. Für `comfort` und `normal` ist das Verhalten naheliegend, aber nicht getestet.
- Nicht unterscheidbar, **wer** geändert hat (API, ViCare, Regler).
- `slope` und `shift` lassen sich nicht getrennt datieren. Ob eine Änderung nur von `shift` den Zeitstempel allein bewegt, wurde nicht getestet (im ViCare-Test wurden beide gemeinsam geändert).
- Features ohne Änderung seit längerem teilen sich einen gemeinsamen Zeitstempel (im Test 121 von 147 Features), vermutlich ein früherer gemeinsamer Zeitpunkt wie Neustart oder Gateway-Abgleich (Annahme).

**Cache-Verhalten nach API-Schreiben:** Ein Abruf direkt (ca. 1 s) nach dem Command liefert noch den alten Wert samt altem Zeitstempel; nach ca. 1 min ist der neue Stand sichtbar. Bei Änderung in ViCare war der neue Stand sofort sichtbar. Ein Verifikations-Read direkt nach dem Schreiben kann also noch den alten Zeitstempel zeigen.

Aktuell wird der Zeitstempel in `_parse_live` und `GET …/live` **nicht** übernommen (nur `properties.*.value`, `fetched_at` ist die Abrufzeit).

## Endpunkte (alle Cognito-JWT)

### `GET /heating/parameters/live`
200:
```json
{ "komfort": 22, "normal": 20, "reduziert": 16, "neigung": 1.4, "niveau": 0.0, "fetched_at": "2026-11-15T10:00:00+00:00" }
```
Nicht lesbare Werte `null`. 502 `{ "error": "..." }` bei Viessmann-Fehler.

### `POST /heating/parameters` (geändert)
Body: `{ "komfort"?, "normal"?, "reduziert"?, "neigung"?, "niveau"? }` (Teilangaben erlaubt, `event_at`/`request_id` optional/ignoriert bzw. für Idempotenz nutzbar).

- 201 `{ "status": "created", "item": {...}, "applied": { "<param>": { "from": 20, "to": 21, "ok": true } } }`
- 200 `{ "status": "unchanged", "state": {...} }` (nichts geschrieben)
- 400 `{ "error": "..." }` Validierung/Plausibilität (nichts geschrieben)
- 403 `{ "error": "forbidden" }` nicht in Gruppe
- 502 `{ "error": "...", "partial": true|false, "applied": {...}, "item": {...}|null }` Viessmann-Fehler; `item` gesetzt, wenn tatsächlich geänderte Werte gespeichert wurden

### `POST /heating/parameters/sync`
Body leer. Server liest Live-Werte; weichen sie vom neuesten DynamoDB-Eintrag ab, Eintrag mit `source=viessmann`.
- 201 `{ "status": "created", "item": {...} }`
- 200 `{ "status": "unchanged", "state": {...} }`
- 403 / 502 wie oben

## Frontend-Verhalten

1. Tab Hparam öffnen: Tabelle aus `GET /heating/parameters`; Eingabefelder (inkl. Datum/Uhrzeit) **leer**.
2. Button **Live** (rechts in der Zeile des Submit-Buttons): `GET …/live`, Felder füllen, Datum/Uhrzeit auf jetzt und gesperrt. Weicht der Live-Zustand vom neuesten Tabelleneintrag ab: Hinweis im GUI plus confirm-Popup "Therme weicht von der Tabelle ab – als Eintrag übernehmen?" → bei Ja `POST …/sync`, danach Tabelle neu laden.
3. Submit: clientseitige Plausibilität (bestehend) → confirm "Werte in die Gastherme schreiben?" → `POST /heating/parameters` → Tabelle neu laden; Anzeige von Erfolg, `unchanged`, Teilfehler (`partial`) und 403.
4. User ohne Gruppe: Live funktioniert, Submit liefert 403 → verständliche Meldung.

## Monitoring ("ich möchte informiert werden")

Jeder Schreibversuch loggt strukturiert (Parameter, alt, neu, Ergebnis, HTTP-Status der Commands; keine Tokens/Secrets).  Fehlgeschlagene Schreibversuche erscheinen als Ereignis `heating_parameter_write_failed` in den Lambda-Logs; eine automatische Alarmierung (SNS) gibt es bewusst nicht.
