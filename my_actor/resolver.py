"""End-to-end company identity resolution pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from apify import Actor

from .ai_resolver import resolve_with_ai
from .google_search import (
    WEBSITE_QUERY,
    ai_overviews_for_company,
    build_attribution_queries,
    build_core_linkedin_query,
    build_domain_fallback_query,
    build_initial_queries,
    evidences_for_company,
    extract_domains_from_text,
    filter_linkedin_evidences,
    filter_website_evidences,
    run_google_searches,
    website_candidate_from_ai_overview,
    website_evidences_from_directory_snippets,
)
from .harvest import (
    enrich_candidates_with_harvest,
    harvest_employee_range,
    harvest_founded_year,
    harvest_headquarters_fields,
    harvest_industry,
    harvest_logo_url,
    harvest_phone,
)
from .models import (
    ActorSettings,
    AiOverviewEvidence,
    CompanyInput,
    GoogleEvidence,
    LinkedInCandidate,
    MatchStatus,
    Relationship,
    ResolutionResult,
)
from .normalization import (
    core_name,
    domain_label,
    extract_registrable_domain,
    collect_sector_hints_from_evidences,
    is_mismatched_country_domain,
    is_noise_website_domain,
    normalize_homepage_url,
    normalize_linkedin_company_url,
    select_official_website,
    slug_from_linkedin_url,
    text_mentions_company,
)
from .scoring import (
    build_website_candidates,
    candidate_debug_dict,
    classify_match_status,
    compute_final_score,
    compute_pre_score,
    confidence_from_status,
    name_similarity,
)
from .maps_fallback import run_google_maps_fallback
from .website_probe import discover_linkedin_from_website, validate_website_candidates


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
                        existing_website=item.get("existing_website") or item.get("website"),
                        existing_domain=item.get("existing_domain") or item.get("domain"),
                        existing_match_status=item.get("existing_match_status")
                        or item.get("match_status"),
                        existing_linkedin_url=item.get("existing_linkedin_url")
                        or item.get("linkedin_url"),
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
        harvest_pre_score_gap=float(raw_input.get("harvest_pre_score_gap") or 15),
        fallback_google_by_website=bool(raw_input.get("fallback_google_by_website", True)),
        fallback_confidence_threshold=int(raw_input.get("fallback_confidence_threshold") or 78),
        use_ai_for_ambiguous=bool(raw_input.get("use_ai_for_ambiguous", False)),
        openai_api_key=(env_openai or raw_input.get("openai_api_key") or None),
        openai_model=raw_input.get("openai_model") or "gpt-4o-mini",
        ai_confidence_threshold=int(raw_input.get("ai_confidence_threshold") or 78),
        batch_size=int(raw_input.get("batch_size") or 20),
        debug=bool(raw_input.get("debug", False)),
        validate_websites=bool(raw_input.get("validate_websites", True)),
        max_website_probes=int(
            raw_input["max_website_probes"]
            if raw_input.get("max_website_probes") is not None
            else 2
        ),
        fallback_google_maps=bool(raw_input.get("fallback_google_maps", True)),
        google_maps_actor_id=raw_input.get("google_maps_actor_id") or "compass/crawler-google-places",
        google_maps_max_places=int(raw_input.get("google_maps_max_places") or 5),
        skip_if_good_website=bool(raw_input.get("skip_if_good_website", True)),
        defer_core_linkedin=bool(raw_input.get("defer_core_linkedin", True)),
    )


_SKIP_MATCH_STATUSES = frozenset({"confirmed", "high_confidence"})


def _should_skip_company(company: CompanyInput, settings: ActorSettings) -> bool:
    """Skip re-resolve when prior website is already non-noise and high-confidence."""
    if not settings.skip_if_good_website:
        return False
    status = (company.existing_match_status or "").strip().lower()
    if status not in _SKIP_MATCH_STATUSES:
        return False
    website = (company.existing_website or "").strip()
    if not website:
        return False
    domain = company.existing_domain or extract_registrable_domain(website)
    if not domain or is_noise_website_domain(domain):
        return False
    return True


def _skipped_result(company: CompanyInput, *, debug: bool) -> ResolutionResult:
    website = normalize_homepage_url(company.existing_website) or company.existing_website
    domain = company.existing_domain or extract_registrable_domain(website)
    status = (company.existing_match_status or MatchStatus.HIGH_CONFIDENCE.value).strip()
    return ResolutionResult(
        source_id=company.source_id,
        legal_name=company.legal_name,
        tax_id=company.tax_id,
        linkedin_url=company.existing_linkedin_url,
        website=website,
        domain=domain,
        google_website=website,
        match_status=status,
        confidence=90.0 if status == MatchStatus.CONFIRMED.value else 82.0,
        relationship=Relationship.UNKNOWN.value,
        enrichment_status="skipped_existing",
        evidence_summary="Skipped: existing non-noise website with confirmed/high_confidence match.",
        google_queries_used=[],
        enriched_at=datetime.now(timezone.utc).isoformat(),
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


def _sanitize_final_website(
    website: str | None,
    domain: str | None,
    google_website: str | None,
    *,
    legal_name: str,
    content_backed: bool,
    country_code: str | None = None,
) -> tuple[str | None, str | None, str | None]:
    """Last-resort guard: never publish noise/garbage/insurer/foreign-ccTLD websites.

    Country mismatch is relative to ``country_code`` (batch setting), not a hard
    ".es only" rule — FR batches keep ``.fr``, ES batches reject ``.pe``, etc.
    Empty is better than a lookalike twin in another country.
    """
    del content_backed
    from .match_guards import should_block_published_website
    from .normalization import is_garbage_website_domain, is_insurer_portal_domain

    dom = domain or extract_registrable_domain(website)
    if not website or not dom:
        return None, None, google_website
    if is_noise_website_domain(dom) or is_garbage_website_domain(dom):
        return None, None, google_website
    if is_insurer_portal_domain(dom, legal_name):
        return None, None, google_website
    blocked, _reason = should_block_published_website(legal_name, dom, country_code=country_code)
    if blocked:
        return None, None, google_website
    return website, dom, google_website


def _top_website_is_content_backed(website_candidates: list[Any], legal_name: str) -> bool:
    if not website_candidates:
        return False
    top = website_candidates[0]
    probe = top.homepage_probe if isinstance(getattr(top, "homepage_probe", None), dict) else {}
    # AI Overview corroboration is strong enough to keep a dissimilar brand domain
    # (e.g. Willis Iberia → servicios-seguros.wtwco.com).
    if probe.get("ai_overview_backed"):
        return True
    from .normalization import website_path_looks_about, website_path_looks_legal_notice

    for ev in top.google_evidences:
        if text_mentions_company(ev.title or "", legal_name):
            return True
        title_n = (ev.title or "").casefold()
        about_title = any(t in title_n for t in ("quiénes somos", "quienes somos", "about us", "sobre nosotros"))
        if text_mentions_company(ev.snippet or "", legal_name) and (
            website_path_looks_about(ev.url) or website_path_looks_legal_notice(ev.url) or about_title
        ):
            return True
    return False


def _result_from_selection(
    company: CompanyInput,
    selected: LinkedInCandidate | None,
    *,
    all_candidates: list[LinkedInCandidate],
    website_candidates: list[Any],
    google_queries_used: list[str],
    harvest_queries_used: list[str],
    status: MatchStatus,
    confidence: float,
    relationship: Relationship,
    commercial_name: str | None,
    ai_decision: dict[str, Any] | None,
    debug: bool,
    error: str | None = None,
    country_code: str | None = None,
) -> ResolutionResult:
    raw_google_website = website_candidates[0].url if website_candidates else None
    raw_google_domain = website_candidates[0].domain if website_candidates else None
    content_backed = _top_website_is_content_backed(website_candidates, company.legal_name)

    if selected is None:
        website, domain, google_website, _harvest_clean = select_official_website(
            legal_name=company.legal_name,
            harvest_website=None,
            google_website=raw_google_website,
            google_domain=raw_google_domain,
            google_content_backed=content_backed,
            country_code=country_code,
        )
        website, domain, google_website = _sanitize_final_website(
            website,
            domain,
            google_website,
            legal_name=company.legal_name,
            content_backed=content_backed,
            country_code=country_code,
        )
        result = _empty_result(company, error=error, status=status)
        result.google_queries_used = google_queries_used
        result.candidates_found = len(all_candidates)
        result.google_website = google_website
        result.domain = domain
        result.website = website
        result.confidence = confidence
        result.enrichment_status = "partial" if website else result.enrichment_status
        if status == MatchStatus.NOT_FOUND and website:
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
    harvest_website_raw = element.get("website") if element else None
    website, domain, google_website, harvest_website = select_official_website(
        legal_name=company.legal_name,
        harvest_website=str(harvest_website_raw) if harvest_website_raw else None,
        google_website=raw_google_website,
        google_domain=raw_google_domain,
        google_content_backed=content_backed,
        country_code=country_code,
    )
    website, domain, google_website = _sanitize_final_website(
        website,
        domain,
        google_website,
        legal_name=company.legal_name,
        content_backed=content_backed,
        country_code=country_code,
    )

    # If the only website was a noise twin and we dropped it, also drop the
    # LinkedIn page that came from that twin (QDQ, directories, …).
    # Country-mismatched Harvest twins that lost to Google also detach LinkedIn.
    harvest_dom_for_guard = extract_registrable_domain(
        str(harvest_website_raw) if harvest_website_raw else None
    )
    drop_bad_linkedin = bool(
        website is None
        and harvest_dom_for_guard
        and (
            is_noise_website_domain(harvest_dom_for_guard)
            or is_mismatched_country_domain(harvest_dom_for_guard, country_code)
        )
    )
    from .match_guards import is_suppressed_linkedin

    if selected and is_suppressed_linkedin(company.legal_name, selected.linkedin_url):
        drop_bad_linkedin = True

    # Google .es (or other) overrode a foreign Harvest twin — detach that LinkedIn page.
    harvest_dom = extract_registrable_domain(str(harvest_website_raw) if harvest_website_raw else None)
    linkedin_detached = bool(
        (domain and harvest_dom and domain != harvest_dom and website == google_website)
        or drop_bad_linkedin
    )
    website_linkedin = None
    if linkedin_detached and website_candidates:
        probe = website_candidates[0].homepage_probe if isinstance(website_candidates[0].homepage_probe, dict) else {}
        raw_lis = probe.get("linkedin_urls") if probe else None
        if isinstance(raw_lis, list):
            for u in raw_lis:
                website_linkedin = normalize_linkedin_company_url(str(u))
                if website_linkedin:
                    break
        if not website_linkedin:
            # Discovery often runs as a LinkedInCandidate (website_linkedin) without
            # copying URLs back onto homepage_probe — reuse that candidate.
            for cand in all_candidates:
                reasons = cand.pre_score_reasons or []
                if "linkedin_found_on_official_website" in reasons or any(
                    (ev.query_type or "") == "website_linkedin" for ev in (cand.google_evidences or [])
                ):
                    website_linkedin = normalize_linkedin_company_url(cand.linkedin_url)
                    if website_linkedin:
                        break
        if not website_linkedin and selected and any(
            (ev.query_type or "") == "website_linkedin" for ev in (selected.google_evidences or [])
        ):
            website_linkedin = normalize_linkedin_company_url(selected.linkedin_url)

    linkedin_id = None
    if not linkedin_detached and element.get("id") is not None:
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

    out_linkedin = selected.linkedin_url
    out_commercial = commercial_name or (element.get("name") if element else None)
    out_status = status
    out_confidence = confidence
    out_relationship = relationship
    if linkedin_detached:
        out_linkedin = website_linkedin
        out_commercial = None
        linkedin_id = None
        employee_count_int = None
        followers_int = None
        enrichment_status = "partial" if website else "google_only"
        if website and not website_linkedin:
            out_status = MatchStatus.PARTIAL
            out_confidence = 0.0
            out_relationship = Relationship.UNKNOWN
        elif website and website_linkedin:
            out_status = MatchStatus.HIGH_CONFIDENCE if status.value in {"confirmed", "high_confidence"} else status
            out_confidence = min(float(confidence), 82.0)
            out_relationship = Relationship.SAME_ENTITY
        if "website_linkedin_override" not in google_queries_used and website_linkedin:
            google_queries_used = list(google_queries_used) + [f"website_linkedin:{domain}"]

    result = ResolutionResult(
        source_id=company.source_id,
        legal_name=company.legal_name,
        tax_id=company.tax_id,
        commercial_name=out_commercial if not linkedin_detached else out_commercial,
        linkedin_url=out_linkedin,
        linkedin_id=linkedin_id,
        universal_name=(None if linkedin_detached else (element.get("universalName") if element else selected.universal_name_guess)),
        linkedin_name=(None if linkedin_detached else (element.get("name") if element else None)),
        website=website,
        domain=domain,
        google_website=google_website,
        harvest_website=harvest_website,
        description=None if linkedin_detached else (element.get("description") if element else None),
        tagline=None if linkedin_detached else (element.get("tagline") if element else None),
        industry=None if linkedin_detached else industry,
        industries=None if linkedin_detached else industries,
        specialties=None if linkedin_detached else ((element.get("specialities") or element.get("specialties")) if element else None),
        employee_count=employee_count_int,
        employee_range=None if linkedin_detached else emp_range,
        employee_range_start=None if linkedin_detached else emp_start,
        employee_range_end=None if linkedin_detached else emp_end,
        followers=followers_int,
        founded_year=None if linkedin_detached else harvest_founded_year(element if element else None),
        headquarters=None if linkedin_detached else hq_fields["headquarters"],
        headquarters_text=None if linkedin_detached else hq_fields["headquarters_text"],
        headquarters_city=None if linkedin_detached else hq_fields["headquarters_city"],
        headquarters_region=None if linkedin_detached else hq_fields["headquarters_region"],
        headquarters_country=None if linkedin_detached else hq_fields["headquarters_country"],
        locations=None if linkedin_detached else (element.get("locations") if element else None),
        phone=None if linkedin_detached else harvest_phone(element if element else None),
        logo=None if linkedin_detached else harvest_logo_url(element if element else None),
        active=None if linkedin_detached else (element.get("active") if element else None),
        page_verified=None if linkedin_detached else (element.get("pageVerified") if element else None),
        relationship=out_relationship.value,
        match_status=out_status.value,
        confidence=out_confidence,
        evidence_summary=(
            f"Google website {domain} preferred over foreign Harvest twin; "
            f"LinkedIn={'from website' if website_linkedin else 'cleared'}."
            if linkedin_detached
            else _build_evidence_summary(selected, domain, out_status)
        ),
        candidates_found=len(all_candidates),
        candidates_enriched=sum(1 for c in all_candidates if c.harvest),
        google_queries_used=google_queries_used,
        harvest_queries_used=harvest_queries_used,
        enrichment_status=enrichment_status,
        enriched_at=datetime.now(timezone.utc).isoformat(),
        error=error or (None if linkedin_detached else selected.harvest_error),
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
    prefetched_ai_overviews: list[AiOverviewEvidence] | None = None,
) -> ResolutionResult:
    """Resolve a single company into exactly one output row."""
    if _should_skip_company(company, settings):
        Actor.log.info(
            "Skipping %s (existing website=%s status=%s)",
            core_name(company.legal_name) or company.legal_name,
            company.existing_website,
            company.existing_match_status,
        )
        return _skipped_result(company, debug=settings.debug)

    google_queries_used: list[str] = []
    harvest_queries_used: list[str] = []

    initial_queries = build_initial_queries(
        company.legal_name,
        city=company.city,
        include_core_linkedin=not settings.defer_core_linkedin,
        country_code=settings.country_code,
    )
    google_queries_used.extend(initial_queries)

    if prefetched_evidences is None:
        evidences, ai_overviews = await run_google_searches(
            initial_queries,
            actor_id=settings.google_actor_id,
            token=settings.apify_token,
            country_code=settings.country_code,
            language_code=settings.language_code,
            results_per_page=settings.google_results_per_page,
            batch_size=settings.batch_size,
        )
    else:
        evidences = evidences_for_company(
            prefetched_evidences,
            company.legal_name,
            city=company.city,
            country_code=settings.country_code,
        )
        ai_overviews = ai_overviews_for_company(
            prefetched_ai_overviews or [],
            company.legal_name,
            city=company.city,
            country_code=settings.country_code,
        )

    linkedin_evidences = filter_linkedin_evidences(evidences)

    # Deferred core-name LinkedIn: only when exact legal-name query found no /company/.
    core_q = build_core_linkedin_query(company.legal_name) if settings.defer_core_linkedin else None
    if core_q and any((e.query or "").strip() == core_q for e in evidences):
        if core_q not in google_queries_used:
            google_queries_used.append(core_q)
    if settings.defer_core_linkedin and not linkedin_evidences and core_q and prefetched_evidences is None:
        Actor.log.info(
            "No LinkedIn /company/ from exact query; running core LinkedIn for %s",
            core_name(company.legal_name) or company.legal_name,
        )
        google_queries_used.append(core_q)
        extra_ev, extra_ai = await run_google_searches(
            [core_q],
            actor_id=settings.google_actor_id,
            token=settings.apify_token,
            country_code=settings.country_code,
            language_code=settings.language_code,
            results_per_page=settings.google_results_per_page,
            batch_size=settings.batch_size,
        )
        evidences.extend(extra_ev)
        ai_overviews.extend(extra_ai)
        linkedin_evidences = filter_linkedin_evidences(evidences)

    website_query_evidences = [e for e in evidences if e.query_type == WEBSITE_QUERY]
    # Sector hints from full SERP (including directories like eInforma/Axesor).
    sector_hints = collect_sector_hints_from_evidences(company.legal_name, website_query_evidences)
    # Never fall back to LinkedIn SERP URLs as websites — that invents false domains.
    website_evidences = filter_website_evidences(website_query_evidences)
    # Recover official sites cited inside directory snippets (egmseguros.com on eInforma).
    cited = website_evidences_from_directory_snippets(
        website_query_evidences,
        company.legal_name,
        country_code=settings.country_code,
    )
    if cited:
        seen_doms = {e.domain for e in website_evidences if e.domain}
        added: list[str] = []
        for ev in cited:
            if ev.domain and ev.domain not in seen_doms:
                website_evidences.append(ev)
                seen_doms.add(ev.domain)
                added.append(ev.domain)
        if added:
            Actor.log.info(
                "Directory-cited websites for %s → %s",
                core_name(company.legal_name) or company.legal_name,
                ", ".join(added),
            )
    website_candidates = build_website_candidates(
        website_evidences,
        company.legal_name,
        country_code=settings.country_code,
        sector_hints=sector_hints,
    )
    if settings.validate_websites and website_candidates:
        website_candidates = await validate_website_candidates(
            company.legal_name,
            website_candidates,
            max_probes=settings.max_website_probes,
            concurrency=min(3, max(1, settings.max_website_probes)),
        )

    # Never publish country-mismatched / explicitly suppressed domains.
    # Empty is better than a foreign lookalike twin (arribas.pe, *.com.co, …).
    from .match_guards import should_block_published_website

    website_candidates = [
        c
        for c in website_candidates
        if not should_block_published_website(
            company.legal_name, c.domain, country_code=settings.country_code
        )[0]
    ]

    # Free final layer: Google AI Overview already returned with Search results.
    # Runs before Maps (Maps costs an extra Actor call).
    if not website_candidates and ai_overviews:
        company_ai = ai_overviews_for_company(
            ai_overviews,
            company.legal_name,
            city=company.city,
            country_code=settings.country_code,
        )
        # Soft-penalize foreign lookalikes in AI organic bridge via scoring;
        # keep them available — country preference is relative to settings.
        ai_organic = website_evidences
        ai_cand = website_candidate_from_ai_overview(
            company.legal_name,
            company_ai,
            ai_organic,
        )
        if ai_cand:
            Actor.log.info(
                "AI Overview website fallback for %s → %s",
                core_name(company.legal_name) or company.legal_name,
                ai_cand.url,
            )
            google_queries_used.append("google_ai_overview")
            ai_list = [ai_cand]
            if settings.validate_websites:
                ai_list = await validate_website_candidates(
                    company.legal_name,
                    ai_list,
                    max_probes=1,
                    concurrency=1,
                )
            website_candidates = ai_list
            website_candidates = [
                c
                for c in website_candidates
                if not should_block_published_website(
                    company.legal_name, c.domain, country_code=settings.country_code
                )[0]
            ]

    # Last resort: Google Maps place website when Search + AI Overview found nothing.
    if settings.fallback_google_maps and not website_candidates:
        maps_candidates = await run_google_maps_fallback(
            company.legal_name,
            token=settings.apify_token,
            actor_id=settings.google_maps_actor_id,
            city=company.city,
            province=company.province,
            country=company.country,
            country_code=settings.country_code,
            language_code=settings.language_code,
            max_places=settings.google_maps_max_places,
        )
        if maps_candidates:
            google_queries_used.append(
                f"google_maps:{maps_candidates[0].google_evidences[0].query if maps_candidates[0].google_evidences else 'fallback'}"
            )
            if settings.validate_websites:
                maps_candidates = await validate_website_candidates(
                    company.legal_name,
                    maps_candidates,
                    max_probes=min(settings.max_website_probes, len(maps_candidates)),
                    concurrency=min(3, settings.max_website_probes),
                )
            website_candidates = [
                c
                for c in maps_candidates
                if not should_block_published_website(
                    company.legal_name, c.domain, country_code=settings.country_code
                )[0]
            ]

    candidates = _dedupe_linkedin_candidates(linkedin_evidences)

    # Cheap LinkedIn discovery: scrape official website for /company/ links
    # (footer/header social icons). Runs only when Google found none.
    if not candidates and website_candidates:
        top_site = website_candidates[0]
        li_from_site: list[str] = []
        probe = top_site.homepage_probe if isinstance(top_site.homepage_probe, dict) else {}
        raw_lis = probe.get("linkedin_urls") if probe else None
        if isinstance(raw_lis, list) and raw_lis:
            li_from_site = [str(u) for u in raw_lis if u]
        else:
            Actor.log.info(
                "No LinkedIn from Google; scanning website HTML for %s → %s",
                core_name(company.legal_name) or company.legal_name,
                top_site.url,
            )
            li_from_site = await discover_linkedin_from_website(top_site.url)
        for li_url in li_from_site:
            normalized = normalize_linkedin_company_url(li_url)
            if not normalized:
                continue
            google_queries_used.append(f"website_linkedin:{top_site.domain or top_site.url}")
            candidates.append(
                LinkedInCandidate(
                    linkedin_url=normalized,
                    universal_name_guess=slug_from_linkedin_url(normalized),
                    google_evidences=[
                        GoogleEvidence(
                            query=f"website:{top_site.url}",
                            query_type="website_linkedin",
                            position=1,
                            title="LinkedIn link on official website",
                            snippet=f"Found on {top_site.url}",
                            url=normalized,
                            domain="linkedin.com",
                        )
                    ],
                    pre_score=70.0,
                    pre_score_reasons=["linkedin_found_on_official_website"],
                )
            )
            Actor.log.info("Website LinkedIn discovery → %s", normalized)
            break  # one company page is enough

    for cand in candidates:
        if not cand.pre_score_reasons:
            pre_score, reasons = compute_pre_score(company, cand)
            cand.pre_score = pre_score
            cand.pre_score_reasons = reasons

    from .match_guards import is_suppressed_linkedin

    # Never spend Harvest quota on explicitly suppressed LinkedIn twins.
    candidates = [c for c in candidates if not is_suppressed_linkedin(company.legal_name, c.linkedin_url)]

    # Sort by pre_score descending; stable list avoids score-keyed dict collisions
    candidates.sort(key=lambda c: c.pre_score, reverse=True)
    top_n = max(1, min(settings.max_harvest_candidates, 5))
    # Always enrich at least 2 LinkedIn candidates when available so a high
    # pre-score foreign twin that fails country checks does not starve the local
    # alternative (cost: one extra Harvest call in contested cases).
    enrich_n = max(top_n, min(2, len(candidates)))
    to_enrich = candidates[:enrich_n]
    gap = settings.harvest_pre_score_gap
    if (
        top_n == 1
        and len(to_enrich) > 1
        and gap > 0
        and (candidates[0].pre_score - candidates[1].pre_score) >= gap
    ):
        Actor.log.info(
            "Harvest top-1 only for %s (pre_score gap %.1f >= %.1f)",
            core_name(company.legal_name) or company.legal_name,
            candidates[0].pre_score - candidates[1].pre_score,
            gap,
        )
        to_enrich = candidates[:1]

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

    for cand in candidates:
        final_score, reasons, relationship = compute_final_score(
            company, cand, website_candidates, country_code=settings.country_code
        )
        cand.final_score = final_score
        cand.score_reasons = reasons
        cand.relationship = relationship

    candidates.sort(key=lambda c: c.final_score, reverse=True)

    # If the leader was crushed by country mismatch and a runner-up was never
    # Harvest-enriched, enrich it once so local commercial_brand can win fairly.
    selected = candidates[0] if candidates else None
    if (
        selected
        and selected.final_score < 40
        and any("mismatch" in r or "suppression" in r for r in (selected.score_reasons or []))
    ):
        alt = next((c for c in candidates[1:] if c.harvest is None and c.final_score >= 25), None)
        if alt is None:
            alt = next((c for c in candidates[1:] if c.harvest is None), None)
        if alt is not None:
            Actor.log.info(
                "Top LinkedIn weak after country guards; enriching runner-up %s",
                alt.linkedin_url,
            )
            extra_map = await enrich_candidates_with_harvest(
                [alt.linkedin_url],
                api_key=settings.harvest_api_key,
                concurrency=1,
            )
            payload = extra_map.get(alt.linkedin_url) or {}
            alt.harvest = payload.get("element")
            alt.harvest_error = payload.get("error")
            harvest_queries_used.append(alt.linkedin_url)
            for cand in candidates:
                final_score, reasons, relationship = compute_final_score(
                    company, cand, website_candidates, country_code=settings.country_code
                )
                cand.final_score = final_score
                cand.score_reasons = reasons
                cand.relationship = relationship
            candidates.sort(key=lambda c: c.final_score, reverse=True)

    selected = candidates[0] if candidates else None
    # Drop crushed leaders (score ~0 from suppression/mismatch with no signal).
    if selected and selected.final_score < 15:
        selected = next((c for c in candidates if c.final_score >= 40), None) or next(
            (c for c in candidates if c.final_score >= 25), None
        )
    second_score = None
    if selected and candidates:
        others = [c.final_score for c in candidates if c.linkedin_url != selected.linkedin_url]
        second_score = others[0] if others else None
    status = classify_match_status(
        selected.final_score if selected else 0.0,
        second_score,
        has_candidates=bool(candidates),
    )
    # Local commercial_brand / parent with solid score → at least probable
    # (AGA → asesoriaarribas: related, not confirmed same_entity).
    if (
        selected
        and status == MatchStatus.AMBIGUOUS
        and selected.final_score >= 50
        and selected.relationship
        in {Relationship.COMMERCIAL_BRAND, Relationship.PARENT_COMPANY, Relationship.SAME_ENTITY}
    ):
        status = MatchStatus.PROBABLE
    confidence = confidence_from_status(selected.final_score if selected else 0.0, status)
    relationship = selected.relationship if selected else Relationship.UNKNOWN
    commercial_name = (selected.harvest or {}).get("name") if selected and selected.harvest else None
    ai_decision_dict: dict[str, Any] | None = None

    # Optional domain→LinkedIn fallback: only when LinkedIn is weak/missing AND
    # we already have a strong website signal (avoids expensive blind retries).
    website_strong = False
    if website_candidates:
        top_w = website_candidates[0]
        probe = top_w.homepage_probe if isinstance(top_w.homepage_probe, dict) else {}
        website_strong = bool(
            _top_website_is_content_backed(website_candidates, company.legal_name)
            or (top_w.score or 0) >= 55
            or probe.get("ai_overview_backed")
            or probe.get("reject_overridden_by_about_page")
        )
    if (
        settings.fallback_google_by_website
        and confidence < settings.fallback_confidence_threshold
        and website_strong
    ):
        domain = None
        if website_candidates:
            top = website_candidates[0]
            # Prefer owned-looking domains; content-backed brand portals also OK.
            label_sim = name_similarity(core_name(company.legal_name), domain_label(top.domain))
            if label_sim >= 50 or _top_website_is_content_backed(website_candidates, company.legal_name):
                domain = top.domain
        if not domain and selected and selected.harvest:
            domain = extract_registrable_domain(str(selected.harvest.get("website") or ""))
        if domain and is_noise_website_domain(domain):
            domain = None
        if not domain:
            domains = []
            for d in extract_domains_from_text(
                *[e.snippet for e in evidences],
                *[e.title for e in evidences],
            ):
                if is_noise_website_domain(d):
                    continue
                if name_similarity(core_name(company.legal_name), domain_label(d)) < 50:
                    continue
                domains.append(d)
            domain = domains[0] if domains else None
        if domain:
            fallback_q = build_domain_fallback_query(domain)
            google_queries_used.append(fallback_q)
            Actor.log.info(
                "Weak LinkedIn (%.1f) + strong website; domain fallback for %s → %s",
                confidence,
                core_name(company.legal_name) or company.legal_name,
                domain,
            )
            fallback_evidences, _ = await run_google_searches(
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
                        google_evidences=[ev],
                    )
                )
            for cand in new_candidates:
                pre_score, reasons = compute_pre_score(company, cand)
                cand.pre_score = pre_score
                cand.pre_score_reasons = reasons
            new_candidates.sort(key=lambda c: c.pre_score, reverse=True)
            enrich_extra = new_candidates[:1]  # one Harvest call max on fallback
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
                final_score, reasons, rel = compute_final_score(
                    company, cand, website_candidates, country_code=settings.country_code
                )
                cand.final_score = final_score
                cand.score_reasons = reasons
                cand.relationship = rel
            candidates.sort(key=lambda c: c.final_score, reverse=True)
            selected = candidates[0] if candidates else None
            if selected and selected.final_score < 15:
                selected = next((c for c in candidates if c.final_score >= 40), None) or next(
                    (c for c in candidates if c.final_score >= 25), None
                )
            second_score = None
            if selected and candidates:
                others = [c.final_score for c in candidates if c.linkedin_url != selected.linkedin_url]
                second_score = others[0] if others else None
            status = classify_match_status(
                selected.final_score if selected else 0.0,
                second_score,
                has_candidates=bool(candidates),
            )
            if (
                selected
                and status == MatchStatus.AMBIGUOUS
                and selected.final_score >= 50
                and selected.relationship
                in {Relationship.COMMERCIAL_BRAND, Relationship.PARENT_COMPANY, Relationship.SAME_ENTITY}
            ):
                status = MatchStatus.PROBABLE
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

    # When Google will beat a country-mismatched Harvest twin, ensure homepage
    # LinkedIn is available on the winning website probe (discovery is skipped if
    # Google already returned some /company/ hit — often the wrong-country twin).
    if selected and website_candidates:
        top_w = website_candidates[0]
        h_raw = (selected.harvest or {}).get("website") if selected.harvest else None
        h_dom = extract_registrable_domain(str(h_raw) if h_raw else None)
        g_dom = top_w.domain
        if (
            g_dom
            and h_dom
            and g_dom != h_dom
            and is_mismatched_country_domain(h_dom, settings.country_code)
            and not is_mismatched_country_domain(g_dom, settings.country_code)
            and _top_website_is_content_backed(website_candidates, company.legal_name)
        ):
            probe = top_w.homepage_probe if isinstance(top_w.homepage_probe, dict) else {}
            lis = [str(u) for u in (probe.get("linkedin_urls") or []) if u]
            if not lis:
                Actor.log.info(
                    "Mismatched-country Harvest twin (%s); scraping LinkedIn from Google website %s",
                    h_dom,
                    top_w.url,
                )
                lis = await discover_linkedin_from_website(top_w.url)
            if lis:
                top_w.homepage_probe = {
                    **probe,
                    "linkedin_urls": lis,
                    "ok": probe.get("ok", True),
                }

    return _result_from_selection(
        company,
        selected,
        all_candidates=candidates,
        website_candidates=website_candidates,
        google_queries_used=google_queries_used,
        harvest_queries_used=harvest_queries_used,
        status=status,
        confidence=confidence,
        relationship=relationship,
        commercial_name=commercial_name,
        ai_decision=ai_decision_dict,
        debug=settings.debug,
        country_code=settings.country_code,
    )


async def resolve_companies_batch(
    companies: list[CompanyInput],
    settings: ActorSettings,
) -> list[ResolutionResult]:
    """Resolve many companies, batching Google queries when possible."""
    if not companies:
        return []

    results_by_index: dict[int, ResolutionResult] = {}
    to_resolve: list[tuple[int, CompanyInput]] = []
    for idx, company in enumerate(companies):
        if _should_skip_company(company, settings):
            Actor.log.info(
                "Skipping %s (existing website=%s status=%s)",
                core_name(company.legal_name) or company.legal_name,
                company.existing_website,
                company.existing_match_status,
            )
            results_by_index[idx] = _skipped_result(company, debug=settings.debug)
        else:
            to_resolve.append((idx, company))

    if not to_resolve:
        return [results_by_index[i] for i in range(len(companies))]

    # Phase 1: LinkedIn exact + soft website (2 queries / company when deferred).
    query_list: list[str] = []
    for _, company in to_resolve:
        query_list.extend(
            build_initial_queries(
                company.legal_name,
                city=company.city,
                include_core_linkedin=not settings.defer_core_linkedin,
                country_code=settings.country_code,
            )
        )

    Actor.log.info(
        "Running initial Google Search for %s companies (%s queries).",
        len(to_resolve),
        len(query_list),
    )
    all_evidences, all_ai_overviews = await run_google_searches(
        query_list,
        actor_id=settings.google_actor_id,
        token=settings.apify_token,
        country_code=settings.country_code,
        language_code=settings.language_code,
        results_per_page=settings.google_results_per_page,
        batch_size=settings.batch_size,
    )

    # Phase 2: deferred core LinkedIn only for companies with no /company/ hit.
    if settings.defer_core_linkedin:
        core_queries: list[str] = []
        for _, company in to_resolve:
            company_ev = evidences_for_company(
                all_evidences,
                company.legal_name,
                city=company.city,
                country_code=settings.country_code,
            )
            if filter_linkedin_evidences(company_ev):
                continue
            core_q = build_core_linkedin_query(company.legal_name)
            if core_q:
                core_queries.append(core_q)
        if core_queries:
            # Dedupe while preserving order
            seen: set[str] = set()
            unique_core: list[str] = []
            for q in core_queries:
                if q not in seen:
                    seen.add(q)
                    unique_core.append(q)
            Actor.log.info(
                "Deferred core LinkedIn for %s companies (%s queries).",
                len(unique_core),
                len(unique_core),
            )
            extra_ev, extra_ai = await run_google_searches(
                unique_core,
                actor_id=settings.google_actor_id,
                token=settings.apify_token,
                country_code=settings.country_code,
                language_code=settings.language_code,
                results_per_page=settings.google_results_per_page,
                batch_size=settings.batch_size,
            )
            all_evidences.extend(extra_ev)
            all_ai_overviews.extend(extra_ai)

    for idx, company in to_resolve:
        try:
            result = await resolve_company(
                company,
                settings,
                prefetched_evidences=all_evidences,
                prefetched_ai_overviews=all_ai_overviews,
            )
        except Exception as exc:  # noqa: BLE001
            Actor.log.exception(
                "Failed resolving company %s: %s",
                company.legal_name,
                type(exc).__name__,
            )
            result = _empty_result(company, error=type(exc).__name__, status=MatchStatus.ERROR)
            result.google_queries_used = build_attribution_queries(
                company.legal_name, city=company.city, country_code=settings.country_code
            )
        results_by_index[idx] = result

    return [results_by_index[i] for i in range(len(companies))]
