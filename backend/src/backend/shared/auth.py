"""JWT-Claim-Helfer für API-Gateway-HTTP-API-Events (Cognito)."""
import re
from typing import Any

WRITER_GROUP = "heating-parameter-writers"


def get_claims(event: dict) -> dict:
    """Liefert die JWT-Claims aus dem Event (payload v2 ``jwt.claims`` oder v1 ``claims``)."""
    authorizer = (event.get("requestContext") or {}).get("authorizer") or {}
    jwt_block = authorizer.get("jwt")
    claims = jwt_block.get("claims") if isinstance(jwt_block, dict) else None
    if not isinstance(claims, dict):
        claims = authorizer.get("claims")
    return claims if isinstance(claims, dict) else {}


def get_user_id(event: dict) -> str | None:
    sub = get_claims(event).get("sub")
    return sub if isinstance(sub, str) and sub else None


def parse_groups(raw: Any) -> list[str]:
    """``cognito:groups`` kommt je nach Gateway als Liste oder als String wie ``[a b]``."""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        return [str(g) for g in raw]
    text = str(raw).strip().strip("[]")
    return [g for g in re.split(r"[\s,]+", text) if g]


def is_in_group(event: dict, group: str = WRITER_GROUP) -> bool:
    return group in parse_groups(get_claims(event).get("cognito:groups"))
