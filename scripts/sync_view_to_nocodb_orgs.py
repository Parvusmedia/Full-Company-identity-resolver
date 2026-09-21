"""Copy company rows from a NocoDB view into telefonica orgs table (no duplicates).

Reads suppression_entities view vwytap93l3m4ve85 by default, filters entity_type=company_name,
drops persons/autónomos, skips rows already present in mewh1ynmcokfsfi (normalized Title/core).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from my_actor.normalization import core_name, normalize_text, remove_legal_forms  # noqa: E402
from scripts.load_n8n_vars import load_n8n_vars  # noqa: E402

DEFAULT_BASE = "https://mpa.parvusmedia.com"
READ_TABLE = "m29pd9rqgfm3agu"
READ_VIEW = "vwytap93l3m4ve85"
WRITE_TABLE = "mewh1ynmcokfsfi"

AUTONOMO = re.compile(r"aut[oó]nomo", re.IGNORECASE)
ORG_KW = re.compile(
    r"seguros|insurance|broker|corredor|group|grupo|holding|bank|banca|mutua|cooperativa|"
    r"empresa|gmbh|ltd|llc|underwriting|reaseguros",
    re.IGNORECASE,
)
TITLE_WORD = re.compile(
    r"^[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]+(?:[-'][A-ZÁÉÍÓÚÑa-záéíóúñü]+)?$",
)


def has_legal_form(name: str) -> bool:
    return normalize_text(remove_legal_forms(name)) != normalize_text(name)


def looks_like_person(name: str) -> bool:
    if has_legal_form(name) or ORG_KW.search(name):
        return False
    if AUTONOMO.search(name):
        return True
    parts = [p for p in re.split(r"\s+", name.strip()) if p]
    if len(parts) == 2 and all(TITLE_WORD.match(p) for p in parts):
        return True
    if 3 <= len(parts) <= 6:
        sig = [p for p in parts if p.lower() not in {"de", "del", "la", "los", "las", "y", "i"}]
        if len(sig) >= 3 and all(TITLE_WORD.match(p) for p in sig):
            return True
    return False


def is_company_entity(name: str) -> bool:
    if not name or len(name.strip()) < 2:
        return False
    if AUTONOMO.search(name):
        return False
    if looks_like_person(name):
        return False
    if has_legal_form(name):
        return True
    if ORG_KW.search(name):
        return True
    parts = name.split()
    # Single-token brands only when clearly not a personal first name (short token).
    if len(parts) == 1 and len(parts[0]) >= 8:
        return True
    return False


def dedupe_keys(name: str) -> set[str]:
    keys: set[str] = set()
    n = normalize_text(name)
    c = normalize_text(core_name(name))
    if n:
        keys.add(n)
    if c:
        keys.add(c)
    return keys


async def list_all_records(
    client: httpx.AsyncClient,
    base: str,
    token: str,
    table: str,
    *,
    view_id: str | None = None,
    fields: str | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    offset = 0
    params: dict[str, Any] = {"limit": 100, "offset": offset}
    if view_id:
        params["viewId"] = view_id
    if fields:
        params["fields"] = fields
    headers = {"xc-token": token, "Accept": "application/json"}
    while True:
        params["offset"] = offset
        response = await client.get(
            f"{base.rstrip('/')}/api/v2/tables/{table}/records",
            headers=headers,
            params=params,
            timeout=120.0,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("list") if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            raise RuntimeError("unexpected list payload")
        out.extend(row for row in rows if isinstance(row, dict))
        page = payload.get("pageInfo") if isinstance(payload, dict) else None
        if isinstance(page, dict) and page.get("isLastPage"):
            break
        if len(rows) < 100:
            break
        offset += 100
    return out


async def post_records(
    client: httpx.AsyncClient,
    base: str,
    token: str,
    table: str,
    rows: list[dict[str, Any]],
) -> None:
    headers = {
        "xc-token": token,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    response = await client.post(
        f"{base.rstrip('/')}/api/v2/tables/{table}/records",
        headers=headers,
        json=rows,
        timeout=120.0,
    )
    response.raise_for_status()


async def main_async(args: argparse.Namespace) -> int:
    flags = load_n8n_vars()
    if not all(flags.values()):
        print("Missing tokens (Plan B): " + ", ".join(k for k, v in flags.items() if not v), file=sys.stderr)
        return 2

    token = os.environ["NOCO_TOKEN"]
    base = (os.getenv("NOCO_BASE") or DEFAULT_BASE).rstrip("/")

    async with httpx.AsyncClient() as client:
        print("Loading existing write table keys …", flush=True)
        existing_rows = await list_all_records(
            client, base, token, args.write_table, fields="Title,source_id,pipedrive_org_id"
        )
        seen: set[str] = set()
        for row in existing_rows:
            title = row.get("Title")
            if title:
                seen |= dedupe_keys(str(title))

        print(f"Existing rows={len(existing_rows)} dedupe_keys={len(seen)}", flush=True)

        print(f"Reading view {args.read_view} …", flush=True)
        source_rows = await list_all_records(
            client, base, token, args.read_table, view_id=args.read_view
        )
        print(f"Source view rows={len(source_rows)}", flush=True)

        to_insert: list[dict[str, Any]] = []
        stats = {
            "skipped_type": 0,
            "skipped_person": 0,
            "skipped_autonomo": 0,
            "skipped_dupe": 0,
            "accepted": 0,
        }

        for row in source_rows:
            if row.get("entity_type") != "company_name":
                stats["skipped_type"] += 1
                continue
            name = (row.get("entity_value") or "").strip()
            if not name:
                stats["skipped_type"] += 1
                continue
            if AUTONOMO.search(name):
                stats["skipped_autonomo"] += 1
                continue
            if not is_company_entity(name):
                stats["skipped_person"] += 1
                continue
            keys = dedupe_keys(name)
            if keys & seen:
                stats["skipped_dupe"] += 1
                continue
            seen |= keys
            stats["accepted"] += 1
            payload: dict[str, Any] = {
                "Title": name,
                "enrichment_status": "pending",
            }
            reason = row.get("reason")
            if reason:
                payload["evidence_summary"] = f"imported_from_suppression_view reason={reason}"
            to_insert.append(payload)
            if args.limit and stats["accepted"] >= args.limit:
                break

        print(
            f"accepted={stats['accepted']} dupe={stats['skipped_dupe']} "
            f"person={stats['skipped_person']} autonomo={stats['skipped_autonomo']} "
            f"other_type={stats['skipped_type']}",
            flush=True,
        )

        if args.dry_run:
            print(f"Dry-run: would POST {len(to_insert)} rows", flush=True)
            for row in to_insert[:10]:
                print(" ", row["Title"][:70], flush=True)
            return 0

        batch = max(1, args.batch_size)
        written = 0
        for i in range(0, len(to_insert), batch):
            chunk = to_insert[i : i + batch]
            await post_records(client, base, token, args.write_table, chunk)
            written += len(chunk)
            print(f"POST {written}/{len(to_insert)}", flush=True)

        print(f"Done. inserted={written}", flush=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Copy companies from Noco view to org table")
    p.add_argument("--read-table", default=READ_TABLE)
    p.add_argument("--read-view", default=READ_VIEW)
    p.add_argument("--write-table", default=WRITE_TABLE)
    p.add_argument("--batch-size", type=int, default=25)
    p.add_argument("--limit", type=int, default=0, help="Max inserts (0=all)")
    p.add_argument("--dry-run", action="store_true")
    return p


def main() -> int:
    return asyncio.run(main_async(build_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
