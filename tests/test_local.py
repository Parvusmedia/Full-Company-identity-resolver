"""Local unit checks that do not require API keys."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from my_actor.models import CompanyInput, LinkedInCandidate, MatchStatus
from my_actor.normalization import (
    core_name,
    is_noise_website_domain,
    normalize_homepage_url,
    normalize_linkedin_company_url,
    remove_legal_forms,
    select_official_website,
    should_reject_linkedin_url,
)
from my_actor.scoring import build_website_candidates, classify_match_status, compute_pre_score
from my_actor.models import GoogleEvidence, ResolutionResult
from my_actor.google_search import filter_website_evidences
from my_actor.resolver import parse_input_companies


def test_json_files() -> None:
    for rel in (".actor/actor.json", ".actor/input_schema.json"):
        path = ROOT / rel
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict), rel
        print(f"OK JSON parse: {rel}")


def test_parse_queries() -> None:
    companies = parse_input_companies(
        {"queries": "Albrok Mediacion S.A.\nOtra Empresa S.L.\n\n"}
    )
    assert len(companies) == 2
    assert companies[0].legal_name == "Albrok Mediacion S.A."
    assert companies[1].legal_name == "Otra Empresa S.L."
    print("OK queries -> one company per line")


def test_companies_priority_and_source_id() -> None:
    companies = parse_input_companies(
        {
            "queries": "Ignored S.L.",
            "companies": [
                {
                    "source_id": "pipedrive-123",
                    "legal_name": "Empresa Uno S.L.",
                    "tax_id": "B12345678",
                    "city": "Madrid",
                }
            ],
        }
    )
    assert len(companies) == 1
    assert companies[0].source_id == "pipedrive-123"
    assert companies[0].legal_name == "Empresa Uno S.L."
    print("OK companies priority + source_id")


def test_legal_form_stripping() -> None:
    assert remove_legal_forms("Empresa Uno S.L.") == "Empresa Uno"
    assert remove_legal_forms("Sociedad Ejemplo Sociedad Anónima") == "Sociedad Ejemplo"
    assert core_name("Albrok Mediacion S.A.") == "albrok mediacion"
    print("OK legal form normalization")


def test_linkedin_url_rules_and_dedupe() -> None:
    assert should_reject_linkedin_url("https://www.linkedin.com/in/someone/")
    assert should_reject_linkedin_url("https://www.linkedin.com/jobs/view/123")
    assert should_reject_linkedin_url("https://www.linkedin.com/school/ie-university/")
    assert should_reject_linkedin_url("https://www.linkedin.com/posts/foo-activity-1")
    a = normalize_linkedin_company_url("https://es.linkedin.com/company/albrok-mediacion/about/")
    b = normalize_linkedin_company_url("http://www.linkedin.com/company/albrok-mediacion")
    assert a == b == "https://www.linkedin.com/company/albrok-mediacion/"
    print("OK LinkedIn URL normalize + reject rules")


def test_one_row_and_debug_raw_harvest() -> None:
    company = CompanyInput(legal_name="Empresa Uno S.L.", source_id="x1")
    result = ResolutionResult(
        source_id=company.source_id,
        legal_name=company.legal_name,
        match_status=MatchStatus.NOT_FOUND.value,
        candidates=[{"linkedin_url": "https://www.linkedin.com/company/x/", "raw_harvest": {"element": {"id": 1}}}],
    )
    normal = result.to_dataset_item(debug=False)
    assert "candidates" not in normal
    assert "raw_harvest" not in normal
    debug = result.to_dataset_item(debug=True)
    assert "candidates" in debug
    assert debug["candidates"][0]["raw_harvest"]["element"]["id"] == 1
    print("OK one-row shape + debug raw_harvest gating")


def test_duplicate_urls_single_candidate_scoring() -> None:
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
    # Two candidates with same score must not collapse if kept in a list
    c2 = cand.model_copy()
    c2.pre_score = score
    cand.pre_score = score
    ranked = sorted([cand, c2], key=lambda c: c.pre_score, reverse=True)
    assert len(ranked) == 2
    print("OK pre-score + same-score list ranking")


def test_match_status_gap() -> None:
    assert classify_match_status(92, 91, has_candidates=True).value == "high_confidence"
    assert classify_match_status(92, 70, has_candidates=True).value == "confirmed"
    assert classify_match_status(30, None, has_candidates=True).value == "not_found"
    assert classify_match_status(0, None, has_candidates=False).value == "not_found"
    print("OK match status classification")


def test_website_homepage_and_noise_filter() -> None:
    assert normalize_homepage_url("https://www.telefonica.es/es/nosotros/") == "https://www.telefonica.es/"
    assert normalize_homepage_url("http://espabrok.es/contacto/") == "https://espabrok.es/"
    assert is_noise_website_domain("infoempresa.com")
    assert is_noise_website_domain("empresite.eleconomista.es")
    assert is_noise_website_domain("boe.es")
    assert is_noise_website_domain("muysegura.com")
    assert not is_noise_website_domain("telefonica.es")
    assert not is_noise_website_domain("espabrok.es")

    evidences = [
        GoogleEvidence(
            query='"Pib Group Iberia" website',
            query_type="website",
            position=1,
            title="PIB Group Iberia - Infoempresa",
            url="https://www.infoempresa.com/en-in/es/company/pib-group-iberia",
            domain="infoempresa.com",
        ),
        GoogleEvidence(
            query='"Verspieren Iberica S.A." website',
            query_type="website",
            position=1,
            title="BORME",
            url="https://www.boe.es/diario_borme/txt.php?id=BORME-A-2026-79-28",
            domain="boe.es",
        ),
        GoogleEvidence(
            query='"Telefonica De Espana, S.A.U." website',
            query_type="website",
            position=1,
            title="Telefónica",
            url="https://www.telefonica.es/es/nosotros/",
            domain="telefonica.es",
        ),
    ]
    filtered = filter_website_evidences(evidences)
    assert len(filtered) == 1
    assert filtered[0].url == "https://www.telefonica.es/"
    assert filtered[0].domain == "telefonica.es"

    website, domain, _, _ = select_official_website(
        legal_name="Telefonica De Espana, S.A.U.",
        harvest_website="https://www.telefonica.es/es/nosotros/",
        google_website="https://www.infoempresa.com/company/telefonica",
        google_domain="infoempresa.com",
    )
    assert website == "https://www.telefonica.es/"
    assert domain == "telefonica.es"

    # Mismatched Harvest domain for another company must not win
    website2, domain2, _, _ = select_official_website(
        legal_name="Excess Corredores De Reaseguros Y Consultores, S.A.",
        harvest_website="http://www.espabrok.es",
        google_website="https://www.muysegura.com/articulo-espabrok",
        google_domain="muysegura.com",
    )
    assert website2 is None
    assert domain2 is None

    candidates = build_website_candidates(
        [
            GoogleEvidence(
                query='"Espabrok C.S S.A" website',
                query_type="website",
                position=1,
                title="Artículo sobre Espabrok",
                url="https://www.muysegura.com/carmelo-alonso-espabrok",
                domain="muysegura.com",
            ),
            GoogleEvidence(
                query='"Espabrok C.S S.A" website',
                query_type="website",
                position=2,
                title="Espabrok",
                url="http://www.espabrok.es/quienes-somos/",
                domain="espabrok.es",
            ),
        ],
        "Espabrok C.S S.A",
    )
    assert len(candidates) == 1
    assert candidates[0].domain == "espabrok.es"
    assert candidates[0].url == "https://www.espabrok.es/"
    # Brand/group site: legal name Verspieren, commercial domain alkora.es
    verspieren_candidates = build_website_candidates(
        [
            GoogleEvidence(
                query='"Verspieren Iberica S.A." website',
                query_type="website",
                position=1,
                title="Grupo Verspieren - Alkora EBS Correduría de Seguros y ...",
                snippet=(
                    "El Grupo Verspieren es el principal corredor de seguros con capital "
                    "íntegramente familiar en Francia. Verspieren Ibérica forma parte del grupo."
                ),
                url="https://www.alkora.es/grupo-verspieren",
                domain="alkora.es",
            ),
            GoogleEvidence(
                query='"Verspieren Iberica S.A." website',
                query_type="website",
                position=2,
                title="BORME anuncio",
                snippet="VERSPIEREN IBERICA S.A.",
                url="https://www.boe.es/diario_borme/txt.php?id=BORME-A-2026-79-28",
                domain="boe.es",
            ),
        ],
        "Verspieren Iberica S.A.",
    )
    assert len(verspieren_candidates) == 1
    assert verspieren_candidates[0].domain == "alkora.es"
    assert verspieren_candidates[0].url == "https://www.alkora.es/"

    website_v, domain_v, _, _ = select_official_website(
        legal_name="Verspieren Iberica S.A.",
        harvest_website=None,
        google_website="https://www.alkora.es/",
        google_domain="alkora.es",
        google_content_backed=True,
    )
    assert website_v == "https://www.alkora.es/"
    assert domain_v == "alkora.es"
    print("OK website homepage normalize + noise/mismatch filters")


def main() -> None:
    test_json_files()
    test_parse_queries()
    test_companies_priority_and_source_id()
    test_legal_form_stripping()
    test_linkedin_url_rules_and_dedupe()
    test_one_row_and_debug_raw_harvest()
    test_duplicate_urls_single_candidate_scoring()
    test_match_status_gap()
    test_website_homepage_and_noise_filter()
    print("\nAll local checks passed.")


if __name__ == "__main__":
    main()
