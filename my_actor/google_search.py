"""Google Search via Apify Actor (batched)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from apify import Actor

from .models import AiOverviewEvidence, GoogleEvidence, WebsiteCandidate
from .normalization import (
    core_name,
    extract_registrable_domain,
    is_linkedin_company_url,
    is_noise_website_domain,
    normalize_homepage_url,
    normalize_linkedin_company_url,
    normalize_text,
    remove_legal_forms,
    text_mentions_company,
)
from .scoring import name_similarity


LINKEDIN_QUERY = "linkedin"
WEBSITE_QUERY = "website"
DOMAIN_FALLBACK_QUERY = "domain_fallback"
CORE_LINKEDIN_QUERY = "core_linkedin"


def build_linkedin_query(legal_name: str) -> str:
    return f'"{legal_name}" linkedin'


def build_website_query(legal_name: str, city: str | None = None) -> str:
    """Discover official websites.

    Important: do **not** wrap the full legal name in quotes. Exact-phrase
    queries bias Google toward registries (einforma, empresite, BORME) and hide
    the real homepage (e.g. baigorri.com). A soft core-name (+ city) query
    matches what users see in a normal Google search.
    """
    core = remove_legal_forms(legal_name).strip() or (legal_name or "").strip()
    if city and city.strip():
        return f"{core} {city.strip()}"
    return core


def build_core_linkedin_query(legal_name: str) -> str | None:
    """Extra LinkedIn query using the name without legal-form suffixes."""
    core = remove_legal_forms(legal_name).strip()
    if not core or core.casefold() == legal_name.strip().casefold():
        return None
    return f'"{core}" linkedin'


def build_initial_queries(legal_name: str, *, city: str | None = None) -> list[str]:
    """Initial Google queries for a company (legal + optional core-name LinkedIn)."""
    queries = [build_linkedin_query(legal_name), build_website_query(legal_name, city=city)]
    core_q = build_core_linkedin_query(legal_name)
    if core_q:
        queries.append(core_q)
    return queries


def build_domain_fallback_query(domain: str) -> str:
    clean = domain.strip().removeprefix("www.")
    return f'site:linkedin.com/company "{clean}"'


def classify_query_type(query: str) -> str:
    q = query.lower().strip()
    if q.startswith("site:linkedin.com/company"):
        return DOMAIN_FALLBACK_QUERY
    if "linkedin" in q:
        return LINKEDIN_QUERY
    # Soft company-name searches (no linkedin / site:) are website discovery.
    if q:
        return WEBSITE_QUERY
    return "other"


def chunked(items: list[str], size: int) -> list[list[str]]:
    if size <= 0:
        size = 20
    return [items[i : i + size] for i in range(0, len(items), size)]


def _organic_results(item: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("organicResults", "organic_results", "results"):
        value = item.get(key)
        if isinstance(value, list):
            return [r for r in value if isinstance(r, dict)]
    return []


def _query_term(item: dict[str, Any]) -> str:
    search_query = item.get("searchQuery") or item.get("search_query") or {}
    if isinstance(search_query, dict):
        term = search_query.get("term") or search_query.get("query") or ""
        return str(term)
    if isinstance(search_query, str):
        return search_query
    return str(item.get("query") or item.get("term") or "")


AI_OVERVIEW_QUERY = "ai_overview"


def parse_ai_overview(item: dict[str, Any], query: str) -> AiOverviewEvidence | None:
    raw = item.get("aiOverview") or item.get("ai_overview") or item.get("generativeAiOverview")
    if not isinstance(raw, dict):
        return None
    content = raw.get("content") or raw.get("text") or raw.get("markdown") or ""
    if isinstance(content, list):
        content = " ".join(str(x) for x in content if x)
    content = str(content or "").strip()
    if not content:
        return None
    sources_raw = raw.get("sources") or raw.get("citations") or []
    sources: list[dict[str, Any]] = []
    if isinstance(sources_raw, list):
        for src in sources_raw:
            if isinstance(src, dict):
                sources.append(src)
            elif isinstance(src, str) and src.strip():
                sources.append({"url": src.strip()})
    return AiOverviewEvidence(query=query, content=content, sources=sources)


def parse_google_dataset_items(
    items: list[dict[str, Any]],
) -> tuple[list[GoogleEvidence], list[AiOverviewEvidence]]:
    evidences: list[GoogleEvidence] = []
    ai_overviews: list[AiOverviewEvidence] = []
    for item in items:
        query = _query_term(item)
        query_type = classify_query_type(query)
        ai = parse_ai_overview(item, query)
        if ai:
            ai_overviews.append(ai)
        for result in _organic_results(item):
            url = (
                result.get("url")
                or result.get("link")
                or result.get("displayedUrl")
                or ""
            )
            if not url:
                continue
            title = result.get("title") or result.get("name")
            snippet = (
                result.get("description")
                or result.get("snippet")
                or result.get("text")
            )
            position = result.get("position") or result.get("rank") or result.get("index")
            try:
                position_int = int(position) if position is not None else None
            except (TypeError, ValueError):
                position_int = None
            evidences.append(
                GoogleEvidence(
                    query=query,
                    query_type=query_type,
                    position=position_int,
                    title=str(title) if title else None,
                    snippet=str(snippet) if snippet else None,
                    url=str(url),
                    domain=extract_registrable_domain(str(url)),
                )
            )
    return evidences, ai_overviews


def ai_overviews_for_company(
    ai_overviews: list[AiOverviewEvidence],
    legal_name: str,
    *,
    city: str | None = None,
) -> list[AiOverviewEvidence]:
    allowed = {q.strip() for q in build_initial_queries(legal_name, city=city) if q and q.strip()}
    return [a for a in ai_overviews if (a.query or "").strip() in allowed]


def ai_overview_mentions_company(content: str | None, legal_name: str) -> bool:
    """True when AI overview text clearly refers to this legal entity."""
    if not content:
        return False
    if text_mentions_company(content, legal_name):
        return True
    # Also accept near-exact legal name presence (with legal forms).
    blob = normalize_text(content)
    legal = normalize_text(legal_name)
    core = normalize_text(remove_legal_forms(legal_name))
    return bool(legal and legal in blob) or bool(core and core in blob)


def _ai_brand_matches_domain(ai_blob: str, domain: str) -> bool:
    """Loose brand↔domain aliases seen in AI Overviews (WTW → wtwco.com)."""
    label = (domain.split(".")[0] if domain else "").lower()
    if not label:
        return False
    # WTW / Willis Towers Watson group sites
    if "wtw" in ai_blob.split() or "willis towers watson" in ai_blob or "willis towes watson" in ai_blob:
        if label.startswith("wtw") or label in {"willis", "willistowerswatson"}:
            return True
    return False


def website_candidate_from_ai_overview(
    legal_name: str,
    ai_overviews: list[AiOverviewEvidence],
    organic_website_evidences: list[GoogleEvidence],
) -> WebsiteCandidate | None:
    """
    Final free layer when organic scoring yields nothing.

    Uses Google AI Overview text (already returned by the Search Actor) plus
    its source URLs / top organic hits. Accepts a non-noise URL only when the
    overview clearly mentions the company (e.g. Willis Iberia →
    servicios-seguros.wtwco.com).
    """
    supporting = [a for a in ai_overviews if ai_overview_mentions_company(a.content, legal_name)]
    if not supporting:
        return None

    ai_blob = normalize_text(" ".join(a.content for a in supporting))
    source_urls: list[str] = []
    for overview in supporting:
        for src in overview.sources:
            url = src.get("url") or src.get("link")
            if isinstance(url, str) and url.strip():
                source_urls.append(url.strip())
        for domain in extract_domains_from_text(overview.content):
            source_urls.append(f"https://{domain}/")

    source_domains = {
        d
        for u in source_urls
        if (d := extract_registrable_domain(u)) and not is_noise_website_domain(d)
    }

    def _usable(ev: GoogleEvidence) -> bool:
        domain = ev.domain or extract_registrable_domain(ev.url)
        if not domain or is_noise_website_domain(domain):
            return False
        host = (urlparse(ev.url).netloc or "").lower()
        return "linkedin.com" not in host

    # Prefer organic hits whose domain is cited by AI or appears in the overview text.
    ranked_organic = sorted(
        [e for e in organic_website_evidences if _usable(e)],
        key=lambda e: e.position or 99,
    )
    preferred: list[GoogleEvidence] = []
    for ev in ranked_organic:
        domain = ev.domain or extract_registrable_domain(ev.url) or ""
        host = (urlparse(ev.url).netloc or "").lower().removeprefix("www.")
        title_hit = text_mentions_company(ev.title or "", legal_name)
        snippet_hit = text_mentions_company(ev.snippet or "", legal_name)
        if (
            domain in source_domains
            or domain in ai_blob
            or host.replace(".", "") in ai_blob.replace(" ", "").replace(".", "")
            or title_hit
            or snippet_hit
            or _ai_brand_matches_domain(ai_blob, domain)
        ):
            preferred.append(ev)
            break

    if not preferred:
        seen_domains: set[str] = set()
        for url in source_urls:
            domain = extract_registrable_domain(url)
            if not domain or domain in seen_domains or is_noise_website_domain(domain):
                continue
            if "linkedin.com" in domain:
                continue
            seen_domains.add(domain)
            preferred.append(
                GoogleEvidence(
                    query=supporting[0].query,
                    query_type=AI_OVERVIEW_QUERY,
                    position=1,
                    title="Google AI Overview source",
                    snippet=supporting[0].content[:400],
                    url=url,
                    domain=domain,
                )
            )
            break

    # Last resort within this free layer: AI named the firm but cited no URL —
    # take the top non-noise website organic (already preferred over Maps).
    if not preferred and ranked_organic:
        preferred.append(ranked_organic[0])

    if not preferred:
        return None

    best = preferred[0]
    homepage = normalize_homepage_url(best.url) or best.url
    domain = best.domain or extract_registrable_domain(homepage)
    core = core_name(legal_name)
    score = 62.0 + name_similarity(core, best.title or "") * 0.1
    return WebsiteCandidate(
        url=homepage,
        domain=domain,
        score=score,
        google_evidences=[best],
        homepage_probe={
            "ai_overview_backed": True,
            "ai_excerpt": supporting[0].content[:280],
        },
    )


def filter_linkedin_evidences(evidences: list[GoogleEvidence]) -> list[GoogleEvidence]:
    out: list[GoogleEvidence] = []
    for ev in evidences:
        normalized = normalize_linkedin_company_url(ev.url)
        if not normalized:
            # Keep only true /company/ URLs; posts may still derive a company URL above.
            if not is_linkedin_company_url(ev.url):
                continue
            continue
        out.append(ev.model_copy(update={"url": normalized}))
    return out


def filter_website_evidences(evidences: list[GoogleEvidence]) -> list[GoogleEvidence]:
    out: list[GoogleEvidence] = []
    for ev in evidences:
        host = (urlparse(ev.url).netloc or "").lower().removeprefix("www.")
        if "linkedin.com" in host:
            continue
        domain = extract_registrable_domain(ev.url) or host
        if is_noise_website_domain(domain):
            continue
        path = urlparse(ev.url).path.lower()
        if path.endswith(".pdf"):
            continue
        # Keep original URL so path editorial checks still work in scoring;
        # homepage normalization happens when building/selecting candidates.
        out.append(ev.model_copy(update={"domain": domain}))
    return out


def evidences_for_company(evidences: list[GoogleEvidence], legal_name: str, *, city: str | None = None) -> list[GoogleEvidence]:
    """Select evidences belonging to a company via exact query match (no substring bleed)."""
    allowed = {q.strip() for q in build_initial_queries(legal_name, city=city) if q and q.strip()}
    if not allowed:
        return []
    return [e for e in evidences if (e.query or "").strip() in allowed]


def evidences_for_query(evidences: list[GoogleEvidence], query: str) -> list[GoogleEvidence]:
    target = query.strip()
    return [e for e in evidences if e.query.strip() == target]


async def run_google_searches(
    queries: list[str],
    *,
    actor_id: str,
    token: str | None,
    country_code: str = "es",
    language_code: str = "es",
    results_per_page: int = 10,
    batch_size: int = 20,
) -> tuple[list[GoogleEvidence], list[AiOverviewEvidence]]:
    """Execute Google Search Actor in batches; return organic + AI Overview evidence."""
    unique_queries = []
    seen = set()
    for q in queries:
        qn = (q or "").strip()
        if not qn or qn in seen:
            continue
        seen.add(qn)
        unique_queries.append(qn)

    if not unique_queries:
        return [], []

    if not token:
        Actor.log.warning("No APIFY_TOKEN available; Google Search cannot run.")
        return [], []

    from .apify_utils import call_actor_collect_items

    all_items: list[dict[str, Any]] = []

    for batch in chunked(unique_queries, batch_size):
        run_input = {
            "queries": "\n".join(batch),
            "countryCode": country_code,
            "languageCode": language_code,
            "maxPagesPerQuery": 1,
            "resultsPerPage": results_per_page,
            "saveHtml": False,
            "saveHtmlToKeyValueStore": False,
        }
        Actor.log.info(
            "Calling Google Search Actor %s with %s queries (batch).",
            actor_id,
            len(batch),
        )
        batch_items = await call_actor_collect_items(
            token=token,
            actor_id=actor_id,
            run_input=run_input,
            item_limit=max(50, len(batch) * results_per_page * 2),
        )
        all_items.extend(batch_items)

    return parse_google_dataset_items(all_items)


_DOMAIN_IN_TEXT_RE = re.compile(
    r"\b(?:https?://)?(?:www\.)?([a-z0-9](?:[a-z0-9\-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?)+)\b",
    re.IGNORECASE,
)


def extract_domains_from_text(*texts: str | None) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for text in texts:
        if not text:
            continue
        for match in _DOMAIN_IN_TEXT_RE.findall(text):
            domain = extract_registrable_domain(match)
            if not domain or domain in seen:
                continue
            if is_noise_website_domain(domain):
                continue
            if any(x in domain for x in ("linkedin.com", "google.", "facebook.com")):
                continue
            seen.add(domain)
            found.append(domain)
    return found
