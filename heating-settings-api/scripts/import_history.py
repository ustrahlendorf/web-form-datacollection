#!/usr/bin/env python3
"""Einmaliger Import der historischen Heizungs-Einstellungen (aus Apple Notes) nach DynamoDB.

Standard ist ein **Dry-Run**: es werden keine AWS-Aufrufe gemacht, nur eine
Zusammenfassung ausgegeben. Geschrieben wird erst mit ``--apply``.

Die CSV enthält persönliche Daten und gehört nicht ins Repo; der Pfad wird
per ``--csv`` übergeben.

Beispiel:
    python scripts/import_history.py --csv /pfad/heizung_events.csv
    python scripts/import_history.py --csv /pfad/heizung_events.csv \\
        --table <TableName> --profile <profil> --region eu-central-1 --apply

Idempotent: Die Schlüssel sind deterministisch, bestehende Einträge werden
nicht überschrieben (``attribute_not_exists``), ein zweiter Lauf legt nichts an.
"""
import argparse
import csv
import hashlib
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambda_src"))
import logic  # noqa: E402

SOURCE = "apple-notes-import"
ONE_DECIMAL = ("neigung", "niveau")


def _num(param: str, value: str) -> Decimal:
    number = float(value)
    if param in ONE_DECIMAL:
        return Decimal(str(number)).quantize(Decimal("0.1"))
    if number != int(number):
        raise ValueError(f"{param}: ganze Zahl erwartet, erhalten {value}")
    return Decimal(int(number))


def _created_at_local(local_iso: str) -> str:
    """Erstelldatum der Notiz (Ortszeit), auf Minuten gekürzt, wie bei API-Einträgen."""
    return datetime.strptime(local_iso, "%Y-%m-%dT%H:%M:%S").strftime("%Y-%m-%dT%H:%M")


def row_to_item(row: dict, pk: str) -> dict:
    """Wandelt eine CSV-Zeile in ein DynamoDB-Item (gleiches Modell wie die API)."""
    quality = []
    if row["event_time"]:
        event_at = f"{row['event_date']}T{row['event_time']}"
    else:
        event_at = f"{row['event_date']}T00:00"
        quality.append("time_unknown")
    if row.get("flags"):
        quality.extend(f for f in row["flags"].split(",") if f)
    for column in ("prev_mismatch", "unmarked_change"):
        if row.get(column):
            quality.extend(f"{column}:{p}" for p in row[column].split(","))

    request_id = hashlib.sha256(f"import|{row['created_at']}|{event_at}".encode()).hexdigest()[:10]
    prev = {p: _num(p, row[f"{p}_prev"]) for p in logic.PARAMS if row.get(f"{p}_prev")}
    changed = [p for p in logic.PARAMS if p in (row.get("changed") or "").split(",")]

    return {
        "PK": pk,
        "SK": logic.sort_key(event_at, request_id),
        "event_at": event_at,
        "created_at": _created_at_local(row["created_at"]),
        **{p: _num(p, row[p]) for p in logic.PARAMS},
        "prev": prev,
        "changed": changed,
        "quality": quality,
        "source": SOURCE,
    }


def load_items(csv_path: Path, pk: str) -> list[dict]:
    with open(csv_path, newline="", encoding="utf-8") as fh:
        items = [row_to_item(row, pk) for row in csv.DictReader(fh)]
    items.sort(key=lambda i: i["SK"])
    keys = [i["SK"] for i in items]
    if len(keys) != len(set(keys)):
        raise ValueError("doppelte Sortierschlüssel in der CSV")
    return items


def summarize(items: list[dict]) -> str:
    flagged = sum(1 for i in items if i["quality"])
    return (f"{len(items)} Einträge, {items[0]['event_at']} bis {items[-1]['event_at']}, "
            f"{flagged} mit Qualitätshinweis (quality)")


def apply(items: list[dict], table_name: str, profile: str | None, region: str | None) -> None:
    import boto3
    from botocore.exceptions import ClientError

    session = boto3.Session(profile_name=profile, region_name=region)
    table = session.resource("dynamodb").Table(table_name)
    created = skipped = 0
    for item in items:
        try:
            table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
            )
            created += 1
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            skipped += 1
    print(f"Fertig: {created} angelegt, {skipped} bereits vorhanden.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True, type=Path, help="Pfad zur heizung_events.csv")
    ap.add_argument("--system-id", default="haus", help="Anlagenkennung (PK = SYSTEM#<id>), Standard: haus")
    ap.add_argument("--table", help="DynamoDB-Tabellenname (Stack-Output TableName)")
    ap.add_argument("--profile", help="AWS-Profil")
    ap.add_argument("--region", help="AWS-Region")
    ap.add_argument("--apply", action="store_true", help="wirklich schreiben (sonst Dry-Run)")
    args = ap.parse_args(argv)

    items = load_items(args.csv, f"SYSTEM#{args.system_id}")
    print(summarize(items))
    if not args.apply:
        print("Dry-Run: es wurde nichts geschrieben. Erstes und letztes Item:")
        for item in (items[0], items[-1]):
            print(" ", logic.to_jsonable(item))
        return 0
    if not args.table:
        ap.error("--table ist mit --apply erforderlich")
    apply(items, args.table, args.profile, args.region)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
