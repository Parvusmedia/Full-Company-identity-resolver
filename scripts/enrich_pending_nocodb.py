#!/usr/bin/env python3
"""Resolve pending NocoDB org rows locally and PATCH results back."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from apify import Actor

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from my_actor.models import CompanyInput
from my_actor.resolver import resolve_companies_batch, settings_from_input

BASE = os.environ["NOCO_BASE"].rstrip("/")
TOKEN = os.environ["NOCO_TOKEN"]
TABLE = "mewh1ynmcokfsfi"
HEADERS = {"xc-token": TOKEN, "Content-Type": "application/json"}


def fetch_pending(limit: int = 50) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while len(rows) < limit:
        r = requests.get(
            f"{BASE}/api/v2/tables/{TABLE}/records",
            headers={"xc-token": TOKEN},
            params={
                "limit": min(100, limit - len(rows)),
                "offset": offset,
                "where": "(enrichment_status,eq,pending)",
            },
        )
        r.raise_for_status()
        data = r.json()
        batch = data.get("list") or []
        if not batch:
            break
        rows.extend(batch)
        if (data.get("pageInfo") or {}).get("isLastPage", True):
            break
        offset += len(batch)
    return rows[:limit]


def result_to_patch(noco_id: int, source_id: str | None, result) -> dict:
    item = result.to_dataset_item(debug=False)
    now = datetime.now(timezone.utc).isoformat()
    queries = item.get("google_queries_used") or []
    if isinstance(queries, list):
        queries_str = " | ".join(str(q) for q in queries)
    else:
        queries_str = str(queries)
    status = item.get("match_status") or "not_found"
    enrichment = "enriched" if status in {"confirmed", "high_confidence", "probable"} else (
        "partial" if status == "partial" else ("not_found" if status == "not_found" else status)
    )
    return {
        "Id": noco_id,
        "source_id": source_id,
        "legal_name": item.get("legal_name"),
        "Title": item.get("legal_name"),
        "commercial_name": item.get("commercial_name"),
        "linkedin_url": item.get("linkedin_url"),
        "website": item.get("website"),
        "domain": item.get("domain"),
        "industry": item.get("industry"),
        "employee_count": item.get("employee_count"),
        "followers": item.get("followers"),
        "phone": item.get("phone"),
        "headquarters_text": item.get("headquarters_text") or item.get("headquarters"),
        "relationship": item.get("relationship"),
        "match_status": status,
        "confidence": item.get("confidence"),
        "evidence_summary": item.get("evidence_summary"),
        "candidates_found": item.get("candidates_found"),
        "candidates_enriched": item.get("candidates_enriched"),
        "google_queries_used": queries_str,
        "enrichment_status": enrichment,
        "enriched_at": now,
        "error": item.get("error"),
    }


async def enrich_chunk(rows: list[dict]) -> list[dict]:
    companies = [
        CompanyInput(legal_name=(r.get("legal_name") or r.get("Title") or "").strip(), source_id=str(r.get("source_id") or ""))
        for r in rows
    ]
    settings = settings_from_input(
        {
            "country_code": "es",
            "language_code": "es",
            "debug": False,
            "skip_if_good_website": False,
            "enable_maps_fallback": False,
            "batch_size": 15,
            "max_harvest_candidates": 2,
        },
        env_token=os.getenv("APIFY_TOKEN"),
        env_harvest=os.getenv("HARVEST_API_KEY"),
        env_openai=os.getenv("OPENAI_API_KEY"),
    )
    results = await resolve_companies_batch(companies, settings)
    patches = []
    for row, result in zip(rows, results):
        patches.append(result_to_patch(row["Id"], str(row.get("source_id") or ""), result))
    return patches


def patch_rows(patches: list[dict]) -> None:
    for p in patches:
        resp = requests.patch(f"{BASE}/api/v2/tables/{TABLE}/records", headers=HEADERS, json=p)
        if not resp.ok:
            print(f"PATCH fail Id={p['Id']}: {resp.status_code} {resp.text[:200]}", flush=True)
            resp.raise_for_status()
        print(
            f"OK Id={p['Id']} | {p.get('legal_name','')[:40]:40} | "
            f"{p.get('match_status')} | web={p.get('website')} | li={p.get('linkedin_url')}",
            flush=True,
        )


async def main() -> None:
    chunk_size = int(os.getenv("CHUNK_SIZE", "10"))
    pending = fetch_pending(50)
    print(f"Pending rows to enrich: {len(pending)}", flush=True)
    if not pending:
        return
    async with Actor:
        for i in range(0, len(pending), chunk_size):
            chunk = pending[i : i + chunk_size]
            print(f"\n=== Chunk {i // chunk_size + 1}: {len(chunk)} companies ===", flush=True)
            patches = await enrich_chunk(chunk)
            patch_rows(patches)
            Path("/tmp/batch50_progress.json").write_text(
                json.dumps({"done_through": i + len(chunk), "last_chunk": patches}, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
    print("\nAll chunks done.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
