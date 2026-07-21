"""Small helpers around Apify Client to avoid nested-run hangs."""

from __future__ import annotations

from typing import Any

from apify import Actor


async def call_actor_collect_items(
    *,
    token: str,
    actor_id: str,
    run_input: dict[str, Any],
    item_limit: int = 500,
) -> list[dict[str, Any]]:
    """Run an Actor and return dataset items without hanging on iterate_items.

    Nested Actor calls inside another Actor have hung indefinitely on
    ``dataset.iterate_items()`` after the child SUCCEEDED. Prefer ``list_items``
    and always close the async client.
    """
    try:
        from apify_client import ApifyClientAsync
    except ImportError:
        Actor.log.error("apify_client is not available.")
        return []

    items: list[dict[str, Any]] = []
    async with ApifyClientAsync(token) as client:
        Actor.log.info("Starting nested Actor %s …", actor_id)
        try:
            run = await client.actor(actor_id).call(run_input=run_input)
        except Exception as exc:  # noqa: BLE001
            Actor.log.exception("Nested Actor %s call failed: %s", actor_id, type(exc).__name__)
            return []

        dataset_id = None
        if run is not None:
            dataset_id = getattr(run, "default_dataset_id", None)
            if dataset_id is None and isinstance(run, dict):
                dataset_id = run.get("defaultDatasetId") or run.get("default_dataset_id")

        if not dataset_id:
            Actor.log.warning("Nested Actor %s returned no dataset.", actor_id)
            return []

        Actor.log.info("Nested Actor %s finished; listing dataset %s …", actor_id, dataset_id)
        try:
            page = await client.dataset(dataset_id).list_items(limit=max(1, item_limit))
        except Exception as exc:  # noqa: BLE001
            Actor.log.exception("Failed listing dataset %s: %s", dataset_id, type(exc).__name__)
            return []

        raw = getattr(page, "items", None)
        if raw is None and isinstance(page, dict):
            raw = page.get("items") or []
        for item in raw or []:
            if isinstance(item, dict):
                items.append(item)
        Actor.log.info("Collected %s items from nested Actor %s.", len(items), actor_id)
    return items
