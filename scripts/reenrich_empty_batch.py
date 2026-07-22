#!/usr/bin/env python3
"""Re-resolve empty (or pending) NocoDB org rows and PATCH only safe outcomes."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from apify import Actor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from my_actor.harvest import industry_name_from_value
from my_actor.match_guards import is_suppressed_linkedin, should_block_published_website
from my_actor.models import CompanyInput
from my_actor.normalization import (
    domain_label,
    extract_registrable_domain,
    is_garbage_website_domain,
    is_insurer_portal_domain,
    is_noise_website_domain,
)
from my_actor.resolver import resolve_companies_batch, settings_from_input
from my_actor.scoring import name_similarity

BASE = os.environ["NOCO_BASE"].rstrip("/")
TOKEN = os.environ["NOCO_TOKEN"]
TABLE = "mewh1ynmcokfsfi"
HEADERS = {"xc-token": TOKEN, "Content-Type": "application/json"}


def fetch_empty_batch(min_source_id: int = 46) -> list[dict]:
    r = requests.get(
        f"{BASE}/api/v2/tables/{TABLE}/records",
        headers={"xc-token": TOKEN},
        params={"limit": 200},
        timeout=60,
    )
    r.raise_for_status()
    rows = r.json().get("list") or []
    out = []
    for row in rows:
        try:
            sid = int(row.get("source_id") or 0)
        except Exception:
            sid = 0
        if sid < min_source_id:
            continue
        if (row.get("website") or "").strip():
            continue
        out.append(row)
    return out


def _domain_ok(legal_name: str, domain: str | None, *, country_code: str) -> bool:
    if not domain:
        return False
    if is_noise_website_domain(domain) or is_garbage_website_domain(domain):
        return False
    if is_insurer_portal_domain(domain, legal_name):
        return False
    blocked, _ = should_block_published_website(legal_name, domain, country_code=country_code)
    if blocked:
        return False
    return True


def _website_name_plausible(legal_name: str, domain: str | None) -> bool:
    if not domain:
        return False
    sim = name_similarity(legal_name, domain_label(domain) or "")
    # Brand domains often diverge (weecover, asesoriaarribas) — allow mid scores.
    return sim >= 35


def safe_patch_from_result(row: dict, result, *, country_code: str = "es") -> dict:
    item = result.to_dataset_item(debug=False)
    legal = item.get("legal_name") or row.get("legal_name") or row.get("Title")
    status = (item.get("match_status") or "not_found").lower()
    website = item.get("website") or None
    domain = item.get("domain") or extract_registrable_domain(website)
    linkedin = item.get("linkedin_url") or None

    # Guards: never write known-bad / foreign-ccTLD / suppressed outcomes.
    if website and not _domain_ok(legal, domain, country_code=country_code):
        website, domain = None, None
    if website and status in {"not_found", "error"} and not _website_name_plausible(legal, domain):
        # Weak not_found + unrelated domain (tickets, NGOs, …) → keep empty.
        website, domain = None, None
    if website and status == "partial" and not _website_name_plausible(legal, domain):
        website, domain = None, None
    if linkedin and is_suppressed_linkedin(legal, linkedin):
        linkedin = None

    # If we cleared a bad website that came with a foreign LinkedIn, drop LI too
    # when status is not_found / weak.
    if not website and status in {"not_found"} and linkedin:
        # Keep LinkedIn only when score-ish status was upgraded — not_found LI is noise.
        linkedin = None

    enrichment = "enriched" if status in {"confirmed", "high_confidence", "probable"} and linkedin else (
        "partial" if website or (linkedin and status in {"probable", "high_confidence", "confirmed", "ambiguous", "partial"}) else (
            "not_found" if status == "not_found" else status
        )
    )
    if website and not linkedin and status in {"partial", "not_found"}:
        enrichment = "partial"
        if status == "not_found":
            status = "partial"

    queries = item.get("google_queries_used") or []
    queries_str = " | ".join(str(q) for q in queries) if isinstance(queries, list) else str(queries)
    now = datetime.now(timezone.utc).isoformat()

    return {
        "Id": row["Id"],
        "source_id": str(row.get("source_id") or ""),
        "legal_name": legal,
        "Title": legal,
        "commercial_name": item.get("commercial_name") if linkedin else None,
        "linkedin_url": linkedin,
        "website": website,
        "domain": domain,
        "industry": industry_name_from_value(item.get("industry")) if linkedin else None,
        "employee_count": item.get("employee_count") if linkedin else None,
        "followers": item.get("followers") if linkedin else None,
        "phone": item.get("phone") if linkedin else None,
        "headquarters_text": (item.get("headquarters_text") or item.get("headquarters")) if linkedin else None,
        "relationship": item.get("relationship") if (linkedin or website) else "unknown",
        "match_status": status if (website or linkedin) else "not_found",
        "confidence": item.get("confidence") if (website or linkedin) else 0,
        "evidence_summary": item.get("evidence_summary"),
        "candidates_found": item.get("candidates_found"),
        "candidates_enriched": item.get("candidates_enriched"),
        "google_queries_used": queries_str,
        "enrichment_status": enrichment if (website or linkedin) else "not_found",
        "enriched_at": now,
        "error": item.get("error"),
    }


async def main() -> None:
    rows = fetch_empty_batch(46)
    print(f"Empty batch rows: {len(rows)}", flush=True)
    for r in rows:
        print(f"  Id={r['Id']} sid={r.get('source_id')} {(r.get('legal_name') or '')[:60]}", flush=True)
    if not rows:
        return

    companies = [
        CompanyInput(
            legal_name=(r.get("legal_name") or r.get("Title") or "").strip(),
            source_id=str(r.get("source_id") or ""),
            country="España",
        )
        for r in rows
    ]
    settings = settings_from_input(
        {
            "country_code": "es",
            "language_code": "es",
            "debug": False,
            "skip_if_good_website": False,
            "fallback_google_maps": True,
            "batch_size": 10,
            "max_harvest_candidates": 2,
            "max_website_probes": 2,
            "validate_websites": True,
        },
        env_token=os.getenv("APIFY_TOKEN"),
        env_harvest=os.getenv("HARVEST_API_KEY"),
        env_openai=os.getenv("OPENAI_API_KEY"),
    )

    dry = os.getenv("DRY_RUN", "0") == "1"
    async with Actor:
        results = await resolve_companies_batch(companies, settings)
        patches = [safe_patch_from_result(row, res) for row, res in zip(rows, results)]
        Path("/tmp/empty_batch_safe_patches.json").write_text(
            json.dumps(patches, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        filled = sum(1 for p in patches if p.get("website") or p.get("linkedin_url"))
        with_web = sum(1 for p in patches if p.get("website"))
        print(f"\nSafe outcomes: {filled}/{len(patches)} with LI/web, {with_web} with website", flush=True)
        for p in patches:
            print(
                f"  Id={p['Id']} [{p.get('match_status')}/{p.get('enrichment_status')}] "
                f"web={p.get('domain') or '-'} li={(p.get('linkedin_url') or '-')[-40:]} "
                f"| {(p.get('legal_name') or '')[:40]}",
                flush=True,
            )
        if dry:
            print("DRY_RUN=1 — not patching NocoDB", flush=True)
            return
        for p in patches:
            resp = requests.patch(f"{BASE}/api/v2/tables/{TABLE}/records", headers=HEADERS, json=p, timeout=60)
            if not resp.ok:
                print(f"PATCH fail Id={p['Id']}: {resp.status_code} {resp.text[:200]}", flush=True)
                resp.raise_for_status()
            print(f"PATCHED Id={p['Id']} web={p.get('website')} li={p.get('linkedin_url')}", flush=True)
        print("Done.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
