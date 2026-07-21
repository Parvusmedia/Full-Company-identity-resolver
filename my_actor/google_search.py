"""Google Search via Apify Actor (batched)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from apify import Actor

from .models import GoogleEvidence
from .normalization import (
    extract_registrable_domain,
    is_linkedin_company_url,
    is_noise_website_domain,
    normalize_linkedin_company_url,
    remove_legal_forms,
)


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


def parse_google_dataset_items(items: list[dict[str, Any]]) -> list[GoogleEvidence]:
    evidences: list[GoogleEvidence] = []
    for item in items:
        query = _query_term(item)
        query_type = classify_query_type(query)
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
    return evidences


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
) -> list[GoogleEvidence]:
    """Execute Google Search Actor in batches and return parsed evidences."""
    unique_queries = []
    seen = set()
    for q in queries:
        qn = (q or "").strip()
        if not qn or qn in seen:
            continue
        seen.add(qn)
        unique_queries.append(qn)

    if not unique_queries:
        return []

    if not token:
        Actor.log.warning("No APIFY_TOKEN available; Google Search cannot run.")
        return []

    all_items: list[dict[str, Any]] = []

    try:
        from apify_client import ApifyClientAsync
    except ImportError:
        Actor.log.error("apify_client is not available; cannot run Google Search Actor.")
        return []

    client = ApifyClientAsync(token)

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
        try:
            run = await client.actor(actor_id).call(run_input=run_input)
        except Exception as exc:  # noqa: BLE001
            Actor.log.exception("Google Search Actor call failed: %s", type(exc).__name__)
            continue

        dataset_id = None
        if run is not None:
            # apify-client >=3 returns a Pydantic Run model; older code paths may yield a dict.
            dataset_id = getattr(run, "default_dataset_id", None)
            if dataset_id is None and isinstance(run, dict):
                dataset_id = run.get("defaultDatasetId") or run.get("default_dataset_id")

        if not dataset_id:
            Actor.log.warning("Google Search Actor returned no dataset.")
            continue
        dataset = client.dataset(dataset_id)
        async for item in dataset.iterate_items():
            if isinstance(item, dict):
                all_items.append(item)

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
