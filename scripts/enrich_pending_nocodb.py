#!/usr/bin/env python3
"""Resolve pending NocoDB org rows locally and PATCH results back."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import requests
from apify import Actor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from my_actor.models import CompanyInput
from my_actor.noco_patch import safe_patch_from_result
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
            timeout=60,
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


async def enrich_chunk(rows: list[dict]) -> list[dict]:
    companies = [
        CompanyInput(
            legal_name=(r.get("legal_name") or r.get("Title") or "").strip(),
            source_id=str(r.get("source_id") or ""),
        )
        for r in rows
    ]
    settings = settings_from_input(
        {
            "country_code": "es",
            "language_code": "es",
            "debug": False,
            "skip_if_good_website": False,
            "fallback_google_maps": False,
            "batch_size": 15,
            "max_harvest_candidates": 2,
        },
        env_token=os.getenv("APIFY_TOKEN"),
        env_harvest=os.getenv("HARVEST_API_KEY"),
        env_openai=os.getenv("OPENAI_API_KEY"),
    )
    results = await resolve_companies_batch(companies, settings)
    return [safe_patch_from_result(row, result) for row, result in zip(rows, results)]


def patch_rows(patches: list[dict]) -> None:
    for p in patches:
        resp = requests.patch(
            f"{BASE}/api/v2/tables/{TABLE}/records",
            headers=HEADERS,
            json=p,
            timeout=60,
        )
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
