"""Viessmann-Zugangsdaten aus Secrets Manager in die Prozess-Umgebung laden."""
import json
import os

_KEYS = ("VIESSMANN_CLIENT_ID", "VIESSMANN_EMAIL", "VIESSMANN_PASSWORD")


def load_into_env(secrets_client) -> None:
    """Liest das Secret (ARN aus ``VIESSMANN_CREDENTIALS_SECRET_ARN``) und setzt die Env-Variablen.

    Wirft ``ValueError`` bei Konfigurationsfehlern (ohne Secret-Inhalte in der Meldung).
    """
    secret_arn = os.environ.get("VIESSMANN_CREDENTIALS_SECRET_ARN")
    if not secret_arn:
        raise ValueError("VIESSMANN_CREDENTIALS_SECRET_ARN is not set")
    secret_str = secrets_client.get_secret_value(SecretId=secret_arn).get("SecretString")
    if not secret_str:
        raise ValueError("Secret has no SecretString")
    data = json.loads(secret_str)
    for key in _KEYS:
        if not data.get(key):
            raise ValueError(f"Secret missing required key: {key}")
    for key in _KEYS:
        os.environ[key] = data[key]
