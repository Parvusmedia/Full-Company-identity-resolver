"""Reconcile Pipedrive org CSV against NocoDB telefonica orgs table.

1. Filter CSV rows to companies (not persons / autónomos).
2. Match existing rows in mewh1ynmcokfsfi by normalized name.
3. Optionally PATCH pipedrive_org_id (Noco column id c5r8ztchlylpg2l).
4. Report net-new companies not in Noco for human review.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from my_actor.normalization import core_name, normalize_text  # noqa: E402
from scripts.load_n8n_vars import load_n8n_vars  # noqa: E402
from scripts.sync_view_to_nocodb_orgs import dedupe_keys, is_company_entity  # noqa: E402

DEFAULT_BASE = "https://mpa.parvusmedia.com"
WRITE_TABLE = "mewh1ynmcokfsfi"
PD_COLUMN = "pipedrive_org_id"

NAME_HEADERS = (
    "name",
    "organization",
    "org name",
    "organization name",
    "company",
    "company name",
    "nombre",
    "razon social",
    "razón social",
    "title",
    "empresa",
)
ID_HEADERS = (
    "id",
    "org id",
    "organization id",
    "pipedrive id",
    "pipedrive_org_id",
    "deal org id",
)


def _norm_header(h: str) -> str:
    return re.sub(r"\s+", " ", (h or "").strip().lower())


def detect_columns(fieldnames: list[str] | None) -> tuple[str, str]:
    if not fieldnames:
        raise ValueError("CSV has no header row")
    mapping = {_norm_header(f): f for f in fieldnames}
    name_col = None
    id_col = None
    for key, original in mapping.items():
        if key in NAME_HEADERS:
            name_col = original
        if key in ID_HEADERS:
            id_col = original
    # Pipedrive export often: "Name" + "ID" on Organizations
    if not name_col:
        for pref in ("Name", "name", "Organization", "Title"):
            if pref in fieldnames:
                name_col = pref
                break
    if not id_col:
        for pref in ("ID", "Id", "id", "Organization ID"):
            if pref in fieldnames:
                id_col = pref
                break
    if not name_col or not id_col:
        raise ValueError(
            f"Could not detect name/id columns. Headers: {fieldnames}. "
            f"Use --name-column and --id-column."
        )
    return name_col, id_col


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        reader = csv.DictReader(fh, dialect=dialect)
        fields = list(reader.fieldnames or [])
        rows = [{k: (v or "").strip() for k, v in row.items()} for row in reader]
    return fields, rows


async def load_noco_index(
    client: httpx.AsyncClient, base: str, token: str, table: str
) -> dict[str, list[dict[str, Any]]]:
    """Map normalized name key -> list of Noco rows (handles rare collisions)."""
    index: dict[str, list[dict[str, Any]]] = {}
    offset = 0
    headers = {"xc-token": token, "Accept": "application/json"}
    while True:
        response = await client.get(
            f"{base.rstrip('/')}/api/v2/tables/{table}/records",
            headers=headers,
            params={"limit": 100, "offset": offset, "fields": "Id,Title,pipedrive_org_id,source_id"},
            timeout=120.0,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("list") or []
        for row in rows:
            title = row.get("Title")
            if not title:
                continue
            record = {
                "Id": row.get("Id"),
                "Title": title,
                "pipedrive_org_id": row.get("pipedrive_org_id"),
                "source_id": row.get("source_id"),
            }
            for key in dedupe_keys(str(title)):
                index.setdefault(key, []).append(record)
        page = payload.get("pageInfo") or {}
        if page.get("isLastPage") or len(rows) < 100:
            break
        offset += 100
    return index


def find_matches(name: str, index: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    seen_ids: set[Any] = set()
    for key in dedupe_keys(name):
        for rec in index.get(key, []):
            rid = rec.get("Id")
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            hits.append(rec)
    return hits


async def patch_records(
    client: httpx.AsyncClient, base: str, token: str, table: str, patches: list[dict[str, Any]]
) -> None:
    headers = {"xc-token": token, "Accept": "application/json", "Content-Type": "application/json"}
    response = await client.patch(
        f"{base.rstrip('/')}/api/v2/tables/{table}/records",
        headers=headers,
        json=patches,
        timeout=120.0,
    )
    response.raise_for_status()


async def main_async(args: argparse.Namespace) -> int:
    flags = load_n8n_vars()
    if not all(flags.values()):
        print("Missing tokens", file=sys.stderr)
        return 2

    path = Path(args.csv)
    if not path.is_file():
        print(f"CSV not found: {path}", file=sys.stderr)
        return 1

    fields, rows = read_csv_rows(path)
    if args.name_column and args.id_column:
        name_col, id_col = args.name_column, args.id_column
    else:
        name_col, id_col = detect_columns(fields)

    token = os.environ["NOCO_TOKEN"]
    base = (os.getenv("NOCO_BASE") or DEFAULT_BASE).rstrip("/")

    stats = {
        "csv_rows": len(rows),
        "skipped_person": 0,
        "skipped_empty": 0,
        "matched": 0,
        "updated_pd": 0,
        "already_pd": 0,
        "ambiguous_match": 0,
        "new_companies": 0,
    }
    updates: list[dict[str, Any]] = []
    new_orgs: list[dict[str, str]] = []
    ambiguous: list[dict[str, Any]] = []

    async with httpx.AsyncClient() as client:
        index = await load_noco_index(client, base, token, args.table)
        print(f"Noco index keys={len(index)}", flush=True)
        print(f"CSV columns: name={name_col!r} id={id_col!r}", flush=True)

        for row in rows:
            name = (row.get(name_col) or "").strip()
            pd_id = (row.get(id_col) or "").strip()
            if not name or not pd_id:
                stats["skipped_empty"] += 1
                continue
            if not is_company_entity(name):
                stats["skipped_person"] += 1
                continue
            matches = find_matches(name, index)
            if not matches:
                stats["new_companies"] += 1
                new_orgs.append({"name": name, "pipedrive_org_id": pd_id})
                continue
            if len(matches) > 1:
                stats["ambiguous_match"] += 1
                ambiguous.append(
                    {"csv_name": name, "pipedrive_org_id": pd_id, "noco_ids": [m["Id"] for m in matches]}
                )
                continue
            stats["matched"] += 1
            rec = matches[0]
            current = str(rec.get("pipedrive_org_id") or "").strip()
            if current == pd_id:
                stats["already_pd"] += 1
                continue
            updates.append({"Id": rec["Id"], PD_COLUMN: pd_id})
            stats["updated_pd"] += 1

        report = {
            "csv": str(path),
            "name_column": name_col,
            "id_column": id_col,
            "stats": stats,
            "new_companies": new_orgs,
            "ambiguous_matches": ambiguous,
            "updates_preview": updates[:20],
        }
        out = Path(args.report_file)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(stats, indent=2), flush=True)
        print(f"Report: {out}", flush=True)
        print(f"New companies (for review): {stats['new_companies']}", flush=True)

        if args.apply and updates:
            batch = max(1, args.batch_size)
            for i in range(0, len(updates), batch):
                chunk = updates[i : i + batch]
                await patch_records(client, base, token, args.table, chunk)
                print(f"Patched {min(i + batch, len(updates))}/{len(updates)}", flush=True)
        elif updates and not args.apply:
            print(f"Dry-run: would PATCH pipedrive_org_id on {len(updates)} rows (use --apply)", flush=True)

    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Reconcile Pipedrive CSV with Noco org table")
    p.add_argument("csv", help="Path to Pipedrive organizations CSV export")
    p.add_argument("--table", default=WRITE_TABLE)
    p.add_argument("--name-column", default="")
    p.add_argument("--id-column", default="")
    p.add_argument("--report-file", default="/tmp/pipedrive-reconcile-report.json")
    p.add_argument("--apply", action="store_true", help="PATCH pipedrive_org_id for matches")
    p.add_argument("--batch-size", type=int, default=50)
    return p


def main() -> int:
    return asyncio.run(main_async(build_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
