"""End-to-end company identity resolution pipeline."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from apify import Actor

from .ai_resolver import resolve_with_ai
from .google_search import (
    WEBSITE_QUERY,
    build_domain_fallback_query,
    build_initial_queries,
    evidences_for_company,
    extract_domains_from_text,
    filter_linkedin_evidences,
    filter_website_evidences,
    run_google_searches,
)
from .harvest import (
    enrich_candidates_with_harvest,
    harvest_employee_range,
    harvest_founded_year,
    harvest_headquarters_fields,
    harvest_industry,
    harvest_logo_url,
    harvest_phone,
    search_company_with_harvest,
)
from .homepage import HOMEPAGE_QUERY, scrape_homepage_linkedin_urls
from .models import (
    ActorSettings,
    CompanyInput,
    GoogleEvidence,
    LinkedInCandidate,
    MatchStatus,
    Relationship,
    ResolutionResult,
)
from .normalization import (
    core_name,
    extract_registrable_domain,
    is_website_noise_domain,
    normalize_linkedin_company_url,
    remove_legal_forms,
    slug_from_linkedin_url,
)
from .scoring import (
    build_website_candidates,
    candidate_debug_dict,
    classify_match_status,
    compute_final_score,
    compute_pre_score,
    confidence_from_status,
)


def parse_input_companies(raw_input: dict[str, Any]) -> list[CompanyInput]:
    """Parse Actor input. `companies` takes priority over `queries`."""
    companies_raw = raw_input.get("companies")
    if isinstance(companies_raw, list) and companies_raw:
        companies: list[CompanyInput] = []
        for item in companies_raw:
            if isinstance(item, str):
                companies.append(CompanyInput(legal_name=item))
            elif isinstance(item, dict):
                legal = item.get("legal_name") or item.get("name") or item.get("query")
                if not legal:
                    continue
                companies.append(
                    CompanyInput(
                        source_id=item.get("source_id"),
                        legal_name=str(legal),
                        tax_id=item.get("tax_id"),
                        city=item.get("city"),
                        province=item.get("province"),
                        country=item.get("country") or "España",
                    )
                )
        if companies:
            return companies

    queries = raw_input.get("queries")
    if isinstance(queries, list):
        lines = [str(q) for q in queries]
    elif isinstance(queries, str):
        lines = queries.splitlines()
    else:
        lines = []

    companies = []
    for line in lines:
        name = line.strip()
        if not name:
            continue
        companies.append(CompanyInput(legal_name=name))
    return companies


def settings_from_input(raw_input: dict[str, Any], *, env_token: str | None, env_harvest: str | None, env_openai: str | None) -> ActorSettings:
    return ActorSettings(
        apify_token=(env_token or raw_input.get("apify_token") or None),
        google_actor_id=raw_input.get("google_actor_id") or "apify/google-search-scraper",
        google_results_per_page=int(raw_input.get("google_results_per_page") or 10),
        country_code=raw_input.get("country_code") or "es",
        language_code=raw_input.get("language_code") or "es",
        max_harvest_candidates=int(raw_input.get("max_harvest_candidates") or 2),
        harvest_api_key=(env_harvest or raw_input.get("harvest_api_key") or None),
        harvest_concurrency=int(raw_input.get("harvest_concurrency") or 3),
        resolve_concurrency=int(raw_input.get("resolve_concurrency") or 1),
        fallback_google_by_website=bool(raw_input.get("fallback_google_by_website", True)),
        fallback_confidence_threshold=int(raw_input.get("fallback_confidence_threshold") or 78),
        fallback_harvest_search=bool(raw_input.get("fallback_harvest_search", True)),
        fallback_homepage_linkedin=bool(raw_input.get("fallback_homepage_linkedin", True)),
        use_ai_for_ambiguous=bool(raw_input.get("use_ai_for_ambiguous", False)),
        openai_api_key=(env_openai or raw_input.get("openai_api_key") or None),
        openai_model=raw_input.get("openai_model") or "gpt-4o-mini",
        ai_confidence_threshold=int(raw_input.get("ai_confidence_threshold") or 78),
        batch_size=int(raw_input.get("batch_size") or 20),
        debug=bool(raw_input.get("debug", False)),
    )


def _dedupe_linkedin_candidates(evidences: list[GoogleEvidence]) -> list[LinkedInCandidate]:
    by_url: dict[str, LinkedInCandidate] = {}
    order: list[str] = []
    for ev in evidences:
        normalized = normalize_linkedin_company_url(ev.url)
        if not normalized:
            continue
        if normalized not in by_url:
            by_url[normalized] = LinkedInCandidate(
                linkedin_url=normalized,
                universal_name_guess=slug_from_linkedin_url(normalized),
                google_evidences=[ev],
            )
            order.append(normalized)
        else:
            by_url[normalized].google_evidences.append(ev)
    return [by_url[url] for url in order]


def _needs_discovery(selected: LinkedInCandidate | None, confidence: float, threshold: int) -> bool:
    return selected is None or confidence < threshold


def _merge_linkedin_candidate(
    candidates: list[LinkedInCandidate],
    url: str,
    *,
    discovery_source: str,
    evidences: list[GoogleEvidence] | None = None,
    harvest: dict[str, Any] | None = None,
    harvest_error: str | None = None,
) -> LinkedInCandidate | None:
    """Add a candidate or attach evidence to an existing URL. Returns new candidate or None if merged."""
    normalized = normalize_linkedin_company_url(url)
    if not normalized:
        return None
    for cand in candidates:
        if cand.linkedin_url != normalized:
            continue
        if evidences:
            cand.google_evidences.extend(evidences)
        if harvest and not cand.harvest:
            cand.harvest = harvest
            cand.harvest_error = harvest_error
        if cand.discovery_source == "google" and discovery_source != "google":
            # Keep google as primary source; homepage/search are extra evidence.
            pass
        elif cand.discovery_source != "google":
            pass
        return None
    cand = LinkedInCandidate(
        linkedin_url=normalized,
        universal_name_guess=slug_from_linkedin_url(normalized),
        discovery_source=discovery_source,
        google_evidences=list(evidences or []),
        harvest=harvest,
        harvest_error=harvest_error,
    )
    candidates.append(cand)
    return cand


def _pre_score_new(company: CompanyInput, new_candidates: list[LinkedInCandidate]) -> None:
    for cand in new_candidates:
        pre_score, reasons = compute_pre_score(company, cand)
        cand.pre_score = pre_score
        cand.pre_score_reasons = reasons


async def _enrich_new_by_url(
    new_candidates: list[LinkedInCandidate],
    *,
    settings: ActorSettings,
    harvest_queries_used: list[str],
    top_n: int,
) -> None:
    to_enrich = [c for c in new_candidates if not c.harvest][: max(1, top_n)]
    if not to_enrich:
        return
    harvest_map = await enrich_candidates_with_harvest(
        [c.linkedin_url for c in to_enrich],
        api_key=settings.harvest_api_key,
        concurrency=settings.harvest_concurrency,
    )
    for cand in to_enrich:
        payload = harvest_map.get(cand.linkedin_url) or {}
        cand.harvest = payload.get("element")
        cand.harvest_error = payload.get("error")
        harvest_queries_used.append(cand.linkedin_url)


def _rescore_and_select(
    company: CompanyInput,
    candidates: list[LinkedInCandidate],
    website_candidates: list[Any],
) -> tuple[LinkedInCandidate | None, MatchStatus, float, Relationship, str | None]:
    for cand in candidates:
        final_score, reasons, relationship = compute_final_score(company, cand, website_candidates)
        cand.final_score = final_score
        cand.score_reasons = reasons
        cand.relationship = relationship
    candidates.sort(key=lambda c: c.final_score, reverse=True)
    selected = candidates[0] if candidates else None
    second_score = candidates[1].final_score if len(candidates) > 1 else None
    status = classify_match_status(
        selected.final_score if selected else 0.0,
        second_score,
        has_candidates=bool(candidates),
    )
    confidence = confidence_from_status(selected.final_score if selected else 0.0, status)
    relationship = selected.relationship if selected else Relationship.UNKNOWN
    commercial_name = (selected.harvest or {}).get("name") if selected and selected.harvest else None
    return selected, status, confidence, relationship, commercial_name


def _website_urls_for_homepage(website_candidates: list[Any], selected: LinkedInCandidate | None) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for item in website_candidates[:2]:
        url = getattr(item, "url", None)
        domain = getattr(item, "domain", None)
        if not url or is_website_noise_domain(domain):
            continue
        key = url.rstrip("/")
        if key not in seen:
            seen.add(key)
            urls.append(url)
    if selected and selected.harvest:
        harvest_site = selected.harvest.get("website")
        if isinstance(harvest_site, str) and harvest_site.strip():
            domain = extract_registrable_domain(harvest_site)
            if not is_website_noise_domain(domain):
                key = harvest_site.strip().rstrip("/")
                if key not in seen:
                    seen.add(key)
                    urls.append(harvest_site.strip())
    return urls[:2]


def _search_queries_for_company(company: CompanyInput) -> list[str]:
    legal = company.legal_name.strip()
    core = remove_legal_forms(legal).strip()
    queries = [legal]
    if core and core.casefold() != legal.casefold():
        queries.append(core)
    return queries


def _empty_result(company: CompanyInput, *, error: str | None = None, status: MatchStatus = MatchStatus.NOT_FOUND) -> ResolutionResult:
    return ResolutionResult(
        source_id=company.source_id,
        legal_name=company.legal_name,
        tax_id=company.tax_id,
        match_status=status.value,
        confidence=0.0,
        relationship=Relationship.UNKNOWN.value,
        enrichment_status="error" if error else "not_found",
        error=error,
        evidence_summary=error or "No LinkedIn company candidates found.",
        enriched_at=datetime.now(timezone.utc).isoformat(),
    )


def _build_evidence_summary(
    selected: LinkedInCandidate | None,
    website_domain: str | None,
    status: MatchStatus,
) -> str:
    if selected is None:
        return "No LinkedIn company page selected."
    parts = [
        f"status={status.value}",
        f"final_score={selected.final_score:.1f}",
        f"pre_score={selected.pre_score:.1f}",
        f"url={selected.linkedin_url}",
    ]
    if website_domain:
        parts.append(f"google_domain={website_domain}")
    harvest_website = (selected.harvest or {}).get("website") if selected.harvest else None
    if harvest_website:
        parts.append(f"harvest_website={harvest_website}")
    top_reasons = selected.score_reasons[:6]
    if top_reasons:
        parts.append("reasons=" + "; ".join(top_reasons))
    return " | ".join(parts)


def _result_from_selection(
    company: CompanyInput,
    selected: LinkedInCandidate | None,
    *,
    all_candidates: list[LinkedInCandidate],
    website_candidates: list[Any],
    google_queries_used: list[str],
    harvest_queries_used: list[str],
    discovery_sources_used: list[str],
    status: MatchStatus,
    confidence: float,
    relationship: Relationship,
    commercial_name: str | None,
    ai_decision: dict[str, Any] | None,
    debug: bool,
    error: str | None = None,
) -> ResolutionResult:
    google_website = website_candidates[0].url if website_candidates else None
    google_domain = website_candidates[0].domain if website_candidates else None

    if selected is None:
        result = _empty_result(company, error=error, status=status)
        result.google_queries_used = google_queries_used
        result.harvest_queries_used = harvest_queries_used
        result.discovery_sources_used = discovery_sources_used
        result.candidates_found = len(all_candidates)
        result.google_website = google_website
        result.domain = google_domain
        result.website = google_website
        result.confidence = confidence
        result.enrichment_status = "partial" if google_website else result.enrichment_status
        if status == MatchStatus.NOT_FOUND and google_website:
            result.match_status = MatchStatus.PARTIAL.value
            result.evidence_summary = "Website candidates found but no reliable LinkedIn match."
        if debug:
            result.candidates = [candidate_debug_dict(c, debug=True) for c in all_candidates]
            result.website_candidates = [w.model_dump(mode="json") for w in website_candidates]
            result.ai_decision = ai_decision
        return result

    element = selected.harvest or {}
    hq_fields = harvest_headquarters_fields(element if element else None)
    industry, industries = harvest_industry(element if element else None)
    emp_range, emp_start, emp_end = harvest_employee_range(element if element else None)
    harvest_website = element.get("website") if element else None
    harvest_domain = extract_registrable_domain(str(harvest_website) if harvest_website else None)
    website = harvest_website or google_website
    domain = harvest_domain or google_domain

    linkedin_id = None
    if element.get("id") is not None:
        linkedin_id = str(element.get("id"))

    employee_count = element.get("employeeCount")
    try:
        employee_count_int = int(employee_count) if employee_count is not None else None
    except (TypeError, ValueError):
        employee_count_int = None

    followers = element.get("followerCount")
    try:
        followers_int = int(followers) if followers is not None else None
    except (TypeError, ValueError):
        followers_int = None

    enrichment_status = "enriched" if selected.harvest else ("google_only" if selected.google_evidences else "partial")
    if selected.harvest_error and not selected.harvest:
        enrichment_status = "harvest_failed_google_kept"

    result = ResolutionResult(
        source_id=company.source_id,
        legal_name=company.legal_name,
        tax_id=company.tax_id,
        commercial_name=commercial_name or (element.get("name") if element else None),
        linkedin_url=selected.linkedin_url,
        linkedin_id=linkedin_id,
        universal_name=element.get("universalName") if element else selected.universal_name_guess,
        linkedin_name=element.get("name") if element else None,
        website=website,
        domain=domain,
        google_website=google_website,
        harvest_website=harvest_website,
        description=element.get("description") if element else None,
        tagline=element.get("tagline") if element else None,
        industry=industry,
        industries=industries,
        specialties=(element.get("specialities") or element.get("specialties")) if element else None,
        employee_count=employee_count_int,
        employee_range=emp_range,
        employee_range_start=emp_start,
        employee_range_end=emp_end,
        followers=followers_int,
        founded_year=harvest_founded_year(element if element else None),
        headquarters=hq_fields["headquarters"],
        headquarters_text=hq_fields["headquarters_text"],
        headquarters_city=hq_fields["headquarters_city"],
        headquarters_region=hq_fields["headquarters_region"],
        headquarters_country=hq_fields["headquarters_country"],
        locations=element.get("locations") if element else None,
        phone=harvest_phone(element if element else None),
        logo=harvest_logo_url(element if element else None),
        active=element.get("active") if element else None,
        page_verified=element.get("pageVerified") if element else None,
        relationship=relationship.value,
        match_status=status.value,
        confidence=confidence,
        evidence_summary=_build_evidence_summary(selected, google_domain, status),
        candidates_found=len(all_candidates),
        candidates_enriched=sum(1 for c in all_candidates if c.harvest),
        google_queries_used=google_queries_used,
        harvest_queries_used=harvest_queries_used,
        discovery_sources_used=discovery_sources_used,
        enrichment_status=enrichment_status,
        enriched_at=datetime.now(timezone.utc).isoformat(),
        error=error or selected.harvest_error,
    )
    if debug:
        result.candidates = [candidate_debug_dict(c, debug=True) for c in all_candidates]
        result.website_candidates = [w.model_dump(mode="json") for w in website_candidates]
        result.ai_decision = ai_decision
    return result


async def resolve_company(
    company: CompanyInput,
    settings: ActorSettings,
    *,
    prefetched_evidences: list[GoogleEvidence] | None = None,
) -> ResolutionResult:
    """Resolve a single company into exactly one output row."""
    google_queries_used: list[str] = []
    harvest_queries_used: list[str] = []

    initial_queries = build_initial_queries(company.legal_name)
    google_queries_used.extend(initial_queries)

    if prefetched_evidences is None:
        evidences = await run_google_searches(
            initial_queries,
            actor_id=settings.google_actor_id,
            token=settings.apify_token,
            country_code=settings.country_code,
            language_code=settings.language_code,
            results_per_page=settings.google_results_per_page,
            batch_size=settings.batch_size,
        )
    else:
        evidences = [
            ev.model_copy(deep=True)
            for ev in evidences_for_company(prefetched_evidences, company.legal_name)
        ]

    linkedin_evidences = filter_linkedin_evidences(evidences)
    website_evidences = filter_website_evidences(
        [e for e in evidences if e.query_type == WEBSITE_QUERY] or evidences
    )
    website_candidates = build_website_candidates(website_evidences, company.legal_name)

    candidates = _dedupe_linkedin_candidates(linkedin_evidences)
    for cand in candidates:
        pre_score, reasons = compute_pre_score(company, cand)
        cand.pre_score = pre_score
        cand.pre_score_reasons = reasons

    # Sort by pre_score descending; stable list avoids score-keyed dict collisions
    candidates.sort(key=lambda c: c.pre_score, reverse=True)
    top_n = max(1, min(settings.max_harvest_candidates, 5))
    to_enrich = candidates[:top_n]

    harvest_map = await enrich_candidates_with_harvest(
        [c.linkedin_url for c in to_enrich],
        api_key=settings.harvest_api_key,
        concurrency=settings.harvest_concurrency,
    )
    for cand in to_enrich:
        payload = harvest_map.get(cand.linkedin_url) or {}
        cand.harvest = payload.get("element")
        cand.harvest_error = payload.get("error")
        harvest_queries_used.append(cand.linkedin_url)

    selected, status, confidence, relationship, commercial_name = _rescore_and_select(
        company, candidates, website_candidates
    )
    ai_decision_dict: dict[str, Any] | None = None
    discovery_sources_used: list[str] = []

    # Homepage scrape + Harvest name search when Google URL-only discovery is weak.
    # Rollback: set fallback_homepage_linkedin / fallback_harvest_search to false
    # (see docs/PIPELINE_GOOGLE_ONLY.md).
    if _needs_discovery(selected, confidence, settings.fallback_confidence_threshold):
        if settings.fallback_homepage_linkedin:
            for site in _website_urls_for_homepage(website_candidates, selected):
                Actor.log.info(
                    "Low confidence (%.1f); scraping homepage LinkedIn links for %s",
                    confidence,
                    core_name(company.legal_name) or company.legal_name,
                )
                found_urls = await scrape_homepage_linkedin_urls(site)
                if not found_urls:
                    continue
                discovery_sources_used.append(f"homepage:{site}")
                new_from_home: list[LinkedInCandidate] = []
                for linkedin_url in found_urls:
                    evidence = GoogleEvidence(
                        query=f"homepage:{site}",
                        query_type=HOMEPAGE_QUERY,
                        position=1,
                        title=None,
                        snippet="linkedin.com/company link on company website",
                        url=linkedin_url,
                        domain="linkedin.com",
                    )
                    created = _merge_linkedin_candidate(
                        candidates,
                        linkedin_url,
                        discovery_source="homepage",
                        evidences=[evidence],
                    )
                    if created:
                        new_from_home.append(created)
                if new_from_home:
                    _pre_score_new(company, new_from_home)
                    await _enrich_new_by_url(
                        new_from_home,
                        settings=settings,
                        harvest_queries_used=harvest_queries_used,
                        top_n=top_n,
                    )
                # Recompute pre_score for merged homepage evidence on existing candidates
                for cand in candidates:
                    if any(ev.query_type == HOMEPAGE_QUERY for ev in cand.google_evidences):
                        pre_score, reasons = compute_pre_score(company, cand)
                        cand.pre_score = pre_score
                        cand.pre_score_reasons = reasons
                selected, status, confidence, relationship, commercial_name = _rescore_and_select(
                    company, candidates, website_candidates
                )
                if not _needs_discovery(selected, confidence, settings.fallback_confidence_threshold):
                    break

        if settings.fallback_harvest_search and _needs_discovery(
            selected, confidence, settings.fallback_confidence_threshold
        ):
            for query in _search_queries_for_company(company):
                Actor.log.info(
                    "Low confidence (%.1f); Harvest search by name for %s",
                    confidence,
                    core_name(company.legal_name) or company.legal_name,
                )
                payload = await search_company_with_harvest(
                    query,
                    api_key=settings.harvest_api_key,
                    concurrency=settings.harvest_concurrency,
                )
                harvest_queries_used.append(f"search:{query}")
                discovery_sources_used.append(f"harvest_search:{query}")
                linkedin_url = payload.get("linkedin_url")
                element = payload.get("element")
                if not linkedin_url:
                    continue
                created = _merge_linkedin_candidate(
                    candidates,
                    linkedin_url,
                    discovery_source="harvest_search",
                    harvest=element if isinstance(element, dict) else None,
                    harvest_error=payload.get("error"),
                )
                if created:
                    _pre_score_new(company, [created])
                    if not created.harvest:
                        await _enrich_new_by_url(
                            [created],
                            settings=settings,
                            harvest_queries_used=harvest_queries_used,
                            top_n=1,
                        )
                selected, status, confidence, relationship, commercial_name = _rescore_and_select(
                    company, candidates, website_candidates
                )
                if not _needs_discovery(selected, confidence, settings.fallback_confidence_threshold):
                    break

    # Optional domain fallback when confidence is still low
    if (
        settings.fallback_google_by_website
        and _needs_discovery(selected, confidence, settings.fallback_confidence_threshold)
    ):
        domain = None
        if website_candidates:
            domain = website_candidates[0].domain
        if not domain and selected and selected.harvest:
            domain = extract_registrable_domain(str(selected.harvest.get("website") or ""))
        if not domain:
            domains = extract_domains_from_text(
                *[e.snippet for e in evidences],
                *[e.title for e in evidences],
            )
            domain = domains[0] if domains else None
        if domain:
            fallback_q = build_domain_fallback_query(domain)
            google_queries_used.append(fallback_q)
            Actor.log.info(
                "Low confidence (%.1f); running domain fallback Google query for %s",
                confidence,
                core_name(company.legal_name) or company.legal_name,
            )
            fallback_evidences = await run_google_searches(
                [fallback_q],
                actor_id=settings.google_actor_id,
                token=settings.apify_token,
                country_code=settings.country_code,
                language_code=settings.language_code,
                results_per_page=settings.google_results_per_page,
                batch_size=settings.batch_size,
            )
            extra_linkedin = filter_linkedin_evidences(fallback_evidences)
            existing_urls = {c.linkedin_url for c in candidates}
            new_candidates: list[LinkedInCandidate] = []
            for ev in extra_linkedin:
                normalized = normalize_linkedin_company_url(ev.url)
                if not normalized:
                    continue
                if normalized in existing_urls:
                    # Attach evidence to existing candidate
                    for cand in candidates:
                        if cand.linkedin_url == normalized:
                            cand.google_evidences.append(ev)
                            break
                    continue
                new_candidates.append(
                    LinkedInCandidate(
                        linkedin_url=normalized,
                        universal_name_guess=slug_from_linkedin_url(normalized),
                        discovery_source="domain_fallback",
                        google_evidences=[ev],
                    )
                )
            for cand in new_candidates:
                pre_score, reasons = compute_pre_score(company, cand)
                cand.pre_score = pre_score
                cand.pre_score_reasons = reasons
            new_candidates.sort(key=lambda c: c.pre_score, reverse=True)
            enrich_extra = new_candidates[: max(1, top_n)]
            if enrich_extra:
                extra_map = await enrich_candidates_with_harvest(
                    [c.linkedin_url for c in enrich_extra],
                    api_key=settings.harvest_api_key,
                    concurrency=settings.harvest_concurrency,
                )
                for cand in enrich_extra:
                    payload = extra_map.get(cand.linkedin_url) or {}
                    cand.harvest = payload.get("element")
                    cand.harvest_error = payload.get("error")
                    harvest_queries_used.append(cand.linkedin_url)
                candidates.extend(enrich_extra)

            # Recompute final scores for all after fallback
            for cand in candidates:
                final_score, reasons, rel = compute_final_score(company, cand, website_candidates)
                cand.final_score = final_score
                cand.score_reasons = reasons
                cand.relationship = rel
            candidates.sort(key=lambda c: c.final_score, reverse=True)
            selected = candidates[0] if candidates else None
            second_score = candidates[1].final_score if len(candidates) > 1 else None
            status = classify_match_status(
                selected.final_score if selected else 0.0,
                second_score,
                has_candidates=bool(candidates),
            )
            confidence = confidence_from_status(selected.final_score if selected else 0.0, status)
            relationship = selected.relationship if selected else Relationship.UNKNOWN
            commercial_name = (selected.harvest or {}).get("name") if selected and selected.harvest else None

    # Optional AI for ambiguous cases — never replaces deterministic pipeline wholesale
    if (
        settings.use_ai_for_ambiguous
        and settings.openai_api_key
        and candidates
        and confidence < settings.ai_confidence_threshold
    ):
        Actor.log.info("Invoking optional AI disambiguation for %s", company.legal_name)
        ai_decision = await resolve_with_ai(
            company,
            candidates[: max(top_n, 3)],
            website_candidates,
            api_key=settings.openai_api_key,
            model=settings.openai_model,
        )
        ai_decision_dict = ai_decision.model_dump(mode="json")
        if (
            ai_decision.selected_candidate_index is not None
            and 0 <= ai_decision.selected_candidate_index < len(candidates[: max(top_n, 3)])
        ):
            selected = candidates[: max(top_n, 3)][ai_decision.selected_candidate_index]
            if ai_decision.relationship:
                relationship = ai_decision.relationship
                selected.relationship = relationship
            if ai_decision.commercial_name:
                commercial_name = ai_decision.commercial_name
            if ai_decision.confidence is not None:
                # Blend AI confidence lightly with deterministic score
                confidence = round((selected.final_score * 0.6) + (ai_decision.confidence * 0.4), 2)
            status = classify_match_status(confidence, None, has_candidates=True)

    return _result_from_selection(
        company,
        selected,
        all_candidates=candidates,
        website_candidates=website_candidates,
        google_queries_used=google_queries_used,
        harvest_queries_used=harvest_queries_used,
        discovery_sources_used=discovery_sources_used,
        status=status,
        confidence=confidence,
        relationship=relationship,
        commercial_name=commercial_name,
        ai_decision=ai_decision_dict,
        debug=settings.debug,
    )


async def resolve_companies_batch(
    companies: list[CompanyInput],
    settings: ActorSettings,
) -> list[ResolutionResult]:
    """Resolve many companies, batching Google queries when possible."""
    if not companies:
        return []

    # Build initial Google query batch for all companies
    query_list: list[str] = []
    for company in companies:
        query_list.extend(build_initial_queries(company.legal_name))

    Actor.log.info("Running initial Google Search for %s companies (%s queries).", len(companies), len(query_list))
    all_evidences = await run_google_searches(
        query_list,
        actor_id=settings.google_actor_id,
        token=settings.apify_token,
        country_code=settings.country_code,
        language_code=settings.language_code,
        results_per_page=settings.google_results_per_page,
        batch_size=settings.batch_size,
    )

    resolve_concurrency = max(1, settings.resolve_concurrency)
    sem = asyncio.Semaphore(resolve_concurrency)

    async def _resolve_one(company: CompanyInput) -> ResolutionResult:
        async with sem:
            try:
                return await resolve_company(company, settings, prefetched_evidences=all_evidences)
            except Exception as exc:  # noqa: BLE001
                Actor.log.exception(
                    "Failed resolving company %s: %s",
                    company.legal_name,
                    type(exc).__name__,
                )
                result = _empty_result(company, error=type(exc).__name__, status=MatchStatus.ERROR)
                result.google_queries_used = build_initial_queries(company.legal_name)
                return result

    if resolve_concurrency <= 1:
        results = [await _resolve_one(company) for company in companies]
    else:
        Actor.log.info(
            "Resolving %s companies with resolve_concurrency=%s (after batched Google).",
            len(companies),
            resolve_concurrency,
        )
        results = list(await asyncio.gather(*[_resolve_one(c) for c in companies]))
    return results
