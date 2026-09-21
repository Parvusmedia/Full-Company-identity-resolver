"""Discovery fallbacks: homepage LinkedIn extract + Harvest search helpers."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from my_actor.harvest import harvest_element_from_payload, linkedin_url_from_harvest
from my_actor.homepage import candidate_page_urls, extract_linkedin_company_urls
from my_actor.models import CompanyInput, GoogleEvidence, LinkedInCandidate
from my_actor.resolver import (
    _merge_linkedin_candidate,
    _needs_discovery,
    _search_queries_for_company,
    settings_from_input,
)
from my_actor.scoring import compute_pre_score


def test_extract_linkedin_company_urls() -> None:
    html = """
    <html><body>
      <a href="https://www.linkedin.com/company/albrok-mediacion/about/">LinkedIn</a>
      <a href="//es.linkedin.com/company/albrok-mediacion">ES</a>
      <script type="application/ld+json">
        {"sameAs": ["https://linkedin.com/company/albrok-mediacion"]}
      </script>
      <a href="https://www.linkedin.com/in/someone/">person</a>
      <a href="https://www.linkedin.com/company/jobs/view/1">jobs</a>
    </body></html>
    """
    urls = extract_linkedin_company_urls(html)
    assert urls == ["https://www.linkedin.com/company/albrok-mediacion/"]
    assert extract_linkedin_company_urls("") == []
    print("OK homepage LinkedIn extract + reject profiles/jobs")


def test_candidate_page_urls() -> None:
    pages = candidate_page_urls("https://www.albroksa.com/contacto")
    assert pages[0] == "https://www.albroksa.com/contacto"
    assert pages[1] == "https://www.albroksa.com/"
    assert candidate_page_urls("albroksa.com")[0].startswith("https://")
    print("OK homepage URL candidates include origin")


def test_linkedin_url_from_harvest() -> None:
    assert (
        linkedin_url_from_harvest({"linkedinUrl": "https://es.linkedin.com/company/foo/about"})
        == "https://www.linkedin.com/company/foo/"
    )
    assert (
        linkedin_url_from_harvest({"universalName": "foo-bar"})
        == "https://www.linkedin.com/company/foo-bar/"
    )
    assert linkedin_url_from_harvest({"name": "No URL"}) is None
    payload = {"elements": [{"name": "X", "linkedinUrl": "https://www.linkedin.com/company/x/"}]}
    element = harvest_element_from_payload(payload)
    assert element is not None
    assert linkedin_url_from_harvest(element) == "https://www.linkedin.com/company/x/"
    print("OK Harvest element → LinkedIn URL")


def test_homepage_pre_score_bonus() -> None:
    company = CompanyInput(legal_name="Albrok Mediacion S.A.")
    url = "https://www.linkedin.com/company/albrok-mediacion/"
    google_only = LinkedInCandidate(
        linkedin_url=url,
        universal_name_guess="albrok-mediacion",
        discovery_source="google",
        google_evidences=[],
    )
    homepage = LinkedInCandidate(
        linkedin_url=url,
        universal_name_guess="albrok-mediacion",
        discovery_source="homepage",
        google_evidences=[
            GoogleEvidence(
                query="homepage:https://albroksa.com/",
                query_type="homepage",
                url=url,
            )
        ],
    )
    g_score, g_reasons = compute_pre_score(company, google_only)
    h_score, h_reasons = compute_pre_score(company, homepage)
    assert h_score >= g_score + 14
    assert any("homepage" in r for r in h_reasons)
    print("OK homepage discovery bonus in pre-score")


def test_discovery_flags_and_rollback() -> None:
    on = settings_from_input({}, env_token=None, env_harvest=None, env_openai=None)
    assert on.fallback_harvest_search is True
    assert on.fallback_homepage_linkedin is True
    off = settings_from_input(
        {"fallback_harvest_search": False, "fallback_homepage_linkedin": False},
        env_token=None,
        env_harvest=None,
        env_openai=None,
    )
    assert off.fallback_harvest_search is False
    assert off.fallback_homepage_linkedin is False
    print("OK discovery flags default on; false restores Google-only")


def test_needs_discovery_and_merge() -> None:
    assert _needs_discovery(None, 0.0, 78) is True
    dummy = LinkedInCandidate(linkedin_url="https://www.linkedin.com/company/x/")
    dummy.final_score = 90
    assert _needs_discovery(dummy, 90.0, 78) is False
    assert _needs_discovery(dummy, 40.0, 78) is True

    candidates: list[LinkedInCandidate] = []
    created = _merge_linkedin_candidate(
        candidates,
        "https://es.linkedin.com/company/foo/",
        discovery_source="harvest_search",
    )
    assert created is not None
    assert created.discovery_source == "harvest_search"
    assert len(candidates) == 1
    merged = _merge_linkedin_candidate(
        candidates,
        "https://www.linkedin.com/company/foo/",
        discovery_source="homepage",
        harvest={"name": "Foo"},
    )
    assert merged is None
    assert candidates[0].harvest == {"name": "Foo"}
    print("OK discovery threshold + candidate merge")


def test_search_queries_include_core_name() -> None:
    company = CompanyInput(legal_name="Albrok Mediacion S.A.")
    queries = _search_queries_for_company(company)
    assert queries[0] == "Albrok Mediacion S.A."
    assert "Albrok Mediacion" in queries
    print("OK Harvest search queries use legal + core name")
