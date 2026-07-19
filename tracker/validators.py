"""Reusable, migration-safe validators for aviation identifiers and timezones."""

import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError


def _validate_code(value: str, *, length: int, label: str) -> None:
    if value and not re.fullmatch(rf"[A-Za-z0-9]{{{length}}}", value):
        raise ValidationError(f"{label} must contain exactly {length} letters or digits.")


def validate_iata_code(value: str) -> None:
    _validate_code(value, length=3, label="IATA code")


def validate_icao_code(value: str) -> None:
    _validate_code(value, length=4, label="ICAO code")


def validate_iana_timezone(value: str) -> None:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationError("Enter a valid IANA timezone, for example Europe/London.") from exc
