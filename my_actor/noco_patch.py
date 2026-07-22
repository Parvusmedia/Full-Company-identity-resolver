"""Build safe NocoDB PATCH payloads from resolver results."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from my_actor.match_guards import is_suppressed_linkedin, should_block_published_website
from my_actor.normalization import (
    domain_label,
    extract_registrable_domain,
    is_garbage_website_domain,
    is_insurer_portal_domain,
    is_noise_website_domain,
)
from my_actor.output_normalize import headquarters_text_from, normalize_noco_patch
from my_actor.scoring import name_similarity

# Omit nulls for these when LinkedIn remains so backfilled Noco values are not wiped.
HARVEST_OPTIONAL_FIELDS = frozenset(
    {
        "commercial_name",
        "industry",
        "employee_count",
        "followers",
        "phone",
        "headquarters_text",
    }
)


def domain_ok_for_publish(legal_name: str, domain: str | None, *, country_code: str) -> bool:
    if not domain:
        return False
    if is_noise_website_domain(domain) or is_garbage_website_domain(domain):
        return False
    if is_insurer_portal_domain(domain, legal_name):
        return False
    blocked, _ = should_block_published_website(legal_name, domain, country_code=country_code)
    return not blocked


def website_name_plausible(legal_name: str, domain: str | None) -> bool:
    if not domain:
        return False
    sim = name_similarity(legal_name, domain_label(domain) or "")
    return sim >= 35


def finalize_noco_patch(patch: dict[str, Any], *, clear_harvest_fields: bool) -> dict[str, Any]:
    """Normalize and apply write policy: do not send null harvest fields unless clearing."""
    payload = dict(patch)
    if not clear_harvest_fields:
        linkedin = (payload.get("linkedin_url") or "").strip()
        if linkedin:
            for key in HARVEST_OPTIONAL_FIELDS:
                if key in payload and payload[key] is None:
                    del payload[key]
    return normalize_noco_patch(payload)


def safe_patch_from_result(
    row: dict,
    result,
    *,
    country_code: str = "es",
) -> dict:
    """Apply publish guards and build a Noco PATCH that will not wipe unrelated columns."""
    item = result.to_dataset_item(debug=False)
    legal = item.get("legal_name") or row.get("legal_name") or row.get("Title")
    status = (item.get("match_status") or "not_found").lower()
    website = item.get("website") or None
    domain = item.get("domain") or extract_registrable_domain(website)
    linkedin = item.get("linkedin_url") or None

    if website and not domain_ok_for_publish(legal, domain, country_code=country_code):
        website, domain = None, None
    if website and status in {"not_found", "error"} and not website_name_plausible(legal, domain):
        website, domain = None, None
    if website and status == "partial" and not website_name_plausible(legal, domain):
        website, domain = None, None
    if linkedin and is_suppressed_linkedin(legal, linkedin):
        linkedin = None

    if not website and status in {"not_found"} and linkedin:
        linkedin = None

    if website and not linkedin and status in {"partial", "not_found"}:
        enrichment = "partial"
        status = "partial"
    elif status in {"confirmed", "high_confidence", "probable"} and linkedin:
        enrichment = "enriched"
    elif website or (
        linkedin
        and status in {"probable", "high_confidence", "confirmed", "ambiguous", "partial"}
    ):
        enrichment = "partial" if website and not linkedin else (
            "not_found" if status == "not_found" and not website and not linkedin else status
        )
    else:
        enrichment = "not_found" if status == "not_found" else status

    if not website and not linkedin:
        enrichment = "not_found"
        status = "not_found"

    queries = item.get("google_queries_used") or []
    queries_str = " | ".join(str(q) for q in queries) if isinstance(queries, list) else str(queries)
    now = datetime.now(timezone.utc).isoformat()

    clear_harvest = not linkedin
    raw_patch: dict[str, Any] = {
        "Id": row["Id"],
        "source_id": str(row.get("source_id") or ""),
        "legal_name": legal,
        "Title": legal,
        "linkedin_url": linkedin,
        "website": website,
        "domain": domain,
        "relationship": item.get("relationship") if (linkedin or website) else "unknown",
        "match_status": status if (website or linkedin) else "not_found",
        "confidence": item.get("confidence") if (website or linkedin) else 0,
        "evidence_summary": item.get("evidence_summary"),
        "candidates_found": item.get("candidates_found"),
        "candidates_enriched": item.get("candidates_enriched"),
        "google_queries_used": queries_str,
        "enrichment_status": enrichment,
        "enriched_at": now,
    }
    if item.get("error"):
        raw_patch["error"] = item.get("error")

    if linkedin:
        for key in HARVEST_OPTIONAL_FIELDS:
            if key == "headquarters_text":
                raw_patch[key] = headquarters_text_from(text=item.get("headquarters_text"))
            else:
                raw_patch[key] = item.get(key)
    elif clear_harvest:
        for key in HARVEST_OPTIONAL_FIELDS:
            raw_patch[key] = None

    return finalize_noco_patch(raw_patch, clear_harvest_fields=clear_harvest)
