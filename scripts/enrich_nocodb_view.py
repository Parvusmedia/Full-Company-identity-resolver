"""Re-run NocoDB org view through the identity resolver.

Plan B tokens via scripts.load_n8n_vars. Never prints secret values.
Skips deferred source_id 2632. Maps are not used.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.load_n8n_vars import load_n8n_vars  # noqa: E402
from my_actor.models import CompanyInput  # noqa: E402
from my_actor.resolver import resolve_companies_batch, settings_from_input  # noqa: E402

DEFAULT_BASE = "https://mpa.parvusmedia.com"
DEFAULT_TABLE = "mewh1ynmcokfsfi"
DEFAULT_VIEW = "vw0q1gm39dsc3d9t"
SKIP_SOURCE_IDS = {"2632"}

DEST_ALIASES: dict[str, tuple[str, ...]] = {
    "id": ("Id", "id", "ID"),
    "source_id": ("source_id", "Source Id", "sourceId"),
    "legal_name": ("legal_name", "Legal name", "razon_social", "Razón social", "name", "Name"),
    "tax_id": ("tax_id", "Tax ID", "cif", "CIF", "nif", "NIF"),
    "city": ("city", "City", "ciudad", "Ciudad"),
    "province": ("province", "Province", "provincia", "Provincia"),
    "country": ("country", "Country", "pais", "País"),
    "commercial_name": ("commercial_name", "Commercial name", "nombre_comercial"),
    "linkedin_url": ("linkedin_url", "LinkedIn", "linkedin"),
    "website": ("website", "Website", "web"),
    "domain": ("domain", "Domain"),
    "match_status": ("match_status", "Match status"),
    "confidence": ("confidence", "Confidence"),
    "enrichment_status": ("enrichment_status", "Enrichment status"),
    "evidence_summary": ("evidence_summary", "Evidence summary"),
    "linkedin_id": ("linkedin_id", "LinkedIn Id"),
    "universal_name": ("universal_name", "universalName"),
    "industry": ("industry", "Industry"),
    "employee_count": ("employee_count", "Employee count"),
    "followers": ("followers", "Followers"),
    "relationship": ("relationship", "Relationship"),
}

WRITE_KEYS = (
    "commercial_name",
    "linkedin_url",
    "website",
    "domain",
    "match_status",
    "confidence",
    "enrichment_status",
    "evidence_summary",
    "linkedin_id",
    "universal_name",
    "industry",
    "employee_count",
    "followers",
    "relationship",
)


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pick(record: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in record and record[name] not in (None, ""):
            return record[name]
    return None


def field_map(sample: dict[str, Any]) -> dict[str, str]:
    """Map logical names to actual NocoDB column names present on a record."""
    keys = set(sample.keys())
    out: dict[str, str] = {}
    for logical, aliases in DEST_ALIASES.items():
        for alias in aliases:
            if alias in keys:
                out[logical] = alias
                break
    return out


def parse_company(record: dict[str, Any], fmap: dict[str, str]) -> CompanyInput | None:
    legal_key = fmap.get("legal_name")
    legal = record.get(legal_key) if legal_key else None
    if not legal:
        return None
    source = record.get(fmap["source_id"]) if "source_id" in fmap else None
    return CompanyInput(
        source_id=str(source) if source is not None else None,
        legal_name=str(legal),
        tax_id=str(record[fmap["tax_id"]]) if fmap.get("tax_id") and record.get(fmap["tax_id"]) else None,
        city=str(record[fmap["city"]]) if fmap.get("city") and record.get(fmap["city"]) else None,
        province=str(record[fmap["province"]]) if fmap.get("province") and record.get(fmap["province"]) else None,
        country=str(record[fmap["country"]]) if fmap.get("country") and record.get(fmap["country"]) else "España",
    )


class NocoClient:
    def __init__(self, base: str, token: str, table: str, view: str) -> None:
        self.base = base.rstrip("/")
        self.table = table
        self.view = view
        self._headers = {"xc-token": token, "Accept": "application/json", "Content-Type": "application/json"}

    def _url(self, path: str) -> str:
        return f"{self.base}{path}"

    async def list_records(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        offset = 0
        limit = 100
        while True:
            response = await client.get(
                self._url(f"/api/v2/tables/{self.table}/records"),
                headers=self._headers,
                params={"viewId": self.view, "offset": offset, "limit": limit},
                timeout=60.0,
            )
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("list") if isinstance(payload, dict) else payload
            if not isinstance(rows, list):
                raise RuntimeError("NocoDB list did not return records")
            out.extend(row for row in rows if isinstance(row, dict))
            page = payload.get("pageInfo") if isinstance(payload, dict) else None
            if isinstance(page, dict) and page.get("isLastPage"):
                break
            if len(rows) < limit:
                break
            offset += limit
        return out

    async def patch_records(self, client: httpx.AsyncClient, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        response = await client.patch(
            self._url(f"/api/v2/tables/{self.table}/records"),
            headers=self._headers,
            json=rows,
            timeout=60.0,
        )
        response.raise_for_status()


def snapshot_row(record: dict[str, Any], fmap: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for logical in ("id", "source_id", "legal_name", *WRITE_KEYS):
        key = fmap.get(logical)
        if key:
            out[logical] = record.get(key)
    return out


def result_patch(result: Any, record: dict[str, Any], fmap: dict[str, str]) -> dict[str, Any]:
    id_key = fmap.get("id")
    if not id_key:
        raise RuntimeError("NocoDB records have no Id column")
    patch: dict[str, Any] = {id_key: record[id_key]}
    mapping = {
        "commercial_name": result.commercial_name,
        "linkedin_url": result.linkedin_url,
        "website": result.website,
        "domain": result.domain,
        "match_status": result.match_status,
        "confidence": result.confidence,
        "enrichment_status": result.enrichment_status,
        "evidence_summary": result.evidence_summary,
        "linkedin_id": result.linkedin_id,
        "universal_name": result.universal_name,
        "industry": result.industry,
        "employee_count": result.employee_count,
        "followers": result.followers,
        "relationship": result.relationship,
    }
    for logical, value in mapping.items():
        col = fmap.get(logical)
        if not col:
            continue
        patch[col] = value
    return patch


def lift_bucket(conf: float | None) -> str:
    if conf is None:
        return "missing"
    if conf < 40:
        return "lt40"
    if conf < 50:
        return "40_49"
    if conf < 78:
        return "50_77"
    return "ge78"


async def main_async(args: argparse.Namespace) -> int:
    flags = load_n8n_vars()
    missing = [name for name, ok in flags.items() if not ok]
    if missing:
        print("Plan B incomplete. Missing: " + ", ".join(missing), file=sys.stderr)
        return 2

    noco_token = os.environ["NOCO_TOKEN"]
    base = (os.getenv("NOCO_BASE") or DEFAULT_BASE).rstrip("/")
    noco = NocoClient(base, noco_token, args.table, args.view)

    settings = settings_from_input(
        {
            "google_results_per_page": 10,
            "max_harvest_candidates": 2,
            "fallback_google_by_website": True,
            "fallback_harvest_search": not args.disable_discovery,
            "fallback_homepage_linkedin": not args.disable_discovery,
            "use_ai_for_ambiguous": False,
            "batch_size": args.chunk_size,
            "debug": False,
        },
        env_token=os.getenv("APIFY_TOKEN"),
        env_harvest=os.getenv("HARVEST_API_KEY"),
        env_openai=os.getenv("OPENAI_API_KEY"),
    )

    async with httpx.AsyncClient() as http:
        print(f"Fetching view {args.view} …")
        records = await noco.list_records(http)
        if not records:
            print("No records in view.")
            return 0
        fmap = field_map(records[0])
        print("Columns mapped: " + ", ".join(sorted(fmap)))

        conf_key = fmap.get("confidence")
        source_key = fmap.get("source_id")
        targets: list[dict[str, Any]] = []
        for row in records:
            source = str(row.get(source_key)) if source_key and row.get(source_key) is not None else ""
            if source in SKIP_SOURCE_IDS:
                continue
            conf = _as_float(row.get(conf_key)) if conf_key else None
            if conf is None or conf < args.confidence_lt:
                targets.append(row)

        print(f"View rows={len(records)} conf<{args.confidence_lt} (skip 2632)={len(targets)}")
        if args.limit and args.limit > 0:
            targets = targets[: args.limit]
            print(f"Limited to {len(targets)} rows")

        snapshot: list[dict[str, Any]] = []
        written = 0
        lifted = 0
        new_linkedin = 0
        discovery_hits = 0
        before_buckets: dict[str, int] = {}
        after_buckets: dict[str, int] = {}

        for i in range(0, len(targets), args.wave_size):
            wave = targets[i : i + args.wave_size]
            companies: list[CompanyInput] = []
            usable_rows: list[dict[str, Any]] = []
            for row in wave:
                company = parse_company(row, fmap)
                if not company:
                    continue
                companies.append(company)
                usable_rows.append(row)
            if not companies:
                continue
            print(f"Wave {i // args.wave_size + 1}: resolving {len(companies)} companies (chunk={args.chunk_size})")
            results = await resolve_companies_batch(companies, settings)
            patches: list[dict[str, Any]] = []
            for row, result in zip(usable_rows, results, strict=True):
                before = snapshot_row(row, fmap)
                before_conf = _as_float(before.get("confidence"))
                after_conf = float(result.confidence or 0)
                before_li = before.get("linkedin_url")
                snap = {
                    "before": before,
                    "after": {
                        "legal_name": result.legal_name,
                        "source_id": result.source_id,
                        "linkedin_url": result.linkedin_url,
                        "website": result.website,
                        "match_status": result.match_status,
                        "confidence": result.confidence,
                        "enrichment_status": result.enrichment_status,
                        "discovery_sources_used": result.discovery_sources_used,
                        "evidence_summary": result.evidence_summary,
                    },
                }
                snapshot.append(snap)
                before_buckets[lift_bucket(before_conf)] = before_buckets.get(lift_bucket(before_conf), 0) + 1
                after_buckets[lift_bucket(after_conf)] = after_buckets.get(lift_bucket(after_conf), 0) + 1
                if result.discovery_sources_used:
                    discovery_hits += 1
                if result.linkedin_url and not before_li:
                    new_linkedin += 1
                if (before_conf is None or after_conf > before_conf + 1) and after_conf >= 50:
                    lifted += 1
                patches.append(result_patch(result, row, fmap))

            if not args.dry_run and patches:
                await noco.patch_records(http, patches)
                written += len(patches)
            elif args.dry_run:
                print(f"Dry-run: would patch {len(patches)} rows")

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        snap_path = Path(f"/tmp/discovery-rerun-{stamp}.json")
        snap_path.write_text(
            json.dumps(
                {
                    "view": args.view,
                    "confidence_lt": args.confidence_lt,
                    "dry_run": args.dry_run,
                    "disable_discovery": args.disable_discovery,
                    "before_buckets": before_buckets,
                    "after_buckets": after_buckets,
                    "lifted_to_50plus": lifted,
                    "new_linkedin": new_linkedin,
                    "discovery_hits": discovery_hits,
                    "written": written,
                    "rows": snapshot,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Snapshot: {snap_path}")
        print(f"before buckets: {before_buckets}")
        print(f"after buckets:  {after_buckets}")
        print(
            f"lifted_to_50plus={lifted} new_linkedin={new_linkedin} "
            f"discovery_hits={discovery_hits} written={written}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Re-run NocoDB view through identity resolver")
    parser.add_argument("--table", default=DEFAULT_TABLE)
    parser.add_argument("--view", default=DEFAULT_VIEW)
    parser.add_argument("--confidence-lt", type=float, default=50.0)
    parser.add_argument("--chunk-size", type=int, default=10)
    parser.add_argument("--wave-size", type=int, default=50)
    parser.add_argument("--limit", type=int, default=0, help="Max rows to process (0=all)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--disable-discovery",
        action="store_true",
        help="Rollback flags: no Harvest search / homepage scrape",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
