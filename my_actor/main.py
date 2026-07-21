"""Module defines the main entry point for the Apify Actor."""

from __future__ import annotations

import os
import sys

from apify import Actor

from .resolver import parse_input_companies, resolve_companies_batch, settings_from_input


async def main() -> None:
    """Define the main entry point for the Apify Actor."""
    async with Actor:
        raw_input = await Actor.get_input() or {}
        if not isinstance(raw_input, dict):
            await Actor.fail(status_message="Actor input must be a JSON object.")
            return

        companies = parse_input_companies(raw_input)
        if not companies:
            message = (
                "No companies provided. Pass `queries` (newline-separated legal names) "
                "or a non-empty `companies` array."
            )
            Actor.log.error(message)
            await Actor.fail(status_message=message)
            return

        settings = settings_from_input(
            raw_input,
            env_token=os.getenv("APIFY_TOKEN"),
            env_harvest=os.getenv("HARVEST_API_KEY"),
            env_openai=os.getenv("OPENAI_API_KEY"),
        )

        Actor.log.info(
            "Starting Full Company Identity Resolver for %s companies (debug=%s, max_harvest=%s).",
            len(companies),
            settings.debug,
            settings.max_harvest_candidates,
        )
        if not settings.apify_token:
            Actor.log.warning("APIFY_TOKEN not set; Google Search Actor calls will fail.")
        if not settings.harvest_api_key:
            Actor.log.warning("HARVEST_API_KEY not set; enrichment will keep Google evidence only.")

        results = await resolve_companies_batch(companies, settings)

        for result in results:
            item = result.to_dataset_item(debug=settings.debug)
            await Actor.push_data(item)

        ok = sum(1 for r in results if r.match_status not in {"error", "not_found"})
        Actor.log.info(
            "Finished. rows=%s matched_or_partial=%s not_found_or_error=%s",
            len(results),
            ok,
            len(results) - ok,
        )


if __name__ == "__main__":
    # Allow `python my_actor/main.py` during local checks.
    import asyncio

    try:
        asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        print(f"Actor failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
