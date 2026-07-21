"""Small helpers around Apify Client to avoid nested-run hangs."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from apify import Actor


async def call_actor_collect_items(
    *,
    token: str,
    actor_id: str,
    run_input: dict[str, Any],
    item_limit: int = 500,
    wait_secs: int = 300,
) -> list[dict[str, Any]]:
    """Run an Actor and return dataset items without hanging on iterate_items.

    Nested Actor calls inside another Actor have hung indefinitely after the
    child SUCCEEDED when draining via ``iterate_items()``. Prefer ``list_items``
    with an explicit wait budget on ``call()``.
    """
    try:
        from apify_client import ApifyClientAsync
    except ImportError:
        Actor.log.error("apify_client is not available.")
        return []

    client = ApifyClientAsync(token)
    Actor.log.info("Starting nested Actor %s (wait_secs=%s) …", actor_id, wait_secs)
    try:
        run = await client.actor(actor_id).call(
            run_input=run_input,
            wait_duration=timedelta(seconds=max(30, wait_secs)),
            timeout="long",
        )
    except Exception as exc:  # noqa: BLE001
        Actor.log.exception("Nested Actor %s call failed: %s", actor_id, type(exc).__name__)
        return []

    if run is None:
        Actor.log.warning("Nested Actor %s returned no run (timeout?).", actor_id)
        return []

    status = getattr(run, "status", None)
    if status is None and isinstance(run, dict):
        status = run.get("status")
    Actor.log.info("Nested Actor %s status=%s", actor_id, status)

    dataset_id = getattr(run, "default_dataset_id", None)
    if dataset_id is None and isinstance(run, dict):
        dataset_id = run.get("defaultDatasetId") or run.get("default_dataset_id")

    if not dataset_id:
        Actor.log.warning("Nested Actor %s returned no dataset.", actor_id)
        return []

    Actor.log.info("Listing dataset %s (limit=%s) …", dataset_id, item_limit)
    try:
        page = await client.dataset(dataset_id).list_items(limit=max(1, item_limit))
    except Exception as exc:  # noqa: BLE001
        Actor.log.exception("Failed listing dataset %s: %s", dataset_id, type(exc).__name__)
        return []

    raw = getattr(page, "items", None)
    if raw is None and isinstance(page, dict):
        raw = page.get("items") or []
    items = [item for item in (raw or []) if isinstance(item, dict)]
    Actor.log.info("Collected %s items from nested Actor %s.", len(items), actor_id)
    return items
