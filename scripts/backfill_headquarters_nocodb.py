#!/usr/bin/env python3
"""Backfill NocoDB headquarters_text from Harvest locations via LinkedIn URL."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from my_actor.harvest import HarvestClient, harvest_headquarters_fields
from my_actor.output_normalize import normalize_noco_patch

load_dotenv()

BASE = os.environ["NOCO_BASE"].rstrip("/")
TOKEN = os.environ["NOCO_TOKEN"]
TABLE = "mewh1ynmcokfsfi"
HEADERS = {"xc-token": TOKEN, "Content-Type": "application/json"}


def fetch_rows() -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        resp = requests.get(
            f"{BASE}/api/v2/tables/{TABLE}/records",
            headers={"xc-token": TOKEN},
            params={"limit": 100, "offset": offset},
            timeout=60,
        )
        resp.raise_for_status()
        batch = resp.json().get("list", [])
        if not batch:
            break
        rows.extend(batch)
        offset += len(batch)
        if len(batch) < 100:
            break
    return rows


async def harvest_hq(linkedin_url: str, client: HarvestClient) -> str | None:
    element = await client.get_company_element(url=linkedin_url)
    if not element:
        return None
    return harvest_headquarters_fields(element).get("headquarters_text")


async def main() -> None:
    api_key = os.environ.get("HARVEST_API_KEY")
    if not api_key:
        raise SystemExit("HARVEST_API_KEY required")

    rows = fetch_rows()
    targets = [
        r
        for r in rows
        if (r.get("linkedin_url") or "").strip() and not (r.get("headquarters_text") or "").strip()
    ]
    print(f"Rows: {len(rows)} | backfill targets: {len(targets)}", flush=True)
    if not targets:
        return

    client = HarvestClient(api_key, concurrency=4)
    patched = 0
    for row in targets:
        li = str(row["linkedin_url"]).strip()
        hq_text = await harvest_hq(li, client)
        if not hq_text:
            print(f"SKIP Id={row['Id']} no HQ | {li}", flush=True)
            continue
        patch = normalize_noco_patch({"Id": row["Id"], "headquarters_text": hq_text})
        resp = requests.patch(
            f"{BASE}/api/v2/tables/{TABLE}/records",
            headers=HEADERS,
            json=patch,
            timeout=60,
        )
        if not resp.ok:
            print(f"FAIL Id={row['Id']}: {resp.status_code} {resp.text[:200]}", flush=True)
            resp.raise_for_status()
        patched += 1
        print(f"OK Id={row['Id']} | {(row.get('legal_name') or '')[:40]:40} | {hq_text}", flush=True)

    print(f"\nPatched headquarters_text on {patched}/{len(targets)} rows.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
