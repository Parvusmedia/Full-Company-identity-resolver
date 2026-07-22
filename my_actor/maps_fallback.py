"""Optional Google Maps last-resort website discovery."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from apify import Actor

from .models import WebsiteCandidate
from .normalization import (
    core_name,
    distinctive_name_tokens,
    domain_label,
    extract_registrable_domain,
    is_insurer_portal_domain,
    is_mismatched_country_domain,
    is_noise_website_domain,
    normalize_homepage_url,
    normalize_text,
    remove_legal_forms,
    text_mentions_company,
)
from .scoring import name_similarity


def build_maps_search_query(legal_name: str, *, city: str | None = None, province: str | None = None) -> str:
    core = remove_legal_forms(legal_name).strip() or legal_name.strip()
    parts = [core]
    # Soft sector cue when the legal name is a short acronym without "seguros"
    # (helps Maps disambiguate EGM / MK2 without changing branded queries).
    low = normalize_text(core)
    if "seguro" not in low and "corredur" not in low and "broker" not in low and "insurance" not in low:
        if len(distinctive_name_tokens(legal_name)) <= 1:
            parts.append("correduria seguros")
    if city and city.strip():
        parts.append(city.strip())
    elif province and province.strip():
        parts.append(province.strip())
    return " ".join(parts)


def _place_website(item: dict[str, Any]) -> str | None:
    for key in ("website", "websiteUrl", "url", "site"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _place_title(item: dict[str, Any]) -> str | None:
    for key in ("title", "name", "placeName"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def maps_items_to_website_candidates(
    items: list[dict[str, Any]],
    legal_name: str,
    *,
    country_code: str | None = None,
) -> list[WebsiteCandidate]:
    """Convert Maps places into WebsiteCandidate rows (noise filtered)."""
    from .models import GoogleEvidence

    core = core_name(legal_name)
    brand_tokens = distinctive_name_tokens(legal_name)
    out: list[WebsiteCandidate] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        website = _place_website(item)
        if not website:
            continue
        domain = extract_registrable_domain(website)
        if not domain or is_noise_website_domain(domain):
            continue
        if is_insurer_portal_domain(domain, legal_name):
            continue
        if is_mismatched_country_domain(domain, country_code):
            continue
        title = _place_title(item) or ""
        title_n = normalize_text(title)
        label = domain_label(domain)
        # Require a distinctive brand token in the place title or domain.
        # Avoid matching only weak qualifiers (e.g. Iberia airline for Willis Iberia).
        brand_in_title = any(t in title_n for t in brand_tokens) if brand_tokens else False
        brand_in_domain = any(t in label for t in brand_tokens) if brand_tokens else False
        domain_ok = name_similarity(core, label) >= 55
        title_ok = text_mentions_company(title, legal_name) or name_similarity(core, title) >= 70
        if brand_tokens and not (brand_in_title or brand_in_domain):
            continue
        if not (title_ok or domain_ok or brand_in_domain):
            continue
        homepage = normalize_homepage_url(website) or website
        score = 40.0
        score += name_similarity(core, title) * 0.35
        score += name_similarity(core, label) * 0.35
        if brand_in_domain:
            score += 12.0
        if idx == 0:
            score += 8.0
        out.append(
            WebsiteCandidate(
                url=homepage,
                domain=domain,
                score=score,
                google_evidences=[
                    GoogleEvidence(
                        query="google_maps_fallback",
                        query_type="maps",
                        position=idx + 1,
                        title=title or None,
                        snippet=item.get("address") or item.get("categoryName") or item.get("category"),
                        url=homepage,
                        domain=domain,
                    )
                ],
            )
        )
    out.sort(key=lambda c: c.score, reverse=True)
    return out


async def run_google_maps_fallback(
    legal_name: str,
    *,
    token: str | None,
    actor_id: str = "compass/crawler-google-places",
    city: str | None = None,
    province: str | None = None,
    country: str | None = None,
    country_code: str | None = None,
    language_code: str | None = None,
    max_places: int = 5,
) -> list[WebsiteCandidate]:
    """Last-resort Maps lookup when Google Search found no usable website."""
    if not token:
        Actor.log.warning("No APIFY_TOKEN; skipping Google Maps fallback.")
        return []

    search = build_maps_search_query(legal_name, city=city, province=province)
    Actor.log.info("Google Maps fallback for %s → %s", core_name(legal_name) or legal_name, search)

    from .apify_utils import call_actor_collect_items

    run_input: dict[str, Any] = {
        "searchStringsArray": [search],
        "maxCrawledPlacesPerSearch": max(1, min(max_places, 10)),
        "language": (language_code or "es").strip().lower()[:2] or "es",
        "maxImages": 0,
        "scrapeContacts": False,
        "includeWebResults": False,
        "skipClosedPlaces": False,
    }
    # Prefer city/province as location bias. Do NOT pass bare country alone —
    # "España" makes the Places crawler fan out across the whole country
    # (hundreds of map tiles) for vague names like "Set Ahorralo".
    location = ", ".join(p for p in [(city or "").strip(), (province or "").strip()] if p)
    if location:
        run_input["locationQuery"] = location
    # `country` is unused for locationQuery on purpose (nationwide crawl risk).
    _ = country

    items = await call_actor_collect_items(
        token=token,
        actor_id=actor_id,
        run_input=run_input,
        item_limit=max(10, max_places * 3),
    )

    candidates = maps_items_to_website_candidates(items, legal_name, country_code=country_code)
    Actor.log.info(
        "Google Maps fallback found %s place websites for %s",
        len(candidates),
        core_name(legal_name) or legal_name,
    )
    return candidates
