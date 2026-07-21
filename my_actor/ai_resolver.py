"""Optional AI disambiguation for ambiguous LinkedIn candidates."""

from __future__ import annotations

import json
from typing import Any

from apify import Actor

from .models import AiDecision, CompanyInput, LinkedInCandidate, Relationship, WebsiteCandidate


def _candidate_payload(candidate: LinkedInCandidate, index: int) -> dict[str, Any]:
    harvest = candidate.harvest or {}
    return {
        "index": index,
        "linkedin_url": candidate.linkedin_url,
        "pre_score": candidate.pre_score,
        "final_score": candidate.final_score,
        "score_reasons": candidate.score_reasons[:12],
        "google_titles": [e.title for e in candidate.google_evidences if e.title][:5],
        "harvest_name": harvest.get("name"),
        "universal_name": harvest.get("universalName"),
        "website": harvest.get("website"),
        "description": (harvest.get("description") or "")[:500] or None,
        "headquarter": harvest.get("headquarter") or harvest.get("headquarters"),
        "industries": harvest.get("industries"),
    }


async def resolve_with_ai(
    company: CompanyInput,
    candidates: list[LinkedInCandidate],
    website_candidates: list[WebsiteCandidate],
    *,
    api_key: str | None,
    model: str,
) -> AiDecision:
    if not api_key:
        return AiDecision(error="missing_openai_api_key")
    if not candidates:
        return AiDecision(error="no_candidates")

    try:
        from openai import AsyncOpenAI
    except Exception as exc:  # noqa: BLE001
        return AiDecision(error=f"openai_import_failed:{type(exc).__name__}")

    payload = {
        "legal_name": company.legal_name,
        "tax_id": company.tax_id,
        "city": company.city,
        "province": company.province,
        "country": company.country,
        "website_candidates": [
            {"url": w.url, "domain": w.domain, "score": w.score} for w in website_candidates[:5]
        ],
        "candidates": [_candidate_payload(c, i) for i, c in enumerate(candidates)],
        "instructions": (
            "Choose the single best LinkedIn company page for the Spanish legal entity. "
            "Return JSON only with keys: selected_candidate_index, commercial_name, "
            "relationship, confidence, reason. relationship must be one of: "
            "same_entity, commercial_brand, parent_company, subsidiary, branch, "
            "unrelated, unknown, requires_review."
        ),
    }

    client = AsyncOpenAI(api_key=api_key)
    try:
        response = await client.chat.completions.create(
            model=model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a careful company-identity resolver for Spanish firms. "
                        "Prefer exact legal/commercial identity matches. Never invent URLs."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        )
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
    except Exception as exc:  # noqa: BLE001
        Actor.log.warning("OpenAI disambiguation failed: %s", type(exc).__name__)
        return AiDecision(error=type(exc).__name__)

    index = data.get("selected_candidate_index")
    try:
        index_int = int(index) if index is not None else None
    except (TypeError, ValueError):
        index_int = None
    if index_int is not None and (index_int < 0 or index_int >= len(candidates)):
        return AiDecision(error="selected_candidate_index_out_of_range", raw=data)

    relationship = None
    rel_raw = data.get("relationship")
    if isinstance(rel_raw, str):
        try:
            relationship = Relationship(rel_raw)
        except ValueError:
            relationship = Relationship.REQUIRES_REVIEW

    confidence = data.get("confidence")
    try:
        confidence_int = int(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        confidence_int = None

    return AiDecision(
        selected_candidate_index=index_int,
        commercial_name=data.get("commercial_name"),
        relationship=relationship,
        confidence=confidence_int,
        reason=data.get("reason"),
        raw=data,
    )
