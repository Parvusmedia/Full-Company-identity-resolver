"""Helpers: Pipedrive prevalece — solo escribir campos vacíos."""

from __future__ import annotations

from typing import Any


def is_pd_value_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, float) and value != value:
        return True
    return False


def filter_payload_empty_only(existing_org: dict, desired: dict[str, Any]) -> dict[str, Any]:
    filtered: dict[str, Any] = {}
    skipped_existing: list[str] = []
    skipped_no_noco: list[str] = []
    for key, new_value in desired.items():
        if is_pd_value_empty(new_value):
            skipped_no_noco.append(key)
            continue
        current = existing_org.get(key)
        if is_pd_value_empty(current):
            filtered[key] = new_value
        else:
            skipped_existing.append(key)
    return {
        "payload": filtered,
        "skipped_existing": skipped_existing,
        "skipped_no_noco": skipped_no_noco,
    }
