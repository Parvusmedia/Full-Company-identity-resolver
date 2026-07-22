#!/usr/bin/env python3
"""Re-resolve one NocoDB org row by Id and optionally PATCH."""

from __future__ import annotations

import argparse
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


def fetch_row(row_id: int) -> dict:
    r = requests.get(
        f"{BASE}/api/v2/tables/{TABLE}/records",
        headers={"xc-token": TOKEN},
        params={"where": f"(Id,eq,{row_id})"},
        timeout=60,
    )
    r.raise_for_status()
    rows = r.json().get("list") or []
    if not rows:
        raise SystemExit(f"No row with Id={row_id}")
    return rows[0]


async def resolve_and_patch(row: dict, *, dry_run: bool, out_path: str) -> dict:
    company = CompanyInput(
        legal_name=(row.get("legal_name") or row.get("Title") or "").strip(),
        source_id=str(row.get("source_id") or ""),
        country="España",
    )
    settings = settings_from_input(
        {
            "country_code": "es",
            "language_code": "es",
            "debug": False,
            "skip_if_good_website": False,
            "fallback_google_maps": True,
            "batch_size": 1,
            "max_harvest_candidates": 2,
            "max_website_probes": 2,
            "validate_websites": True,
        },
        env_token=os.getenv("APIFY_TOKEN"),
        env_harvest=os.getenv("HARVEST_API_KEY"),
        env_openai=os.getenv("OPENAI_API_KEY"),
    )
    async with Actor:
        results = await resolve_companies_batch([company], settings)
        result = results[0]
        item = result.to_dataset_item(debug=False)
        patch = safe_patch_from_result(row, result)
        payload = {"item": item, "patch": patch}
        Path(out_path).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        if not dry_run:
            resp = requests.patch(
                f"{BASE}/api/v2/tables/{TABLE}/records",
                headers=HEADERS,
                json=patch,
                timeout=60,
            )
            if not resp.ok:
                raise RuntimeError(f"PATCH failed: {resp.status_code} {resp.text[:300]}")
        return patch


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("row_id", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out", default="/tmp/reenrich_single.json")
    args = parser.parse_args()

    row = fetch_row(args.row_id)
    patch = asyncio.run(resolve_and_patch(row, dry_run=args.dry_run, out_path=args.out))
    print(f"Wrote {args.out}", flush=True)
    print(json.dumps(patch, ensure_ascii=False, indent=2, default=str), flush=True)
    if args.dry_run:
        print("DRY_RUN — not patching NocoDB", flush=True)
    else:
        print(f"PATCHED Id={args.row_id}", flush=True)


if __name__ == "__main__":
    main()
