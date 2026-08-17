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
    normalize_linkedin_company_url,
    remove_legal_forms,
    should_reject_linkedin_url,
)
from my_actor.resolver import parse_input_companies
from my_actor.scoring import classify_match_status, compute_pre_score
from my_actor.models import GoogleEvidence, ResolutionResult
from tests.test_load_n8n_vars import test_jwt_aud_and_mcp_skip, test_load_keeps_existing_and_fills_missing


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


def main() -> None:
    test_json_files()
    test_parse_queries()
    test_companies_priority_and_source_id()
    test_legal_form_stripping()
    test_linkedin_url_rules_and_dedupe()
    test_one_row_and_debug_raw_harvest()
    test_duplicate_urls_single_candidate_scoring()
    test_match_status_gap()
    test_jwt_aud_and_mcp_skip()
    test_load_keeps_existing_and_fills_missing()
    print("\nAll local checks passed.")


if __name__ == "__main__":
    main()
