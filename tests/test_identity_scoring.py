"""Identity scoring: distinctive tokens, directory veto, confidence caps."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from my_actor.google_search import filter_website_evidences
from my_actor.models import CompanyInput, GoogleEvidence, LinkedInCandidate, WebsiteCandidate
from my_actor.normalization import identity_match_tier, is_website_noise_domain
from my_actor.scoring import classify_match_status, compute_final_score, compute_pre_score


def _candidate(
    *,
    url: str,
    harvest_name: str,
    website: str | None = None,
    universal: str | None = None,
    pre_score: float = 70.0,
) -> LinkedInCandidate:
    cand = LinkedInCandidate(
        linkedin_url=url,
        universal_name_guess=universal,
        google_evidences=[
            GoogleEvidence(
                query='"x" linkedin',
                query_type="linkedin",
                position=1,
                title=harvest_name,
                snippet="",
                url=url,
            )
        ],
    )
    cand.pre_score = pre_score
    cand.harvest = {
        "name": harvest_name,
        "website": website,
        "universalName": universal,
        "employeeCount": 50000,
        "followerCount": 200000,
        "active": True,
        "pageVerified": True,
        "industries": ["Government"],
    }
    return cand


def test_identity_tiers() -> None:
    assert (
        identity_match_tier(
            "Talleres Auxiliares De Subcontratacion Industria Navarra Sa",
            "Gobierno de Navarra",
            "gobierno-de-navarra",
            "navarra.es",
        )
        == "weak"
    )
    assert (
        identity_match_tier(
            "Apricot Restauraciones Slu",
            "Publicaciones Alimarket, S.A.",
            "alimarket.es",
        )
        == "weak"
    )
    assert (
        identity_match_tier(
            "Brokalia Diversos, Correduria De Seguros, Sl.",
            "Brokalia",
            "brokalia",
            "brokalia.com",
        )
        in {"strong", "brand"}
    )
    assert (
        identity_match_tier(
            'Mercados De Abastecimientos De Barcelona Sa "Mercabarna"',
            "Mercabarna",
            "mercabarna",
            "mercabarna.es",
        )
        in {"strong", "brand"}
    )
    assert (
        identity_match_tier(
            "De La Uz, S.L.",
            "Grupo de la Uz",
            "grupo-de-la-uz",
        )
        in {"strong", "brand"}
    )
    print("OK identity tiers")


def test_false_positives_capped_below_50() -> None:
    company = CompanyInput(legal_name="Talleres Auxiliares De Subcontratacion Industria Navarra Sa")
    cand = _candidate(
        url="https://www.linkedin.com/company/gobierno-de-navarra-nafarroako-gobernua/",
        harvest_name="Gobierno de Navarra",
        website="https://www.navarra.es/",
        universal="gobierno-de-navarra",
    )
    websites = [WebsiteCandidate(url="https://www.navarra.es/", domain="navarra.es")]
    score, reasons, _rel = compute_final_score(company, cand, websites)
    assert score < 50, score
    assert any("identity_cap_weak" in r for r in reasons)
    assert classify_match_status(score, None, has_candidates=True).value == "not_found"

    company2 = CompanyInput(legal_name="Apricot Restauraciones Slu")
    cand2 = _candidate(
        url="https://www.linkedin.com/company/publicaciones-alimarket-s.a./",
        harvest_name="Publicaciones Alimarket, S.A.",
        website="https://www.alimarket.es/",
        universal="publicaciones-alimarket",
    )
    websites2 = [WebsiteCandidate(url="https://www.alimarket.es/", domain="alimarket.es")]
    score2, reasons2, _ = compute_final_score(company2, cand2, websites2)
    assert score2 < 50, score2
    assert any("identity_cap_weak" in r for r in reasons2)
    print("OK false positives capped below 50")


def test_true_brand_not_dropped() -> None:
    company = CompanyInput(legal_name="Brokalia Diversos, Correduria De Seguros, Sl.")
    cand = _candidate(
        url="https://www.linkedin.com/company/brokalia/",
        harvest_name="Brokalia",
        website="https://www.brokalia.com/",
        universal="brokalia",
        pre_score=70.0,
    )
    websites = [WebsiteCandidate(url="https://www.brokalia.com/", domain="brokalia.com")]
    score, _reasons, _rel = compute_final_score(company, cand, websites)
    assert score >= 50, score
    print("OK true brand kept above 50")


def test_directory_domains_rejected() -> None:
    assert is_website_noise_domain("alimarket.es")
    assert is_website_noise_domain("www.tripadvisor.es")
    ev = GoogleEvidence(
        query='"x" website',
        query_type="website",
        position=1,
        title="Alimarket",
        url="https://www.alimarket.es/empresa/apricot",
    )
    assert filter_website_evidences([ev]) == []
    print("OK directory domain veto")


def test_pre_score_albrok_still_ranks() -> None:
    company = CompanyInput(legal_name="Albrok Mediacion S.A.", city="Madrid")
    url = "https://www.linkedin.com/company/albrok-mediacion/"
    cand = LinkedInCandidate(
        linkedin_url=url,
        universal_name_guess="albrok-mediacion",
        google_evidences=[
            GoogleEvidence(
                query='"Albrok Mediacion S.A." linkedin',
                query_type="linkedin",
                position=1,
                title="Albrok Mediacion | LinkedIn",
                snippet="Madrid",
                url=url,
            ),
            GoogleEvidence(
                query='"Albrok Mediacion S.A." website',
                query_type="website",
                position=2,
                title="Albrok Mediacion",
                snippet="empresa",
                url=url,
            ),
        ],
    )
    score, reasons = compute_pre_score(company, cand)
    assert score > 40
    assert any("multiple_query" in r for r in reasons)
    print("OK Albrok pre-score still ranks")


def main() -> None:
    test_identity_tiers()
    test_false_positives_capped_below_50()
    test_true_brand_not_dropped()
    test_directory_domains_rejected()
    test_pre_score_albrok_still_ranks()
    print("All identity scoring checks passed.")


if __name__ == "__main__":
    main()
