#!/usr/bin/env python3
"""Re-resolve empty (or pending) NocoDB org rows and PATCH only safe outcomes."""

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


def fetch_empty_batch(min_source_id: int = 46) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        r = requests.get(
            f"{BASE}/api/v2/tables/{TABLE}/records",
            headers={"xc-token": TOKEN},
            params={"limit": 100, "offset": offset},
            timeout=60,
        )
        r.raise_for_status()
        batch = r.json().get("list") or []
        if not batch:
            break
        rows.extend(batch)
        offset += len(batch)
        if len(batch) < 100:
            break
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
