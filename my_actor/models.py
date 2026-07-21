"""Pydantic models and typed dataclasses for the Actor."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class Relationship(str, Enum):
    SAME_ENTITY = "same_entity"
    COMMERCIAL_BRAND = "commercial_brand"
    PARENT_COMPANY = "parent_company"
    SUBSIDIARY = "subsidiary"
    BRANCH = "branch"
    UNRELATED = "unrelated"
    UNKNOWN = "unknown"
    REQUIRES_REVIEW = "requires_review"


class MatchStatus(str, Enum):
    CONFIRMED = "confirmed"
    HIGH_CONFIDENCE = "high_confidence"
    PROBABLE = "probable"
    AMBIGUOUS = "ambiguous"
    PARTIAL = "partial"
    NOT_FOUND = "not_found"
    ERROR = "error"


class CompanyInput(BaseModel):
    source_id: str | None = None
    legal_name: str
    tax_id: str | None = None
    city: str | None = None
    province: str | None = None
    country: str | None = "España"
    # Optional prior enrichment (from NocoDB) — used to skip already-good rows.
    existing_website: str | None = None
    existing_domain: str | None = None
    existing_match_status: str | None = None
    existing_linkedin_url: str | None = None

    @field_validator("legal_name")
    @classmethod
    def strip_legal_name(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("legal_name must not be empty")
        return cleaned


class ActorSettings(BaseModel):
    """Runtime settings derived from Actor input + environment."""

    apify_token: str | None = None
    google_actor_id: str = "apify/google-search-scraper"
    google_results_per_page: int = 10
    country_code: str = "es"
    language_code: str = "es"
    max_harvest_candidates: int = 2
    harvest_api_key: str | None = None
    harvest_concurrency: int = 3
    harvest_pre_score_gap: float = 15.0
    fallback_google_by_website: bool = True
    fallback_confidence_threshold: int = 78
    use_ai_for_ambiguous: bool = False
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    ai_confidence_threshold: int = 78
    batch_size: int = 20
    debug: bool = False
    validate_websites: bool = True
    max_website_probes: int = 2
    # Last resort after Google Search + AI Overview found no publishable website.
    fallback_google_maps: bool = True
    google_maps_actor_id: str = "compass/crawler-google-places"
    google_maps_max_places: int = 5
    skip_if_good_website: bool = True
    defer_core_linkedin: bool = True


class GoogleEvidence(BaseModel):
    query: str
    query_type: str
    position: int | None = None
    title: str | None = None
    snippet: str | None = None
    url: str
    domain: str | None = None


class AiOverviewEvidence(BaseModel):
    query: str
    content: str
    sources: list[dict[str, Any]] = Field(default_factory=list)


class LinkedInCandidate(BaseModel):
    linkedin_url: str
    universal_name_guess: str | None = None
    google_evidences: list[GoogleEvidence] = Field(default_factory=list)
    pre_score: float = 0.0
    pre_score_reasons: list[str] = Field(default_factory=list)
    final_score: float = 0.0
    score_reasons: list[str] = Field(default_factory=list)
    harvest: dict[str, Any] | None = None
    harvest_error: str | None = None
    relationship: Relationship = Relationship.UNKNOWN


class WebsiteCandidate(BaseModel):
    url: str
    domain: str | None = None
    google_evidences: list[GoogleEvidence] = Field(default_factory=list)
    score: float = 0.0
    homepage_probe: dict[str, Any] | None = None


class AiDecision(BaseModel):
    selected_candidate_index: int | None = None
    commercial_name: str | None = None
    relationship: Relationship | None = None
    confidence: int | None = None
    reason: str | None = None
    raw: dict[str, Any] | None = None
    error: str | None = None


class ResolutionResult(BaseModel):
    source_id: str | None = None
    legal_name: str
    tax_id: str | None = None
    commercial_name: str | None = None
    linkedin_url: str | None = None
    linkedin_id: str | None = None
    universal_name: str | None = None
    linkedin_name: str | None = None
    website: str | None = None
    domain: str | None = None
    google_website: str | None = None
    harvest_website: str | None = None
    description: str | None = None
    tagline: str | None = None
    industry: str | None = None
    industries: list[Any] | None = None
    specialties: list[Any] | None = None
    employee_count: int | None = None
    employee_range: str | None = None
    employee_range_start: int | None = None
    employee_range_end: int | None = None
    followers: int | None = None
    founded_year: int | None = None
    headquarters: dict[str, Any] | list[Any] | None = None
    headquarters_text: str | None = None
    headquarters_city: str | None = None
    headquarters_region: str | None = None
    headquarters_country: str | None = None
    locations: list[Any] | None = None
    phone: str | None = None
    logo: str | None = None
    active: bool | None = None
    page_verified: bool | None = None
    relationship: str = Relationship.UNKNOWN.value
    match_status: str = MatchStatus.NOT_FOUND.value
    confidence: float = 0.0
    evidence_summary: str | None = None
    candidates_found: int = 0
    candidates_enriched: int = 0
    google_queries_used: list[str] = Field(default_factory=list)
    harvest_queries_used: list[str] = Field(default_factory=list)
    enrichment_status: str = "pending"
    enriched_at: str | None = None
    error: str | None = None
    # Debug-only fields (stripped when debug=false)
    candidates: list[dict[str, Any]] | None = None
    website_candidates: list[dict[str, Any]] | None = None
    ai_decision: dict[str, Any] | None = None

    def to_dataset_item(self, *, debug: bool = False) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        if not debug:
            data.pop("candidates", None)
            data.pop("website_candidates", None)
            data.pop("ai_decision", None)
            # Ensure no nested raw_harvest leaks into normal output
            for key in list(data.keys()):
                if key.startswith("raw_"):
                    data.pop(key, None)
        else:
            # Keep candidates as provided; raw_harvest is nested inside each candidate
            pass
        if not data.get("enriched_at"):
            data["enriched_at"] = datetime.now(timezone.utc).isoformat()
        return data
