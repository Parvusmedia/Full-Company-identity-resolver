"""Compare sequential vs parallel resolve on the same NocoDB sample (no PATCH).

Measures wall time and checks that key output fields match between modes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from my_actor.models import CompanyInput, ResolutionResult  # noqa: E402
from my_actor.google_search import build_initial_queries, run_google_searches  # noqa: E402
from my_actor.resolver import resolve_companies_batch, resolve_company, settings_from_input  # noqa: E402
from scripts.enrich_nocodb_view import (  # noqa: E402
    DEFAULT_BASE,
    DEFAULT_TABLE,
    DEFAULT_VIEW,
    NocoClient,
    SKIP_SOURCE_IDS,
    field_map,
    parse_company,
)
from scripts.load_n8n_vars import load_n8n_vars  # noqa: E402


def _fingerprint(result: ResolutionResult) -> dict[str, Any]:
    return {
        "legal_name": result.legal_name,
        "linkedin_url": result.linkedin_url,
        "website": result.website,
        "match_status": result.match_status,
        "confidence": round(float(result.confidence or 0), 2),
        "enrichment_status": result.enrichment_status,
        "discovery_sources_used": sorted(result.discovery_sources_used or []),
    }


def _compare(
    baseline: list[ResolutionResult],
    candidate: list[ResolutionResult],
) -> list[dict[str, Any]]:
    diffs: list[dict[str, Any]] = []
    for a, b in zip(baseline, candidate, strict=True):
        fa, fb = _fingerprint(a), _fingerprint(b)
        if fa != fb:
            diffs.append({"legal_name": a.legal_name, "baseline": fa, "candidate": fb})
    return diffs


async def _fetch_sample(
    *,
    table: str,
    view: str,
    only_pending: bool,
    limit: int,
) -> tuple[list[CompanyInput], list[dict[str, Any]]]:
    token = os.environ["NOCO_TOKEN"]
    base = (os.getenv("NOCO_BASE") or DEFAULT_BASE).rstrip("/")
    noco = NocoClient(base, token, table, view)
    async with httpx.AsyncClient() as http:
        records = await noco.list_records(http)
    fmap = field_map(records[0])
    enrich_key = fmap.get("enrichment_status")
    conf_key = fmap.get("confidence")
    source_key = fmap.get("source_id")
    companies: list[CompanyInput] = []
    rows: list[dict[str, Any]] = []
    for row in records:
        if limit and len(companies) >= limit:
            break
        source = str(row.get(source_key)) if source_key and row.get(source_key) is not None else ""
        if source in SKIP_SOURCE_IDS:
            continue
        if only_pending:
            status = row.get(enrich_key) if enrich_key else row.get("enrichment_status")
            if status != "pending":
                continue
        else:
            conf = row.get(conf_key)
            try:
                if conf is not None and float(conf) >= 50:
                    continue
            except (TypeError, ValueError):
                pass
        company = parse_company(row, fmap)
        if not company:
            continue
        companies.append(company)
        rows.append(row)
    return companies, rows


def _settings(
    *,
    chunk_size: int,
    harvest_concurrency: int,
    resolve_concurrency: int,
) -> Any:
    return settings_from_input(
        {
            "google_results_per_page": 10,
            "max_harvest_candidates": 2,
            "fallback_google_by_website": True,
            "fallback_harvest_search": True,
            "fallback_homepage_linkedin": True,
            "use_ai_for_ambiguous": False,
            "batch_size": chunk_size,
            "harvest_concurrency": harvest_concurrency,
            "resolve_concurrency": resolve_concurrency,
            "debug": False,
        },
        env_token=os.getenv("APIFY_TOKEN"),
        env_harvest=os.getenv("HARVEST_API_KEY"),
        env_openai=os.getenv("OPENAI_API_KEY"),
    )


async def _prefetch_google(companies: list[CompanyInput], settings: Any) -> list[Any]:
    query_list: list[str] = []
    for company in companies:
        query_list.extend(build_initial_queries(company.legal_name))
    return await run_google_searches(
        query_list,
        actor_id=settings.google_actor_id,
        token=settings.apify_token,
        country_code=settings.country_code,
        language_code=settings.language_code,
        results_per_page=settings.google_results_per_page,
        batch_size=settings.batch_size,
    )


async def _resolve_prefetched(
    companies: list[CompanyInput],
    settings: Any,
    all_evidences: list[Any],
) -> list[ResolutionResult]:
    resolve_concurrency = max(1, settings.resolve_concurrency)
    if resolve_concurrency <= 1:
        out: list[ResolutionResult] = []
        for company in companies:
            out.append(await resolve_company(company, settings, prefetched_evidences=all_evidences))
        return out

    import asyncio

    sem = asyncio.Semaphore(resolve_concurrency)

    async def _one(company: CompanyInput) -> ResolutionResult:
        async with sem:
            return await resolve_company(company, settings, prefetched_evidences=all_evidences)

    return list(await asyncio.gather(*[_one(c) for c in companies]))


async def _run_mode(
    companies: list[CompanyInput],
    *,
    label: str,
    chunk_size: int,
    harvest_concurrency: int,
    resolve_concurrency: int,
    prefetched_evidences: list[Any] | None = None,
) -> tuple[float, list[ResolutionResult]]:
    settings = _settings(
        chunk_size=chunk_size,
        harvest_concurrency=harvest_concurrency,
        resolve_concurrency=resolve_concurrency,
    )
    print(
        f"\n=== {label} (n={len(companies)}, chunk={chunk_size}, "
        f"harvest_cc={harvest_concurrency}, resolve_cc={resolve_concurrency}) ===",
        flush=True,
    )
    t0 = time.perf_counter()
    if prefetched_evidences is not None:
        results = await _resolve_prefetched(companies, settings, prefetched_evidences)
    else:
        results = await resolve_companies_batch(companies, settings)
    elapsed = time.perf_counter() - t0
    print(f"Elapsed: {elapsed:.1f}s ({elapsed / max(1, len(companies)):.1f}s/org)", flush=True)
    return elapsed, results


async def main_async(args: argparse.Namespace) -> int:
    flags = load_n8n_vars()
    missing = [name for name, ok in flags.items() if not ok]
    if missing:
        print("Missing tokens: " + ", ".join(missing), file=sys.stderr)
        return 2

    companies, _rows = await _fetch_sample(
        table=args.table,
        view=args.view,
        only_pending=args.only_pending,
        limit=args.limit,
    )
    if not companies:
        print("No sample rows found.", file=sys.stderr)
        return 1

    print(f"Sample: {len(companies)} companies from view {args.view}", flush=True)
    for c in companies:
        print(f"  - {c.legal_name}", flush=True)

    shared_google: list[Any] | None = None
    if args.isolate_resolve:
        base_settings = _settings(chunk_size=args.chunk_size, harvest_concurrency=3, resolve_concurrency=1)
        print("\nPrefetching Google once for isolate-resolve comparison …", flush=True)
        tg0 = time.perf_counter()
        shared_google = await _prefetch_google(companies, base_settings)
        print(f"Google prefetch: {time.perf_counter() - tg0:.1f}s", flush=True)

    harvest_base = 3 if args.isolate_resolve else 3
    harvest_fast = 3 if args.isolate_resolve else args.harvest_concurrency

    t_base, res_base = await _run_mode(
        companies,
        label="baseline",
        chunk_size=args.chunk_size,
        harvest_concurrency=harvest_base,
        resolve_concurrency=1,
        prefetched_evidences=shared_google,
    )
    t_fast, res_fast = await _run_mode(
        companies,
        label="candidate",
        chunk_size=args.chunk_size,
        harvest_concurrency=harvest_fast,
        resolve_concurrency=args.resolve_concurrency,
        prefetched_evidences=shared_google,
    )

    diffs = _compare(res_base, res_fast)
    report = {
        "sample_size": len(companies),
        "chunk_size": args.chunk_size,
        "isolate_resolve": args.isolate_resolve,
        "baseline": {
            "resolve_concurrency": 1,
            "harvest_concurrency": 3,
            "elapsed_s": round(t_base, 2),
            "per_org_s": round(t_base / len(companies), 2),
        },
        "candidate": {
            "resolve_concurrency": args.resolve_concurrency,
            "harvest_concurrency": args.harvest_concurrency,
            "elapsed_s": round(t_fast, 2),
            "per_org_s": round(t_fast / len(companies), 2),
        },
        "speedup": round(t_base / t_fast, 2) if t_fast > 0 else None,
        "efficacy_match": len(diffs) == 0,
        "diff_count": len(diffs),
        "diffs": diffs[:20],
        "lift_baseline_ge_50": sum(1 for r in res_base if float(r.confidence or 0) >= 50),
        "lift_candidate_ge_50": sum(1 for r in res_fast if float(r.confidence or 0) >= 50),
    }
    out = Path(args.output)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport: {out}", flush=True)
    print(json.dumps({k: report[k] for k in report if k != "diffs"}, indent=2), flush=True)
    if diffs:
        print(f"WARNING: {len(diffs)} row(s) differ between modes (see report).", flush=True)
        return 3
    print("Efficacy: outputs match on fingerprint fields.", flush=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Benchmark resolve concurrency (no NocoDB PATCH)")
    p.add_argument("--table", default=DEFAULT_TABLE)
    p.add_argument("--view", default=DEFAULT_VIEW)
    p.add_argument("--only-pending", action="store_true")
    p.add_argument("--limit", type=int, default=6)
    p.add_argument("--chunk-size", type=int, default=10)
    p.add_argument("--resolve-concurrency", type=int, default=4)
    p.add_argument("--harvest-concurrency", type=int, default=5)
    p.add_argument("--output", default="/tmp/benchmark-resolve-modes.json")
    p.add_argument(
        "--isolate-resolve",
        action="store_true",
        help="One Google prefetch; compare only resolve step (fair efficacy check)",
    )
    return p


def main() -> int:
    return asyncio.run(main_async(build_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
