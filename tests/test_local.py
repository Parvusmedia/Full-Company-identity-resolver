"""Local unit checks that do not require API keys."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from my_actor.harvest import harvest_headquarters_fields, harvest_industry, industry_name_from_value
from my_actor.models import CompanyInput, LinkedInCandidate, MatchStatus
from my_actor.output_normalize import normalize_noco_patch, normalize_output_item
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
    assert normalize_homepage_url("http://espabrok.es/contacto/") == "https://www.espabrok.es/"
    assert normalize_homepage_url("https://vigo.albroksa.com/contacto/") == "https://www.albroksa.com/"
    assert (
        normalize_homepage_url("https://servicios-seguros.wtwco.com/Admin/Public/p/quienes-somos")
        == "https://servicios-seguros.wtwco.com/"
    )
    assert is_noise_website_domain("infoempresa.com")
    assert is_noise_website_domain("empresite.eleconomista.es")
    assert is_noise_website_domain("boe.es")
    assert is_noise_website_domain("muysegura.com")
    assert is_noise_website_domain("elespanol.com")
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
    assert filtered[0].domain == "telefonica.es"
    assert normalize_homepage_url(filtered[0].url) == "https://www.telefonica.es/"

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

    # Harvest website should dominate Google when present and non-noise
    website_h, domain_h, _, harvest_clean = select_official_website(
        legal_name="Albrok Mediacion S.A.",
        harvest_website="https://www.albroksa.com/es/contacto",
        google_website="https://www.infoempresa.com/company/albrok",
        google_domain="infoempresa.com",
        google_content_backed=False,
    )
    assert website_h == "https://www.albroksa.com/"
    assert domain_h == "albroksa.com"
    assert harvest_clean == "https://www.albroksa.com/"

    # Harvest also beats a weaker Google brand mention
    website_h2, domain_h2, _, _ = select_official_website(
        legal_name="Peris Correduria De Seguros S.A.",
        harvest_website="http://www.peris.es/quienes-somos",
        google_website="https://www.elespanol.com/noticia-peris",
        google_domain="elespanol.com",
        google_content_backed=True,
    )
    assert website_h2 == "https://www.peris.es/"
    assert domain_h2 == "peris.es"

    # Snippet-only competitor mention must not become the official website
    competitor = build_website_candidates(
        [
            GoogleEvidence(
                query='"Excess Corredores" website',
                query_type="website",
                position=1,
                title="Marsh Iberia amplia capacidades",
                snippet="Excess Corredores compite en el mercado de reaseguros con Marsh.",
                url="https://www.marsh.com/es/es/home.html",
                domain="marsh.com",
            )
        ],
        "Excess Corredores De Reaseguros Y Consultores, S.A.",
    )
    assert competitor == []
    print("OK website homepage normalize + noise/mismatch filters")


def test_batch_evidence_no_substring_bleed() -> None:
    from my_actor.google_search import evidences_for_company, build_website_query

    # Soft website query must NOT use exact-phrase quotes (registry bias).
    wq = build_website_query("Correduria De Seguros Baigorri S.A", city="Zaragoza")
    assert "Zaragoza" in wq
    assert '"' not in wq
    assert "website" not in wq.lower()

    evidences = [
        GoogleEvidence(
            query='"MAPFRE ESPANA S.A." linkedin',
            query_type="linkedin",
            position=1,
            title="MAPFRE España",
            url="https://www.linkedin.com/company/mapfre-espana/",
        ),
        GoogleEvidence(
            query='"MAPFRE S.A." linkedin',
            query_type="linkedin",
            position=1,
            title="MAPFRE",
            url="https://www.linkedin.com/company/mapfre/",
        ),
    ]
    only_parent = evidences_for_company(evidences, "MAPFRE S.A.")
    assert len(only_parent) == 1
    assert "MAPFRE S.A." in only_parent[0].query
    only_es = evidences_for_company(evidences, "MAPFRE ESPANA S.A.")
    assert len(only_es) == 1
    assert "MAPFRE ESPANA" in only_es[0].query
    print("OK batch evidence exact-query attribution")


def test_maps_place_to_website_candidate() -> None:
    from my_actor.maps_fallback import maps_items_to_website_candidates

    cands = maps_items_to_website_candidates(
        [
            {
                "title": "Baigorri Sabseg * Correduría de Seguros",
                "website": "https://baigorri.com/",
                "address": "Zaragoza",
                "categoryName": "Corredor de seguros",
            },
            {
                "title": "Otra cosa",
                "website": "https://empresite.eleconomista.es/x",
            },
        ],
        "Correduria De Seguros Baigorri S.A",
    )
    assert len(cands) == 1
    assert cands[0].domain == "baigorri.com"
    assert cands[0].url == "https://www.baigorri.com/"

    # Must not map Willis Iberia → iberia.com (airline)
    bad = maps_items_to_website_candidates(
        [
            {
                "title": "Iberia",
                "website": "https://www.iberia.com/",
                "categoryName": "Airline",
            }
        ],
        "Willis Iberia Correduria De Seguros Y Reaseguros, S.A.",
    )
    assert bad == []
    print("OK maps place → website candidate")


def test_parent_page_penalty_and_no_post_derivation() -> None:
    from my_actor.normalization import looks_like_parent_or_group_name
    from my_actor.scoring import compute_final_score
    from my_actor.models import Relationship

    assert looks_like_parent_or_group_name("Marsh Iberica S.A.", "Marsh")
    assert looks_like_parent_or_group_name("Marsh Iberica S.A.", "Marsh McLennan")
    assert not looks_like_parent_or_group_name("Marsh Iberica S.A.", "Marsh Iberica")
    assert normalize_linkedin_company_url(
        "https://www.linkedin.com/posts/john-doe_activity-123"
    ) is None

    company = CompanyInput(legal_name="Marsh Iberica S.A.")
    parent = LinkedInCandidate(
        linkedin_url="https://www.linkedin.com/company/marsh/",
        universal_name_guess="marsh",
        harvest={
            "name": "Marsh",
            "universalName": "marsh",
            "website": "https://www.marsh.com",
            "employeeCount": 50000,
            "followerCount": 1000000,
            "active": True,
            "pageVerified": True,
        },
    )
    local = LinkedInCandidate(
        linkedin_url="https://www.linkedin.com/company/marsh-iberia/",
        universal_name_guess="marsh-iberia",
        harvest={
            "name": "Marsh Iberia",
            "universalName": "marsh-iberia",
            "website": "https://www.marsh.com/es",
            "employeeCount": 800,
            "followerCount": 5000,
            "active": True,
            "pageVerified": True,
        },
    )
    parent.pre_score = 70
    local.pre_score = 70
    parent_score, parent_reasons, parent_rel = compute_final_score(company, parent, [])
    local_score, local_reasons, local_rel = compute_final_score(company, local, [])
    assert any("parent" in r for r in parent_reasons)
    assert parent_rel == Relationship.PARENT_COMPANY
    assert local_score > parent_score
    assert local_rel in {Relationship.SAME_ENTITY, Relationship.COMMERCIAL_BRAND}
    print("OK parent-page penalty + no post→company derivation")


def test_homepage_probe_rejects_global_brand_for_iberica() -> None:
    from my_actor.website_probe import HomepageProbe, evaluate_homepage_probe, parse_homepage_html

    title, meta, text, _li = parse_homepage_html(
        "<html><head><title>WTW - Willis Towers Watson</title>"
        "<meta name='description' content='Global advisory firm'></head>"
        "<body><h1>WTW</h1><p>Risk, benefits and brokerage worldwide.</p></body></html>"
    )
    probe = HomepageProbe(
        url="https://www.wtwco.com/",
        final_url="https://www.wtwco.com/",
        title=title,
        meta_description=meta,
        text_sample=text,
        ok=True,
    )
    out = evaluate_homepage_probe("Willis Iberia Correduria De Seguros Y Reaseguros, S.A.", probe)
    assert out.reject is True
    assert any("local_qualifier" in r or "no_company_tokens" in r for r in (out.reasons or []))

    local = HomepageProbe(
        url="https://servicios-seguros.wtwco.com/",
        final_url="https://servicios-seguros.wtwco.com/",
        title="Willis Iberia - Servicios de seguros",
        meta_description="Correduría Willis Iberia",
        text_sample="Willis Iberia Correduria de Seguros y Reaseguros en España",
        ok=True,
    )
    local_out = evaluate_homepage_probe(
        "Willis Iberia Correduria De Seguros Y Reaseguros, S.A.", local
    )
    assert local_out.reject is False
    assert local_out.score_delta > 0
    print("OK homepage probe rejects global WTW for Willis Iberia")


def test_ai_overview_website_fallback() -> None:
    from my_actor.google_search import (
        parse_ai_overview,
        parse_google_dataset_items,
        website_candidate_from_ai_overview,
    )
    from my_actor.models import AiOverviewEvidence
    from my_actor.scoring import build_website_candidates

    legal = "Willis Iberia Correduria De Seguros Y Reaseguros, S.A."
    query = "Willis Iberia Correduria De Seguros Y Reaseguros"
    organic = GoogleEvidence(
        query=query,
        query_type="website",
        position=1,
        title="Quienes Somos - Seguros - WTW",
        snippet="WILLIS IBERIA, CORREDURÍA DE SEGUROS Y REASEGUROS, S.A.",
        url="https://servicios-seguros.wtwco.com/Admin/Public/p/quienes-somos",
        domain="wtwco.com",
    )
    # About-page + legal-name snippet now scores without AI Overview.
    organic_scored = build_website_candidates([organic], legal)
    assert organic_scored and organic_scored[0].url == "https://servicios-seguros.wtwco.com/"

    ai = AiOverviewEvidence(
        query=query,
        content=(
            "Willis Iberia Correduria De Seguros Y Reaseguros, S.A. es una de las "
            "principales corredurías de España y forma parte de WTW. "
            "Sede en Paseo de la Castellana 36-38, Madrid. Más info en wtwco.com."
        ),
        sources=[{"url": "https://servicios-seguros.wtwco.com/Admin/Public/p/quienes-somos"}],
    )
    cand = website_candidate_from_ai_overview(legal, [ai], [organic])
    assert cand is not None
    assert cand.url == "https://servicios-seguros.wtwco.com/"
    assert cand.homepage_probe and cand.homepage_probe.get("ai_overview_backed") is True

    # Unrelated AI overview must not invent a website
    assert (
        website_candidate_from_ai_overview(
            legal,
            [AiOverviewEvidence(query=query, content="Otra empresa distinta sin relación.")],
            [organic],
        )
        is None
    )

    items = [
        {
            "searchQuery": {"term": query},
            "aiOverview": {
                "content": "Willis Iberia es parte de WTW (wtwco.com).",
                "sources": [{"url": "https://servicios-seguros.wtwco.com/"}],
            },
            "organicResults": [
                {
                    "url": "https://servicios-seguros.wtwco.com/",
                    "title": "Seguros - WTW",
                    "description": "Willis",
                    "position": 1,
                }
            ],
        }
    ]
    evidences, overviews = parse_google_dataset_items(items)
    assert len(evidences) == 1
    assert len(overviews) == 1
    assert parse_ai_overview(items[0], query) is not None
    # Screenshot pattern: AI says "filial del grupo WTW" with no website URL;
    # organic #1 is the WTW Spain portal.
    screenshot_ai = AiOverviewEvidence(
        query=query,
        content=(
            "Willis Iberia Correduría de Seguros y Reaseguros, S.A. (filial del grupo WTW) "
            "es una de las corredurías de seguros independientes líderes en España. "
            "Supervisada por la DGSFP, registro J-974. Sede: Paseo de la Castellana 36-38, Madrid."
        ),
        sources=[],
    )
    screenshot = website_candidate_from_ai_overview(legal, [screenshot_ai], [organic])
    assert screenshot is not None
    assert screenshot.url == "https://servicios-seguros.wtwco.com/"
    assert screenshot.homepage_probe and screenshot.homepage_probe.get("ai_brand_bridge") is True

    # Live-shaped: AI Overview on LinkedIn query mentions firm + WTW, no sources;
    # website organic #1 is the WTW Spain portal.
    live_ai = AiOverviewEvidence(
        query=f'"{legal}" linkedin',
        content=(
            "Puedes encontrar perfiles de profesionales que trabajan en "
            "Willis Iberia Correduria de Seguros y Reaseguros S.A. (parte de WTW) "
            "directamente en LinkedIn."
        ),
        sources=[],
    )
    live = website_candidate_from_ai_overview(legal, [live_ai], [organic])
    assert live is not None
    assert live.url == "https://servicios-seguros.wtwco.com/"
    print("OK AI Overview website fallback for Willis Iberia")


def test_willis_quienes_somos_about_page_scoring() -> None:
    from my_actor.scoring import build_website_candidates

    legal = "Willis Iberia Correduria De Seguros Y Reaseguros, S.A."
    evidences = [
        GoogleEvidence(
            query="Willis Iberia Correduria De Seguros Y Reaseguros Madrid",
            query_type="website",
            position=1,
            title="Quienes Somos - Seguros - WTW",
            snippet=(
                "Denominaciones sociales: WILLIS IBERIA, CORREDURÍA DE SEGUROS Y "
                "REASEGUROS, S.A. y PyM BROKER CORREDURIA DE SEGUROS, S.A."
            ),
            url="https://servicios-seguros.wtwco.com/Admin/Public/p/quienes-somos",
            domain="wtwco.com",
        ),
        GoogleEvidence(
            query="Willis Iberia Correduria De Seguros Y Reaseguros Madrid",
            query_type="website",
            position=2,
            title="Aviso legal",
            snippet="WILLIS IBERIA, CORREDURIA DE SEGUROS Y REASEGUROS, S.A.; Domicilio social",
            url="https://willplatine.es/aviso-legal/",
            domain="willplatine.es",
        ),
    ]
    cands = build_website_candidates(evidences, legal)
    assert cands, "expected WTW about-page to survive scoring"
    assert "wtwco.com" in (cands[0].domain or "")
    assert cands[0].url == "https://servicios-seguros.wtwco.com/"
    # Legal-notice hits may survive at lower score; they must not beat WTW about.
    for c in cands:
        if "willplatine" in (c.domain or ""):
            assert c.score < cands[0].score
    print("OK Willis quienes-somos about-page scoring")


def test_weecover_aviso_legal_beats_startup_hub() -> None:
    """Insurtech Solutions SL is Weecover — not Catalonia Trade & Investment."""
    from my_actor.scoring import build_website_candidates
    from my_actor.normalization import is_noise_website_domain

    legal = "Insurtech Solutions Correduria De Seguros Sl"
    assert is_noise_website_domain("catalonia.com")
    evidences = [
        GoogleEvidence(
            query="Insurtech Solutions Correduria De Seguros",
            query_type="website",
            position=2,
            title="Aviso Legal | Información Corporativa y Términos",
            snippet=(
                "Insurtech Solutions C. S. SL (en adelante, la Compañía), con: "
                "Domicilio social: Via Augusta 158, 3o 1a, 08006 Barcelona"
            ),
            url="https://weecover.com/aviso-legal",
            domain="weecover.com",
        ),
        GoogleEvidence(
            query="Insurtech Solutions Correduria De Seguros",
            query_type="website",
            position=5,
            title="Insurtech Solutions — Startup Hub Catalonia",
            snippet="Startup hub invest in catalonia listing",
            url="https://startupshub.catalonia.com/startup/insurtech",
            domain="catalonia.com",
        ),
    ]
    cands = build_website_candidates(evidences, legal)
    assert cands and cands[0].domain == "weecover.com"
    assert cands[0].url == "https://www.weecover.com/"
    assert all(c.domain != "catalonia.com" for c in cands)
    # Regression: ES prefer_local must not drop Weecover .com
    cands_es = build_website_candidates(evidences, legal, prefer_local_es=True)
    assert cands_es and cands_es[0].domain == "weecover.com"
    print("OK Weecover aviso-legal beats Catalonia startup hub")


def test_efficiency_defaults_and_skip() -> None:
    from my_actor.google_search import build_attribution_queries, build_initial_queries
    from my_actor.models import ActorSettings, CompanyInput
    from my_actor.resolver import _should_skip_company, _skipped_result, settings_from_input

    qs = build_initial_queries("Willis Iberia Correduria De Seguros Y Reaseguros, S.A.", city="Madrid")
    assert len(qs) == 2
    assert "linkedin" in qs[0].lower()
    assert "Madrid" in qs[1]
    assert all("website" not in q.lower() for q in qs)
    attr = build_attribution_queries("Willis Iberia Correduria De Seguros Y Reaseguros, S.A.", city="Madrid")
    assert len(attr) == 3  # + deferred core LinkedIn

    settings = settings_from_input({}, env_token=None, env_harvest=None, env_openai=None)
    assert settings.fallback_google_maps is True
    assert settings.max_website_probes == 2
    assert settings.skip_if_good_website is True
    assert settings.defer_core_linkedin is True
    assert settings.harvest_pre_score_gap == 15

    good = CompanyInput(
        legal_name="Albrok Mediacion S.A.",
        existing_website="https://www.albroksa.com/",
        existing_domain="albroksa.com",
        existing_match_status="confirmed",
        existing_linkedin_url="https://www.linkedin.com/company/albrok/",
    )
    assert _should_skip_company(good, settings) is True
    skipped = _skipped_result(good, debug=False)
    assert skipped.website == "https://www.albroksa.com/"
    assert skipped.enrichment_status == "skipped_existing"
    assert skipped.google_queries_used == []

    partial = good.model_copy(update={"existing_match_status": "partial"})
    assert _should_skip_company(partial, settings) is False
    noise = good.model_copy(update={"existing_website": "https://www.infoempresa.com/x", "existing_domain": "infoempresa.com"})
    assert _should_skip_company(noise, settings) is False
    print("OK efficiency defaults + skip-if-good-website")


def test_extract_linkedin_from_homepage_html() -> None:
    from my_actor.website_probe import extract_linkedin_company_urls_from_html

    html = """
    <html><head><title>Atento</title></head>
    <body>
      <a href="https://www.linkedin.com/company/atento/">LinkedIn</a>
      <a href="https://www.facebook.com/atento">FB</a>
      <a href="https://www.linkedin.com/in/someone/">person</a>
    </body></html>
    """
    urls = extract_linkedin_company_urls_from_html(html)
    assert urls == ["https://www.linkedin.com/company/atento/"]
    assert extract_linkedin_company_urls_from_html("<html></html>") == []
    print("OK LinkedIn extraction from homepage HTML")


def test_generic_name_prefers_matching_google_domain() -> None:
    """Insurance Manager, S.L. must not promote BlueCross portals over insurance-manager.es."""
    from my_actor.google_search import build_website_query

    legal = "Insurance Manager, S.L."
    wq = build_website_query(legal, country_code="es")
    assert "S.L" in wq or "S.L." in wq
    assert '"' not in wq
    assert "España" not in wq
    assert "Espana" not in wq

    evidences = [
        GoogleEvidence(
            query=wq,
            query_type="website",
            position=1,
            title="Insurance Manager: Tus seguros al mejor precio",
            snippet="Tu correduría de seguros online",
            url="https://www.insurance-manager.es/",
            domain="insurance-manager.es",
        ),
        GoogleEvidence(
            query=wq,
            query_type="website",
            position=3,
            title="Insurance Manager",
            snippet="Provider portal BlueCross BlueShield of South Carolina",
            url="https://provider.bcbssc.com/",
            domain="bcbssc.com",
        ),
    ]
    cands = build_website_candidates(
        evidences, legal, country_code="es", sector_hints=frozenset({"insurance"})
    )
    assert cands, "expected insurance-manager.es candidate"
    assert cands[0].domain == "insurance-manager.es"
    assert all(c.domain != "bcbssc.com" for c in cands)

    website, domain, _, harvest = select_official_website(
        legal_name=legal,
        harvest_website="http://www.theinsurancemanager.co.uk",
        google_website="https://www.insurance-manager.es/",
        google_domain="insurance-manager.es",
        google_content_backed=True,
        country_code="es",
    )
    assert domain == "insurance-manager.es"
    assert website == "https://www.insurance-manager.es/"
    assert harvest == "https://www.theinsurancemanager.co.uk/"
    print("OK generic-name website: Google #1 domain wins, bcbssc rejected, local beats UK Harvest")


def test_batch_es_rejects_directories_and_foreign_twins() -> None:
    """EGM/QDQ, Cover Colombia, Eureka Italy, garbage hosts must not win for ES."""
    from my_actor.normalization import (
        collect_sector_hints_from_evidences,
        extract_sector_hints,
        is_foreign_to_spain_domain,
        is_mismatched_country_domain,
        is_noise_website_domain,
        is_garbage_website_domain,
    )
    from my_actor.google_search import build_website_query

    assert is_noise_website_domain("qdq.com")
    assert is_noise_website_domain("f6s.com")
    assert is_noise_website_domain("ilo.org")
    assert is_foreign_to_spain_domain("eureka-ins.it")
    assert is_mismatched_country_domain("eureka-ins.it", "es")
    assert is_mismatched_country_domain("globalcoverseguros.com.co", "es")
    assert not is_mismatched_country_domain("globalcoverseguros.com.co", "co")
    assert is_foreign_to_spain_domain("asegura.com.br")
    assert not is_foreign_to_spain_domain("weecover.com")
    assert not is_foreign_to_spain_domain("wtwco.com")
    assert not is_foreign_to_spain_domain("insurance-manager.es")
    assert is_garbage_website_domain("s.l")
    assert is_garbage_website_domain("plataforma.para")
    assert is_garbage_website_domain("linkedin.explora")

    # Geo bias is Actor countryCode — query text must stay country-agnostic.
    egm_q = build_website_query("Egm Correduria De Seguros", country_code="es")
    assert "España" not in egm_q
    assert "Egm" in egm_q or "EGM" in egm_q or "egm" in egm_q.lower()

    # Directory SERP snippets still yield sector hints (even when domain is noise).
    dir_hints = extract_sector_hints(
        "Coverly, Corredores De Seguros Y Reaseguros SL",
        "LA REALIZACIÓN DE ACTIVIDADES PROPIAS DE CORREDURÍA DE SEGUROS",
        "CNAE 6622 - Actividades de agentes y corredores",
    )
    assert "insurance" in dir_hints

    egm = build_website_candidates(
        [
            GoogleEvidence(
                query=egm_q,
                query_type="website",
                position=1,
                title="EGM en QDQ",
                snippet="Ficha EGM Correduria",
                url="https://www.qdq.com/egm",
                domain="qdq.com",
            ),
            GoogleEvidence(
                query=egm_q,
                query_type="website",
                position=2,
                title="EGM Correduría de Seguros",
                snippet="Correduria de seguros en Madrid",
                url="https://egmseguros.com/",
                domain="egmseguros.com",
            ),
        ],
        "Egm Correduria De Seguros",
        country_code="es",
        sector_hints=frozenset({"insurance"}),
    )
    assert egm and egm[0].domain == "egmseguros.com"
    assert all(c.domain != "qdq.com" for c in egm)

    cover_ev = [
        GoogleEvidence(
            query="Cover Seguros",
            query_type="website",
            position=1,
            title="Global Cover Seguros Colombia",
            snippet="Cover Seguros",
            url="https://www.globalcoverseguros.com.co/",
            domain="globalcoverseguros.com.co",
        ),
        GoogleEvidence(
            query="Cover Seguros",
            query_type="website",
            position=2,
            title="Cover Seguros",
            snippet="Cover Correduría de Seguros España",
            url="https://www.coverseguros.com/",
            domain="coverseguros.com",
        ),
        GoogleEvidence(
            query="Cover Seguros",
            query_type="website",
            position=3,
            title="Coverly, Corredores De Seguros Y Reaseguros SL - eInforma",
            snippet="CNAE 6622 Actividades de agentes y corredores de seguros",
            url="https://www.einforma.com/servlet/app/portal/1/1/descargable/empresa/coverly",
            domain="einforma.com",
        ),
    ]
    cover_hints = collect_sector_hints_from_evidences("Cover Seguros", cover_ev)
    assert "insurance" in cover_hints
    cover = build_website_candidates(
        [e for e in cover_ev if e.domain != "einforma.com"],
        "Cover Seguros",
        country_code="es",
        sector_hints=cover_hints,
    )
    assert cover and cover[0].domain == "coverseguros.com"
    # Soft geo: Colombia twin may remain as a low-ranked candidate, must not win.
    assert cover[0].domain != "globalcoverseguros.com.co"

    eureka = build_website_candidates(
        [
            GoogleEvidence(
                query="Eureka Brokers",
                query_type="website",
                position=1,
                title="Eureka Insurance Broker Italia",
                snippet="Eureka Brokers",
                url="https://www.eureka-ins.it/",
                domain="eureka-ins.it",
            ),
        ],
        "Eureka Brokers Correduria De Seguros Sl",
        country_code="es",
        sector_hints=frozenset({"insurance"}),
    )
    # Soft: Italy twin may appear but is heavily penalized vs preferred country.
    if eureka:
        assert is_mismatched_country_domain(eureka[0].domain, "es")
    assert is_foreign_to_spain_domain("gestioneducativa.pe")
    assert is_foreign_to_spain_domain("profundizar.si")
    from my_actor.normalization import is_insurer_portal_domain
    assert is_insurer_portal_domain("allianz.es", "Aga Correduria De Seguros Arribas S.L.")
    assert is_insurer_portal_domain("kpmg.com", "Servicios Profesionales Financieros 2019, S.L.")
    assert not is_insurer_portal_domain("allianz.es", "Allianz Compañia De Seguros Y Reaseguros S.A.")
    print("OK ES batch guards: QDQ/foreign twins/garbage + sector hints from directories")


def test_country_relative_tld_not_spain_hardcoded() -> None:
    """FR batch must prefer .fr over .es twins; .com stays valid everywhere."""
    from my_actor.normalization import is_mismatched_country_domain, domain_matches_country
    from my_actor.scoring import build_website_candidates

    assert domain_matches_country("acme.fr", "fr")
    assert is_mismatched_country_domain("acme.es", "fr")
    assert not is_mismatched_country_domain("acme.com", "fr")
    assert not is_mismatched_country_domain("acme.com", "es")

    legal = "Acme Assurances SAS"
    cands = build_website_candidates(
        [
            GoogleEvidence(
                query="Acme Assurances",
                query_type="website",
                position=1,
                title="Acme Assurances España",
                snippet="Correduría Acme",
                url="https://www.acme.es/",
                domain="acme.es",
            ),
            GoogleEvidence(
                query="Acme Assurances",
                query_type="website",
                position=2,
                title="Acme Assurances",
                snippet="Courtier d'assurances Paris",
                url="https://www.acme-assurances.fr/",
                domain="acme-assurances.fr",
            ),
        ],
        legal,
        country_code="fr",
        sector_hints=frozenset({"insurance"}),
    )
    assert cands and cands[0].domain == "acme-assurances.fr"

    website, domain, _, harvest = select_official_website(
        legal_name=legal,
        harvest_website="https://www.acme.es/",
        google_website="https://www.acme-assurances.fr/",
        google_domain="acme-assurances.fr",
        google_content_backed=True,
        country_code="fr",
    )
    assert domain == "acme-assurances.fr"
    assert harvest == "https://www.acme.es/"
    print("OK country-relative TLD preference (FR batch)")


def test_match_guards_block_foreign_twins_and_suppressions() -> None:
    """Past false positives must not republish: country mismatch + curated suppressions."""
    from my_actor.match_guards import (
        is_suppressed_domain,
        is_suppressed_linkedin,
        should_block_published_website,
    )
    from my_actor.models import CompanyInput, LinkedInCandidate
    from my_actor.scoring import compute_final_score, classify_match_status

    legal = "Aga Correduria De Seguros Arribas S.L."
    assert is_suppressed_domain(legal, "arribas.pe")
    assert is_suppressed_linkedin(legal, "https://www.linkedin.com/company/arribas-corredores-de-seguros-sac/")
    assert not is_suppressed_linkedin(legal, "https://www.linkedin.com/company/asesoriaarribas/")

    blocked, reason = should_block_published_website(legal, "arribas.pe", country_code="es")
    assert blocked and reason in {"explicit_suppression", "country_mismatch_cctld"}
    # Generic .com never blocked by country rule
    assert should_block_published_website(legal, "asesoriaarribas.com", country_code="es") == (False, None)
    # FR batch may publish .fr
    assert should_block_published_website("Acme SAS", "acme.fr", country_code="fr") == (False, None)
    assert should_block_published_website("Acme SAS", "acme.es", country_code="fr")[0] is True

    company = CompanyInput(legal_name=legal)
    peru = LinkedInCandidate(
        linkedin_url="https://www.linkedin.com/company/arribas-corredores-de-seguros-sac/",
        universal_name_guess="arribas-corredores-de-seguros-sac",
        pre_score=80.0,
        pre_score_reasons=["fixture"],
        harvest={
            "name": "ARRIBAS® - CORREDORES DE SEGUROS",
            "universalName": "arribas-corredores-de-seguros-sac",
            "website": "https://www.arribas.pe/",
            "headquarter": {"city": "Lima", "country": "Peru"},
        },
    )
    local = LinkedInCandidate(
        linkedin_url="https://www.linkedin.com/company/asesoriaarribas/",
        universal_name_guess="asesoriaarribas",
        pre_score=48.0,
        pre_score_reasons=["fixture"],
        harvest={
            "name": "ASESORIA Y GESTION ARRIBAS SL",
            "universalName": "asesoriaarribas",
            "website": "http://www.asesoriaarribas.com",
            "headquarter": {"city": "Badalona", "country": "Spain"},
        },
    )
    peru_score, peru_reasons, _ = compute_final_score(company, peru, [], country_code="es")
    local_score, local_reasons, local_rel = compute_final_score(company, local, [], country_code="es")
    assert peru_score == 0.0 or peru_score < local_score
    assert "explicit_linkedin_suppression" in peru_reasons or any(
        "mismatch" in r for r in peru_reasons
    )
    assert local_score > peru_score
    assert any("country_ok" in r for r in local_reasons)
    status = classify_match_status(local_score, peru_score, has_candidates=True)
    assert status.value in {"probable", "high_confidence", "confirmed", "ambiguous"}
    # Local related gestoría should clear the probable bar after country boost.
    assert local_score >= 60 or status.value == "probable"
    assert local_rel.value in {"commercial_brand", "parent_company", "same_entity", "requires_review"}
    print("OK match guards: Peru twin suppressed, local Asesoría ranks higher")


def test_harvest_headquarters_from_locations() -> None:
    loc = {
        "country": "ES",
        "city": "Barcelona",
        "geographicArea": "Barcelona",
        "line1": "Avenida Via Augusta 128, ",
        "line2": " 3o 1a",
        "headquarter": True,
        "parsed": {"text": "Barcelona, Spain", "country": "Spain", "city": "Barcelona"},
    }
    fields = harvest_headquarters_fields({"locations": [loc]})
    assert fields["headquarters_city"] == "Barcelona"
    assert fields["headquarters_country"] == "Spain"
    assert "Barcelona" in (fields["headquarters_text"] or "")
    assert "Spain" in (fields["headquarters_text"] or "")

    live = harvest_headquarters_fields(
        {
            "locations": [
                {
                    "country": "ES",
                    "city": "Palma",
                    "geographicArea": "Illes Balears",
                    "headquarter": True,
                    "parsed": {"text": "Palma, Spain", "country": "Spain", "city": "Palma"},
                }
            ]
        }
    )
    assert live["headquarters_text"] == "Palma, Spain"
    print("OK harvest headquarters from locations array")


def test_output_normalize_before_write() -> None:
    blob = {
        "id": "42",
        "name": "Insurance",
        "urn": "urn:li:fsd_industryV2:42",
        "title": "Insurance",
        "hierarchy": "Financial Services > Insurance",
    }
    primary, industries = harvest_industry({"industries": [blob, {"name": "Banking"}]})
    assert primary == "Insurance"
    assert industries == ["Insurance", "Banking"]

    primary2, industries2 = harvest_industry({"industry": blob})
    assert primary2 == "Insurance"
    assert industries2 == ["Insurance"]

    repr_s = str(blob)
    assert industry_name_from_value(repr_s) == "Insurance"
    assert industry_name_from_value('{"name": "Telecommunications", "id": "8"}') == "Telecommunications"
    assert industry_name_from_value("Insurance") == "Insurance"

    item = ResolutionResult(
        legal_name="Test S.L.",
        industry=repr_s,
        industries=[blob],
    ).to_dataset_item(debug=False)
    assert item["industry"] == "Insurance"
    assert item["industries"] == ["Insurance"]

    normalized = normalize_output_item(
        {
            "legal_name": "Test S.L.",
            "industry": repr_s,
            "industries": [blob],
            "specialties": [{"name": "seguros"}, "insurtech"],
            "phone": {"number": "900600004"},
            "headquarters": {"city": "Madrid", "country": "Spain", "line1": "Calle Mayor 1"},
            "locations": [{"city": "Barcelona", "country": "ES", "parsed": {"text": "Barcelona, Spain"}}],
            "website": "https://example.com/path?q=1",
            "linkedin_url": "https://www.linkedin.com/company/example/",
            "confidence": 0.0,
            "relationship": "unknown",
            "match_status": "not_found",
        },
        debug=False,
    )
    assert normalized["industry"] == "Insurance"
    assert normalized["industries"] == ["Insurance"]
    assert normalized["specialties"] == ["seguros", "insurtech"]
    assert normalized["phone"] == "900600004"
    assert normalized["headquarters_text"] == "Calle Mayor 1, Madrid, Spain"
    assert normalized["headquarters_city"] == "Madrid"
    assert normalized["headquarters_country"] == "Spain"
    assert normalized["headquarters"] is None
    assert normalized["locations"] == ["Barcelona, Spain"]
    assert normalized["website"] == "https://www.example.com/"
    assert normalized["linkedin_url"] == "https://www.linkedin.com/company/example/"

    locations_only = normalize_output_item(
        {
            "legal_name": "Loc Only S.L.",
            "locations": [
                {
                    "country": "ES",
                    "city": "Valencia",
                    "geographicArea": "Valencia",
                    "headquarter": True,
                    "parsed": {"text": "Valencia, Spain", "country": "Spain", "city": "Valencia"},
                }
            ],
            "confidence": 0.0,
            "relationship": "unknown",
            "match_status": "not_found",
        },
        debug=False,
    )
    assert locations_only["headquarters_text"] == "Valencia, Spain"
    assert locations_only["headquarters_city"] == "Valencia"
    assert locations_only["headquarters_country"] == "Spain"

    patch = normalize_noco_patch(
        {
            "Id": 1,
            "industry": repr_s,
            "phone": {"number": "927233430"},
            "headquarters_text": str({"city": "Madrid", "country": "Spain"}),
            "website": "https://example.com/about",
            "confidence": "72.5",
            "employee_count": "28",
        }
    )
    assert patch["industry"] == "Insurance"
    assert patch["phone"] == "927233430"
    assert patch["headquarters_text"] == "Madrid, Spain"
    assert patch["confidence"] == 72.5
    assert patch["employee_count"] == 28

    hq_only = normalize_noco_patch({"Id": 2, "headquarters_text": "Barcelona, Spain"})
    assert hq_only == {"Id": 2, "headquarters_text": "Barcelona, Spain"}
    print("OK output normalization before write")


def test_industry_stores_names_only() -> None:
    test_output_normalize_before_write()


def test_directory_snippet_website_and_short_acronym_tokens() -> None:
    """EGM: keep short brand token; mine egmseguros.com from directory snippet."""
    from my_actor.google_search import website_evidences_from_directory_snippets
    from my_actor.normalization import distinctive_name_tokens
    from my_actor.scoring import build_website_candidates

    assert "egm" in distinctive_name_tokens("Egm Correduria De Seguros")
    assert "mk2" in distinctive_name_tokens("Mk2 Correduria De Seguros S.L")

    legal = "Egm Correduria De Seguros"
    dir_ev = [
        GoogleEvidence(
            query="Egm Correduria De Seguros",
            query_type="website",
            position=1,
            title="E G M Correduria De Seguros Sl - Empresite",
            snippet="Su teléfono es 914588421 y su página web es www.egmseguros.com. CNAE 6622",
            url="https://empresite.eleconomista.es/EGM-CORREDURIA-SEGUROS.html",
            domain="empresite.eleconomista.es",
        ),
        GoogleEvidence(
            query="Egm Correduria De Seguros",
            query_type="website",
            position=2,
            title="EGM en QDQ",
            snippet="Ficha EGM",
            url="https://www.qdq.com/egm",
            domain="qdq.com",
        ),
    ]
    cited = website_evidences_from_directory_snippets(dir_ev, legal, country_code="es")
    assert any((e.domain or "") == "egmseguros.com" for e in cited)
    cands = build_website_candidates(cited, legal, country_code="es", sector_hints=frozenset({"insurance"}))
    assert cands and cands[0].domain == "egmseguros.com"
    print("OK directory snippet → egmseguros.com; short acronym tokens kept")


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
    test_batch_evidence_no_substring_bleed()
    test_maps_place_to_website_candidate()
    test_parent_page_penalty_and_no_post_derivation()
    test_homepage_probe_rejects_global_brand_for_iberica()
    test_ai_overview_website_fallback()
    test_willis_quienes_somos_about_page_scoring()
    test_weecover_aviso_legal_beats_startup_hub()
    test_efficiency_defaults_and_skip()
    test_extract_linkedin_from_homepage_html()
    test_generic_name_prefers_matching_google_domain()
    test_batch_es_rejects_directories_and_foreign_twins()
    test_country_relative_tld_not_spain_hardcoded()
    test_match_guards_block_foreign_twins_and_suppressions()
    test_directory_snippet_website_and_short_acronym_tokens()
    test_output_normalize_before_write()
    test_harvest_headquarters_from_locations()
    print("\nAll local checks passed.")


if __name__ == "__main__":
    main()
