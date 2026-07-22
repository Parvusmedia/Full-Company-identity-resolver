"""Normalize resolver output immediately before dataset / NocoDB writes."""

from __future__ import annotations

import ast
import json
from typing import Any, Callable

from my_actor.harvest import (
    harvest_headquarters_fields,
    harvest_logo_url,
    harvest_phone,
    industry_name_from_value,
)
from my_actor.normalization import (
    extract_registrable_domain,
    normalize_homepage_url,
    normalize_linkedin_company_url,
)

_OBJECT_REPR_MARKERS = ("'id':", '"id":', "urn:li:", "'name':", '"name":')
_DICT_REPR_RE = None


def _dict_repr_re():
    global _DICT_REPR_RE
    if _DICT_REPR_RE is None:
        import re

        _DICT_REPR_RE = re.compile(r"""^\s*[\{\[]\s*['\"]?\w+['\"]?\s*:""")
    return _DICT_REPR_RE


def _looks_like_object_repr(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped[0] not in "{[":
        return False
    if any(marker in stripped for marker in _OBJECT_REPR_MARKERS):
        return True
    return bool(_dict_repr_re().match(stripped))


def _parse_object_blob(text: str) -> Any | None:
    try:
        return ast.literal_eval(text)
    except (SyntaxError, ValueError):
        try:
            return json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None


def plain_string(
    value: Any,
    *,
    prefer_keys: tuple[str, ...] = ("name", "localizedName", "title", "label", "text", "value"),
) -> str | None:
    """Coerce Harvest scalars / named dicts / accidental repr blobs to a plain string."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in prefer_keys:
            part = value.get(key)
            if part is not None and str(part).strip():
                return str(part).strip()
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            text = plain_string(item, prefer_keys=prefer_keys)
            if text:
                return text
        return None
    if not isinstance(value, str):
        return plain_string(str(value), prefer_keys=prefer_keys)

    text = value.strip()
    if not text:
        return None
    if _looks_like_object_repr(text):
        parsed = _parse_object_blob(text)
        if parsed is not None:
            recovered = plain_string(parsed, prefer_keys=prefer_keys)
            if recovered:
                return recovered
        return None
    return text


def plain_string_list(
    value: Any,
    *,
    item_extractor: Callable[[Any], str | None] | None = None,
) -> list[str] | None:
    extract = item_extractor or plain_string
    if value is None:
        return None
    if isinstance(value, str):
        parsed = _parse_object_blob(value) if _looks_like_object_repr(value) else None
        value = parsed if parsed is not None else [value]
    if not isinstance(value, (list, tuple)):
        name = extract(value)
        return [name] if name else None

    names: list[str] = []
    for item in value:
        name = extract(item)
        if name and name not in names:
            names.append(name)
    return names or None


def headquarters_text_from(*, text: Any = None, hq: Any = None) -> str | None:
    """Build a human-readable HQ line; never return dict repr strings."""
    if isinstance(text, dict):
        hq = text
        text = None

    cleaned = plain_string(text)
    if cleaned and not _looks_like_object_repr(cleaned):
        return cleaned

    if hq is None and isinstance(text, str) and _looks_like_object_repr(text):
        hq = _parse_object_blob(text)
    if isinstance(hq, list) and hq:
        hq = hq[0]

    if isinstance(hq, dict):
        fields = harvest_headquarters_fields({"headquarter": hq})
        return fields.get("headquarters_text") or plain_string(hq.get("description"))

    if isinstance(hq, str):
        return hq.strip() or None
    return None


def headquarters_part(value: Any, *, key: str) -> str | None:
    if isinstance(value, dict):
        direct = plain_string(value.get(key))
        if direct:
            return direct
        parsed = value.get("parsed")
        if isinstance(parsed, dict):
            mapped = {
                "city": parsed.get("city"),
                "region": parsed.get("state") or parsed.get("region"),
                "country": parsed.get("country") or parsed.get("countryFull") or parsed.get("countryCode"),
            }
            return plain_string(mapped.get(key))
    return plain_string(value)


def location_label(location: Any) -> str | None:
    if isinstance(location, str):
        return location.strip() or None
    if not isinstance(location, dict):
        return plain_string(location)

    parsed = location.get("parsed")
    if isinstance(parsed, dict):
        text = parsed.get("text")
        if text:
            return str(text).strip()

    for key in ("description", "city", "geographicArea", "country", "line1"):
        part = location.get(key)
        if part:
            return str(part).strip()

    parts = [
        location.get("line1"),
        location.get("city"),
        location.get("geographicArea"),
        location.get("country"),
    ]
    joined = ", ".join(str(p).strip() for p in parts if p)
    return joined or None


def location_text_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    items = value if isinstance(value, list) else [value]
    labels: list[str] = []
    for item in items:
        label = location_label(item)
        if label and label not in labels:
            labels.append(label)
    return labels or None


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_output_item(data: dict[str, Any], *, debug: bool = False) -> dict[str, Any]:
    """Sanitize a dataset row immediately before Actor.push_data / export."""
    out = dict(data)

    for key in (
        "legal_name",
        "commercial_name",
        "linkedin_name",
        "tagline",
        "description",
        "evidence_summary",
        "error",
        "employee_range",
        "universal_name",
        "tax_id",
        "linkedin_id",
        "relationship",
        "match_status",
        "enrichment_status",
    ):
        if key in out:
            out[key] = plain_string(out.get(key))

    out["industry"] = industry_name_from_value(out.get("industry"))
    out["industries"] = plain_string_list(out.get("industries"), item_extractor=industry_name_from_value)
    out["specialties"] = plain_string_list(out.get("specialties"))

    if out.get("phone") is not None:
        out["phone"] = harvest_phone({"phone": out.get("phone")})
    if out.get("logo") is not None:
        out["logo"] = harvest_logo_url({"logo": out.get("logo")})

    hq = out.get("headquarters")
    out["headquarters_text"] = headquarters_text_from(text=out.get("headquarters_text"), hq=hq)
    out["headquarters_city"] = headquarters_part(out.get("headquarters_city"), key="city") or headquarters_part(
        hq, key="city"
    )
    out["headquarters_region"] = headquarters_part(out.get("headquarters_region"), key="region") or headquarters_part(
        hq, key="region"
    )
    out["headquarters_country"] = headquarters_part(out.get("headquarters_country"), key="country") or headquarters_part(
        hq, key="country"
    )

    for url_key in ("website", "google_website", "harvest_website"):
        raw = out.get(url_key)
        if raw:
            out[url_key] = normalize_homepage_url(str(raw))
    if out.get("linkedin_url"):
        out["linkedin_url"] = normalize_linkedin_company_url(str(out["linkedin_url"]))
    if out.get("logo") and str(out["logo"]).startswith("http"):
        out["logo"] = str(out["logo"]).strip()

    out["domain"] = extract_registrable_domain(out.get("website") or out.get("domain"))

    for int_key in (
        "employee_count",
        "followers",
        "founded_year",
        "employee_range_start",
        "employee_range_end",
        "candidates_found",
        "candidates_enriched",
    ):
        if int_key in out:
            out[int_key] = _to_int(out.get(int_key))
    if "confidence" in out:
        out["confidence"] = _to_float(out.get("confidence")) or 0.0

    queries = out.get("google_queries_used")
    if isinstance(queries, list):
        out["google_queries_used"] = [str(q) for q in queries if q is not None]
    elif queries is not None:
        out["google_queries_used"] = [str(queries)]

    harvest_queries = out.get("harvest_queries_used")
    if isinstance(harvest_queries, list):
        out["harvest_queries_used"] = [str(q) for q in harvest_queries if q is not None]
    elif harvest_queries is not None:
        out["harvest_queries_used"] = [str(harvest_queries)]

    if out.get("locations") is not None:
        out["locations"] = location_text_list(out["locations"])

    if not debug:
        # Flat exports should not carry raw nested Harvest HQ blobs.
        out["headquarters"] = None

    return out


def normalize_noco_patch(patch: dict[str, Any]) -> dict[str, Any]:
    """Sanitize a NocoDB PATCH payload immediately before HTTP write."""
    out = dict(patch)

    for key in (
        "legal_name",
        "Title",
        "commercial_name",
        "domain",
        "evidence_summary",
        "error",
        "relationship",
        "match_status",
        "enrichment_status",
        "google_queries_used",
        "source_id",
    ):
        if key in out and out[key] is not None:
            out[key] = plain_string(out[key])

    out["industry"] = industry_name_from_value(out.get("industry"))
    if out.get("phone") is not None:
        out["phone"] = harvest_phone({"phone": out.get("phone")})
    out["headquarters_text"] = headquarters_text_from(text=out.get("headquarters_text"))

    if out.get("website"):
        out["website"] = normalize_homepage_url(str(out["website"]))
        out["domain"] = extract_registrable_domain(out.get("website") or out.get("domain"))
    elif out.get("domain"):
        out["domain"] = extract_registrable_domain(str(out["domain"]))
    if out.get("linkedin_url"):
        out["linkedin_url"] = normalize_linkedin_company_url(str(out["linkedin_url"]))

    for int_key in ("employee_count", "followers", "candidates_found", "candidates_enriched"):
        if int_key in out:
            out[int_key] = _to_int(out.get(int_key))
    if "confidence" in out:
        out["confidence"] = _to_float(out.get("confidence")) or 0.0

    return out
