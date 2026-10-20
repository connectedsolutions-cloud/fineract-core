"""Last-issued share certificate, provisional, and share-serial counters."""

from __future__ import annotations

import re
from typing import Any

_PROVISIONAL = re.compile(r"^CP(\d{8})$")
_CERTIFICATE = re.compile(r"^(\d{5}1A[CP])(\d{2})$")
_SERIAL_PREFIX = {"1": "COMMON", "2": "PREFERRED", "1AC": "COMMON", "1AP": "PREFERRED"}


def counter_seed(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Highest already issued ordinals. Keys are namespace|prefix."""

    counters: dict[str, int] = {}
    for row in rows:
        number = str(row.get("NUMERO_CERTIFICADO") or row.get("certificate_number") or "").strip()
        provisional = _PROVISIONAL.fullmatch(number)
        if provisional:
            _raise(counters, "SHARE_CERTIFICATE_PROVISIONAL|CP", int(provisional.group(1)))
        provisional_column = str(row.get("provisional_number") or "").strip()
        provisional_stored = _PROVISIONAL.fullmatch(provisional_column)
        if provisional_stored:
            _raise(counters, "SHARE_CERTIFICATE_PROVISIONAL|CP", int(provisional_stored.group(1)))
        certificate = _CERTIFICATE.fullmatch(number)
        if certificate:
            _raise(counters, f"SHARE_CERTIFICATE|{certificate.group(1)}", int(certificate.group(2)))
        serial_end = _whole_number(row.get("ACCION_FIN") or row.get("final_share_number") or row.get("share_serial_end"))
        if serial_end is None:
            continue
        share_class = row.get("ID_TIPO_ACCION", row.get("arissto_share_type_id", row.get("share_class_code")))
        prefix = _serial_prefix(share_class)
        if prefix:
            _raise(counters, f"SHARE_SERIAL|{prefix}", serial_end)
    return counters


def _raise(counters: dict[str, int], key: str, value: int) -> None:
    counters[key] = max(counters.get(key, 0), value)


def _serial_prefix(value: Any) -> str | None:
    text = str(value or "").strip()
    if text.endswith(".0"):
        text = text[:-2]
    return _SERIAL_PREFIX.get(text)


def _whole_number(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text.isdigit():
        return None
    return int(text)
