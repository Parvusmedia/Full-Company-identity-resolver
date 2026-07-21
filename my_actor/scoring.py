"""Explainable pre-score and final-score for LinkedIn company candidates."""

from __future__ import annotations

from typing import Any

from rapidfuzz import fuzz

from .models import CompanyInput, GoogleEvidence, LinkedInCandidate, MatchStatus, Relationship, WebsiteCandidate
from .normalization import (
    contains_branch_terms,
    core_name,
    extract_registrable_domain,
    normalize_text,
    slug_from_linkedin_url,
)


def _clamp(score: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, score))


def name_similarity(a: str | None, b: str | None) -> float:
    na = normalize_text(a or "")
    nb = normalize_text(b or "")
    if not na or not nb:
        return 0.0
    return float(fuzz.token_set_ratio(na, nb))


def position_bonus(position: int | None) -> tuple[float, str | None]:
    if position is None:
        return 0.0, None
    if position == 1:
        return 18.0, "google_position_1"
    if position == 2:
        return 12.0, "google_position_2"
    if position <= 3:
        return 8.0, "google_position_top3"
    if position <= 5:
        return 4.0, "google_position_top5"
    return 0.0, None


def compute_pre_score(
    company: CompanyInput,
    candidate: LinkedInCandidate,
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    core = core_name(company.legal_name)
    slug = candidate.universal_name_guess or slug_from_linkedin_url(candidate.linkedin_url) or ""
    slug_sim = name_similarity(core, slug.replace("-", " "))
    score += slug_sim * 0.35
    reasons.append(f"slug_similarity={slug_sim:.1f}")

    best_title_sim = 0.0
    best_position_bonus = 0.0
    best_position_reason: str | None = None
    location_hit = False
    multi_query_types: set[str] = set()

    for ev in candidate.google_evidences:
        multi_query_types.add(ev.query_type)
        title_sim = name_similarity(core, ev.title or "")
        best_title_sim = max(best_title_sim, title_sim)
        bonus, reason = position_bonus(ev.position)
        if bonus > best_position_bonus:
            best_position_bonus = bonus
            best_position_reason = reason
        loc_blob = f"{ev.title or ''} {ev.snippet or ''}"
        if company.city and normalize_text(company.city) in normalize_text(loc_blob):
            location_hit = True
        if company.province and normalize_text(company.province) in normalize_text(loc_blob):
            location_hit = True
        if contains_branch_terms(ev.title, ev.snippet, slug):
            score -= 12.0
            reasons.append("penalty_branch_terms")

    score += best_title_sim * 0.30
    reasons.append(f"title_similarity={best_title_sim:.1f}")
    score += best_position_bonus
    if best_position_reason:
        reasons.append(best_position_reason)

    if len(multi_query_types) > 1:
        score += 10.0
        reasons.append("found_in_multiple_query_types")
    elif len(candidate.google_evidences) > 1:
        score += 5.0
        reasons.append("found_in_multiple_results")

    if location_hit:
        score += 8.0
        reasons.append("city_or_province_in_google")

    return _clamp(score), reasons


def compute_final_score(
    company: CompanyInput,
    candidate: LinkedInCandidate,
    website_candidates: list[WebsiteCandidate],
) -> tuple[float, list[str], Relationship]:
    reasons = list(candidate.pre_score_reasons)
    score = candidate.pre_score * 0.45
    reasons.append(f"pre_score_contribution={candidate.pre_score * 0.45:.1f}")
    relationship = Relationship.UNKNOWN

    element = candidate.harvest or {}
    harvest_name = element.get("name") if isinstance(element, dict) else None
    universal = element.get("universalName") if isinstance(element, dict) else candidate.universal_name_guess
    harvest_website = element.get("website") if isinstance(element, dict) else None
    description = element.get("description") if isinstance(element, dict) else None
    tagline = element.get("tagline") if isinstance(element, dict) else None
    active = element.get("active") if isinstance(element, dict) else None
    verified = element.get("pageVerified") if isinstance(element, dict) else None
    employee_count = element.get("employeeCount") if isinstance(element, dict) else None
    followers = element.get("followerCount") if isinstance(element, dict) else None
    hq = None
    if isinstance(element, dict):
        hq = element.get("headquarter") or element.get("headquarters")

    core = core_name(company.legal_name)

    if harvest_name:
        name_sim = name_similarity(core, str(harvest_name))
        score += name_sim * 0.25
        reasons.append(f"harvest_name_similarity={name_sim:.1f}")
        if name_sim >= 90:
            relationship = Relationship.SAME_ENTITY
        elif name_sim >= 75:
            relationship = Relationship.COMMERCIAL_BRAND
        elif name_sim < 45:
            relationship = Relationship.REQUIRES_REVIEW

    if universal:
        uni_sim = name_similarity(core, str(universal).replace("-", " "))
        score += uni_sim * 0.10
        reasons.append(f"universal_name_similarity={uni_sim:.1f}")

    google_domain = None
    if website_candidates:
        google_domain = website_candidates[0].domain
    harvest_domain = extract_registrable_domain(str(harvest_website) if harvest_website else None)

    if google_domain and harvest_domain:
        if google_domain == harvest_domain:
            score += 18.0
            reasons.append("exact_domain_match")
            if relationship in {Relationship.UNKNOWN, Relationship.REQUIRES_REVIEW}:
                relationship = Relationship.SAME_ENTITY
        else:
            score -= 15.0
            reasons.append("domain_conflict")
            if relationship == Relationship.SAME_ENTITY:
                relationship = Relationship.REQUIRES_REVIEW
    elif harvest_domain and not google_domain:
        score += 4.0
        reasons.append("harvest_website_present")
    elif google_domain and not harvest_domain:
        score += 2.0
        reasons.append("google_website_present_only")

    # Headquarters / city
    hq_text = ""
    if isinstance(hq, dict):
        hq_text = " ".join(
            str(hq.get(k) or "")
            for k in ("city", "geographicArea", "region", "country", "line1", "description")
        )
    elif isinstance(hq, str):
        hq_text = hq
    loc_blob = normalize_text(f"{hq_text} {description or ''} {tagline or ''}")
    if company.city and normalize_text(company.city) in loc_blob:
        score += 6.0
        reasons.append("city_match")
    if company.province and normalize_text(company.province) in loc_blob:
        score += 4.0
        reasons.append("province_match")

    if description:
        desc_sim = name_similarity(core, description[:300])
        if desc_sim >= 60:
            score += 4.0
            reasons.append("description_mentions_name")

    industries = element.get("industries") if isinstance(element, dict) else None
    if industries:
        score += 2.0
        reasons.append("industry_present")
    if employee_count:
        score += 2.0
        reasons.append("employees_present")
    if followers:
        score += 1.5
        reasons.append("followers_present")
    if active is True:
        score += 3.0
        reasons.append("page_active")
    elif active is False:
        score -= 8.0
        reasons.append("page_inactive")
    if verified is True:
        score += 4.0
        reasons.append("page_verified")

    if contains_branch_terms(harvest_name, description, tagline, candidate.linkedin_url):
        score -= 10.0
        reasons.append("possible_branch_or_subsidiary")
        if relationship == Relationship.SAME_ENTITY:
            relationship = Relationship.BRANCH

    return _clamp(score), reasons, relationship


def classify_match_status(
    best_score: float,
    second_score: float | None,
    *,
    has_candidates: bool,
) -> MatchStatus:
    if not has_candidates or best_score < 40:
        return MatchStatus.NOT_FOUND

    gap = None if second_score is None else (best_score - second_score)
    status: MatchStatus
    if best_score >= 90:
        status = MatchStatus.CONFIRMED
    elif best_score >= 78:
        status = MatchStatus.HIGH_CONFIDENCE
    elif best_score >= 60:
        status = MatchStatus.PROBABLE
    elif best_score >= 40:
        status = MatchStatus.AMBIGUOUS
    else:
        status = MatchStatus.NOT_FOUND

    # Close race between top two candidates reduces certainty
    if gap is not None and gap < 6 and status in {
        MatchStatus.CONFIRMED,
        MatchStatus.HIGH_CONFIDENCE,
        MatchStatus.PROBABLE,
    }:
        if status == MatchStatus.CONFIRMED:
            status = MatchStatus.HIGH_CONFIDENCE
        elif status == MatchStatus.HIGH_CONFIDENCE:
            status = MatchStatus.PROBABLE
        else:
            status = MatchStatus.AMBIGUOUS
    return status


def confidence_from_status(score: float, status: MatchStatus) -> float:
    if status == MatchStatus.NOT_FOUND:
        return min(score, 35.0)
    return round(_clamp(score), 2)


def build_website_candidates(evidences: list[GoogleEvidence], legal_name: str) -> list[WebsiteCandidate]:
    by_domain: dict[str, WebsiteCandidate] = {}
    core = core_name(legal_name)
    for ev in evidences:
        domain = extract_registrable_domain(ev.url)
        if not domain:
            continue
        existing = by_domain.get(domain)
        if existing is None:
            existing = WebsiteCandidate(url=ev.url, domain=domain, google_evidences=[ev], score=0.0)
            by_domain[domain] = existing
        else:
            existing.google_evidences.append(ev)

    candidates = list(by_domain.values())
    for cand in candidates:
        score = 0.0
        for ev in cand.google_evidences:
            bonus, _ = position_bonus(ev.position)
            score += bonus
            score += name_similarity(core, ev.title or "") * 0.2
            if ev.query_type == "website":
                score += 8.0
        # Prefer domains that resemble the company core name
        score += name_similarity(core, (cand.domain or "").split(".")[0]) * 0.3
        cand.score = score

    # Sort list — do NOT index by score (ties must not overwrite)
    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates


def candidate_debug_dict(candidate: LinkedInCandidate, *, debug: bool) -> dict[str, Any]:
    data: dict[str, Any] = {
        "linkedin_url": candidate.linkedin_url,
        "universal_name_guess": candidate.universal_name_guess,
        "pre_score": candidate.pre_score,
        "pre_score_reasons": candidate.pre_score_reasons,
        "final_score": candidate.final_score,
        "score_reasons": candidate.score_reasons,
        "relationship": candidate.relationship.value,
        "harvest_error": candidate.harvest_error,
        "google_evidences": [e.model_dump(mode="json") for e in candidate.google_evidences],
        "harvest_summary": None,
    }
    if candidate.harvest:
        data["harvest_summary"] = {
            "name": candidate.harvest.get("name"),
            "universalName": candidate.harvest.get("universalName"),
            "website": candidate.harvest.get("website"),
            "linkedinUrl": candidate.harvest.get("linkedinUrl"),
            "employeeCount": candidate.harvest.get("employeeCount"),
            "followerCount": candidate.harvest.get("followerCount"),
            "active": candidate.harvest.get("active"),
            "pageVerified": candidate.harvest.get("pageVerified"),
        }
    if debug:
        data["raw_harvest"] = candidate.harvest
    return data
