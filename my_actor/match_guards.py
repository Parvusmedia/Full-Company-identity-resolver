"""Guards derived from past false-positive classes.

Prefer reusable rules over a growing per-company exception list.
Use ``SUPPRESSIONS`` only for confirmed bad publishes that soft rules
still cannot catch safely.

Error classes encoded here / in scoring+sanitize:
  1. country_mismatch_cctld — never publish another country's ccTLD for this batch
  2. noise_directory_domain — QDQ, eInforma, hubs, … (WEBSITE_NOISE_DOMAINS)
  3. insurer_portal_domain — Allianz/Mapfre/KPMG for independent brokers
  4. harvest_overrides_google — content-backed Google beats foreign Harvest twin
  5. foreign_linkedin_twin — LinkedIn whose Harvest website/HQ is country-mismatched
  6. parent_group_as_same_entity — BBVA/Marsh-style parents stay commercial/parent
  7. explicit_suppression — curated reject of domain/LinkedIn slug for a legal name
"""

from __future__ import annotations

from dataclasses import dataclass

from .normalization import (
    core_name,
    extract_registrable_domain,
    is_mismatched_country_domain,
    normalize_text,
    slug_from_linkedin_url,
)


@dataclass(frozen=True)
class MatchSuppression:
    """Explicit reject for a confirmed wrong outcome (last-resort safety net)."""

    # Substring match against normalized core legal name (accents stripped).
    core_contains: str
    reject_domains: frozenset[str] = frozenset()
    reject_linkedin_slugs: frozenset[str] = frozenset()
    note: str = ""


# Curated only after a human-confirmed false positive. Prefer a new soft rule
# + regression test when the pattern generalizes.
SUPPRESSIONS: tuple[MatchSuppression, ...] = (
    MatchSuppression(
        core_contains="aga correduria de seguros arribas",
        reject_domains=frozenset({"arribas.pe"}),
        reject_linkedin_slugs=frozenset({"arribas-corredores-de-seguros-sac"}),
        note="Peru broker twin (José Luis Arribas Berendson); ES target is Badalona S.L.",
    ),
    MatchSuppression(
        core_contains="cover seguros",
        reject_domains=frozenset({"globalcoverseguros.com.co"}),
        note="Colombia Cover twin for Spanish Cover Seguros batch rows.",
    ),
    MatchSuppression(
        core_contains="eureka brokers",
        reject_domains=frozenset({"eureka-ins.it"}),
        note="Italian Eureka twin for Spanish Eureka Brokers S.L.",
    ),
    MatchSuppression(
        core_contains="insurance manager",
        reject_domains=frozenset({"theinsurancemanager.co.uk", "bcbssc.com"}),
        note="UK twin / BlueCross portal for Insurance Manager S.L.",
    ),
)


def _core(legal_name: str) -> str:
    return core_name(legal_name) or normalize_text(legal_name)


def matching_suppressions(legal_name: str) -> list[MatchSuppression]:
    core = _core(legal_name)
    if not core:
        return []
    return [s for s in SUPPRESSIONS if s.core_contains in core]


def is_suppressed_domain(legal_name: str, domain: str | None) -> bool:
    if not domain:
        return False
    d = domain.lower().removeprefix("www.")
    for s in matching_suppressions(legal_name):
        if d in s.reject_domains:
            return True
    return False


def is_suppressed_linkedin(legal_name: str, linkedin_url: str | None) -> bool:
    slug = slug_from_linkedin_url(linkedin_url or "")
    if not slug:
        return False
    slug_n = slug.lower()
    for s in matching_suppressions(legal_name):
        if slug_n in s.reject_linkedin_slugs:
            return True
    return False


def should_block_published_website(
    legal_name: str,
    domain: str | None,
    *,
    country_code: str | None,
) -> tuple[bool, str | None]:
    """Final publish guard: mismatched ccTLD, explicit suppression.

    Generic gTLDs (.com/.net/.org/.eu) are never blocked by country mismatch.
    """
    if not domain:
        return False, None
    if is_suppressed_domain(legal_name, domain):
        return True, "explicit_suppression"
    if is_mismatched_country_domain(domain, country_code):
        return True, "country_mismatch_cctld"
    return False, None


def harvest_signals_country_mismatch(
    *,
    harvest_website: str | None,
    headquarters_text: str | None,
    country_code: str | None,
) -> tuple[bool, str | None]:
    """True when Harvest website TLD or HQ text points at another country."""
    cc = (country_code or "").strip().lower()
    if not cc:
        return False, None
    h_dom = extract_registrable_domain(harvest_website)
    if h_dom and is_mismatched_country_domain(h_dom, cc):
        return True, "harvest_website_country_mismatch"
    # Lightweight HQ country tokens — extend as batches expand.
    hq = normalize_text(headquarters_text or "")
    if not hq:
        return False, None
    foreign_markers: dict[str, tuple[str, ...]] = {
        "es": (
            "peru",
            "lima",
            "colombia",
            "bogota",
            "mexico",
            "brasil",
            "brazil",
            "italy",
            "italia",
            "france",
            "paris",
            "united kingdom",
            "london",
            "portugal",
            "lisbon",
        ),
        "fr": ("spain", "espana", "madrid", "barcelona", "peru", "italy", "italia"),
        "pt": ("spain", "espana", "madrid", "peru", "brazil", "brasil"),
    }
    markers = foreign_markers.get(cc, ())
    if any(m in hq for m in markers):
        # Avoid false hits when HQ also mentions the batch country strongly.
        local_ok = {
            "es": ("spain", "espana", "madrid", "barcelona", "valencia", "badalona"),
            "fr": ("france", "paris", "lyon"),
            "pt": ("portugal", "lisbon", "lisboa", "porto"),
        }.get(cc, ())
        if local_ok and any(t in hq for t in local_ok):
            return False, None
        return True, "harvest_hq_country_mismatch"
    return False, None
