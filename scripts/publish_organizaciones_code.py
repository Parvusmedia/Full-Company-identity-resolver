#!/usr/bin/env python3
"""Publish scripts/n8n_push_organizaciones_code.js into the live enrich workflow.

Updates only the Code node jsCode. Does not change triggers, config, or active state.
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


def main() -> None:
    js_code = CODE_PATH.read_text(encoding="utf-8")
    if "function mapIndustry" not in js_code or "payload.industry = industry.id" not in js_code:
        raise SystemExit("refusing to publish push code without industry mapping")

    workflow = api("GET", f"/workflows/{WORKFLOW_ID}")
    node = next(item for item in workflow["nodes"] if item["name"] == NODE_NAME)
    node["parameters"]["jsCode"] = js_code

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
