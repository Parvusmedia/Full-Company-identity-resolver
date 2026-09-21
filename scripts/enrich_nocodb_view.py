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
    "legal_name": ("legal_name", "Legal name", "razon_social", "Razón social", "Title", "name", "Name"),
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


def _row_id(record: dict[str, Any], fmap: dict[str, str]) -> Any:
    id_key = fmap.get("id")
    return record.get(id_key) if id_key else None


def load_run_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_run_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def checkpoint_payload(args: argparse.Namespace, meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "view": args.view,
        "table": args.table,
        "confidence_lt": args.confidence_lt,
        "dry_run": args.dry_run,
        "disable_discovery": args.disable_discovery,
        "chunk_size": args.chunk_size,
        "wave_size": args.wave_size,
        **meta,
    }


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

        state_path = Path(args.state_file)
        prior = load_run_state(state_path) if args.resume else {}
        processed_ids: set[Any] = set()
        if args.resume and prior.get("view") == args.view and prior.get("table") == args.table:
            for pid in prior.get("processed_ids") or []:
                processed_ids.add(pid)
            print(
                f"Resume: skipping {len(processed_ids)} already-processed rows from {state_path}",
                flush=True,
            )
        elif prior and args.resume:
            print(
                f"Resume state ignored (view/table mismatch): {state_path}",
                flush=True,
            )

        if processed_ids:
            targets = [row for row in targets if _row_id(row, fmap) not in processed_ids]

        print(
            f"View rows={len(records)} conf<{args.confidence_lt} (skip 2632) "
            f"pending={len(targets)}",
            flush=True,
        )
        if args.limit and args.limit > 0:
            targets = targets[: args.limit]
            print(f"Limited to {len(targets)} rows", flush=True)

        snapshot: list[dict[str, Any]] = list(prior.get("rows") or []) if args.resume else []
        written = int(prior.get("written") or 0) if args.resume else 0
        lifted = int(prior.get("lifted_to_50plus") or 0) if args.resume else 0
        new_linkedin = int(prior.get("new_linkedin") or 0) if args.resume else 0
        discovery_hits = int(prior.get("discovery_hits") or 0) if args.resume else 0
        before_buckets: dict[str, int] = dict(prior.get("before_buckets") or {}) if args.resume else {}
        after_buckets: dict[str, int] = dict(prior.get("after_buckets") or {}) if args.resume else {}
        homepage_hits = int(prior.get("homepage_hits") or 0) if args.resume else 0
        harvest_search_hits = int(prior.get("harvest_search_hits") or 0) if args.resume else 0

        checkpoint_path = Path(args.checkpoint_file)
        total_waves = max(1, (len(targets) + args.wave_size - 1) // args.wave_size) if targets else 0

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
            wave_no = i // args.wave_size + 1
            print(
                f"Wave {wave_no}/{total_waves}: resolving {len(companies)} companies "
                f"(chunk={args.chunk_size})",
                flush=True,
            )
            results = await resolve_companies_batch(companies, settings)
            patches: list[dict[str, Any]] = []
            wave_ids: list[Any] = []
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
                for src in result.discovery_sources_used:
                    if src.startswith("homepage:"):
                        homepage_hits += 1
                    elif src.startswith("harvest_search:"):
                        harvest_search_hits += 1
                if result.linkedin_url and not before_li:
                    new_linkedin += 1
                if (before_conf is None or after_conf > before_conf + 1) and after_conf >= 50:
                    lifted += 1
                patches.append(result_patch(result, row, fmap))
                rid = _row_id(row, fmap)
                if rid is not None:
                    wave_ids.append(rid)

            if not args.dry_run and patches:
                await noco.patch_records(http, patches)
                written += len(patches)
            elif args.dry_run:
                print(f"Dry-run: would patch {len(patches)} rows", flush=True)

            processed_ids.update(wave_ids)
            meta = {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "processed_ids": sorted(processed_ids, key=lambda x: (isinstance(x, str), x)),
                "before_buckets": before_buckets,
                "after_buckets": after_buckets,
                "lifted_to_50plus": lifted,
                "new_linkedin": new_linkedin,
                "discovery_hits": discovery_hits,
                "homepage_hits": homepage_hits,
                "harvest_search_hits": harvest_search_hits,
                "written": written,
                "rows": snapshot,
            }
            save_run_state(
                state_path,
                checkpoint_payload(args, meta),
            )
            checkpoint_path.write_text(
                json.dumps(checkpoint_payload(args, meta), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(
                f"Checkpoint wave {wave_no}/{total_waves}: written={written} "
                f"lifted={lifted} new_li={new_linkedin} discovery={discovery_hits} "
                f"(homepage={homepage_hits} harvest_search={harvest_search_hits})",
                flush=True,
            )

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        snap_path = Path(f"/tmp/discovery-rerun-{stamp}.json")
        final = checkpoint_payload(
            args,
            {
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "before_buckets": before_buckets,
                "after_buckets": after_buckets,
                "lifted_to_50plus": lifted,
                "new_linkedin": new_linkedin,
                "discovery_hits": discovery_hits,
                "homepage_hits": homepage_hits,
                "harvest_search_hits": harvest_search_hits,
                "written": written,
                "processed_count": len(processed_ids),
                "rows": snapshot,
            },
        )
        snap_path.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
        checkpoint_path.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Snapshot: {snap_path}", flush=True)
        print(f"Checkpoint: {checkpoint_path}", flush=True)
        print(f"before buckets: {before_buckets}", flush=True)
        print(f"after buckets:  {after_buckets}", flush=True)
        print(
            f"lifted_to_50plus={lifted} new_linkedin={new_linkedin} "
            f"discovery_hits={discovery_hits} homepage_hits={homepage_hits} "
            f"harvest_search_hits={harvest_search_hits} written={written}",
            flush=True,
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Re-run NocoDB view through identity resolver")
    parser.add_argument("--table", default=DEFAULT_TABLE)
    parser.add_argument("--view", default=DEFAULT_VIEW)
    parser.add_argument("--confidence-lt", type=float, default=50.0)
    parser.add_argument("--chunk-size", type=int, default=int(os.getenv("CHUNK_SIZE", "10")))
    parser.add_argument(
        "--wave-size",
        type=int,
        default=int(os.getenv("WAVE_SIZE", "10")),
        help="NocoDB patch + checkpoint every N rows (default 10; smaller = safer on timeouts)",
    )
    parser.add_argument("--limit", type=int, default=0, help="Max rows to process (0=all)")
    parser.add_argument(
        "--state-file",
        default=os.getenv(
            "ENRICH_STATE_FILE",
            "/tmp/enrich-nocodb-vw0q1gm39dsc3d9t.state.json",
        ),
        help="Resume state (processed row ids + rolling lift stats)",
    )
    parser.add_argument(
        "--checkpoint-file",
        default=os.getenv(
            "ENRICH_CHECKPOINT_FILE",
            "/tmp/discovery-rerun-latest.json",
        ),
    )
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip row ids listed in --state-file for this view/table",
    )
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
