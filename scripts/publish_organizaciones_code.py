#!/usr/bin/env python3
"""Publish scripts/n8n_push_organizaciones_code.js into the live enrich workflow.

Updates the Code node and the non-secret batch settings on config_enrich_push.
Adds the n8n API coordinates used for single-flight from the environment.
Does not print token values.
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

WORKFLOW_ID = "7A1xSnh6x5QeynjU"
NODE_NAME = "Push Enriched Organizaciones to Pipedrive"
CODE_PATH = Path(__file__).with_name("n8n_push_organizaciones_code.js")


def api(method: str, path: str, body: dict | None = None) -> dict:
    base = os.environ["N8N_URL"].rstrip("/")
    key = os.environ["N8N_REST_API_KEY"]
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/api/v1{path}",
        data=data,
        method=method,
        headers={"X-N8N-API-KEY": key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode()
        return json.loads(raw) if raw else {}


CONFIG_VALUES = {
    "enrich_push_max_rows_per_run": "50",
    "code_time_budget_ms": "240000",
    "single_flight_settle_ms": "2000",
    "n8n_workflow_id": WORKFLOW_ID,
}


def upsert_config(workflow: dict) -> None:
    node = next(item for item in workflow["nodes"] if item["name"] == "config_enrich_push")
    assignments = node["parameters"]["assignments"]["assignments"]
    by_name = {item["name"]: item for item in assignments}
    values = dict(CONFIG_VALUES)
    values["n8n_api_base"] = os.environ["N8N_URL"].rstrip("/")
    values["n8n_api_key"] = os.environ["N8N_REST_API_KEY"]
    for name, value in values.items():
        if name in by_name:
            by_name[name]["value"] = value
            continue
        assignments.append({"id": f"cfg-{name}", "name": name, "value": value, "type": "string"})


def main() -> None:
    js_code = CODE_PATH.read_text(encoding="utf-8")
    if "function mapIndustry" not in js_code or "shouldYieldToOlderRun" not in js_code:
        raise SystemExit("refusing to publish push code without industry mapping and single-flight")

    workflow = api("GET", f"/workflows/{WORKFLOW_ID}")
    node = next(item for item in workflow["nodes"] if item["name"] == NODE_NAME)
    node["parameters"]["jsCode"] = js_code
    upsert_config(workflow)

    allowed_settings = {"executionOrder", "executionTimeout", "callerPolicy"}
    settings = {k: v for k, v in (workflow.get("settings") or {}).items() if k in allowed_settings}
    result = api(
        "PUT",
        f"/workflows/{WORKFLOW_ID}",
        {
            "name": workflow["name"],
            "nodes": workflow["nodes"],
            "connections": workflow["connections"],
            "settings": settings,
        },
    )
    published = next(item for item in result["nodes"] if item["name"] == NODE_NAME)
    if published["parameters"]["jsCode"] != js_code:
        raise SystemExit("published jsCode does not match local file")
    published_cfg = next(item for item in result["nodes"] if item["name"] == "config_enrich_push")
    names = {item["name"] for item in published_cfg["parameters"]["assignments"]["assignments"]}
    missing = [name for name in ("enrich_push_max_rows_per_run", "n8n_workflow_id", "n8n_api_key") if name not in names]
    if missing:
        raise SystemExit(f"published config missing {missing}")
    print(
        "published",
        result.get("id"),
        result.get("name"),
        "active",
        result.get("active"),
        "code_bytes",
        len(js_code),
    )


if __name__ == "__main__":
    main()
