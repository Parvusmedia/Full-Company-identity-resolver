#!/usr/bin/env python3
"""Deploy n8n_push_organizaciones_code.js to all workflows that use it."""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

CODE_PATH = Path(__file__).with_name("n8n_push_organizaciones_code.js")
PUSH_NODE = "Push Enriched Organizaciones to Pipedrive"
WORKFLOW_IDS = ("7A1xSnh6x5QeynjU", "YEiosPHh8GxGSY64")


def api_get(path: str) -> dict:
    req = urllib.request.Request(
        f"{os.environ['N8N_URL'].rstrip('/')}/api/v1{path}",
        headers={"X-N8N-API-KEY": os.environ["N8N_REST_API_KEY"]},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def api_put(workflow_id: str, body: dict) -> dict:
    allowed = {"executionOrder", "executionTimeout", "callerPolicy"}
    settings = {k: v for k, v in (body.get("settings") or {}).items() if k in allowed}
    payload = {
        "name": body["name"],
        "nodes": body["nodes"],
        "connections": body["connections"],
        "settings": settings,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{os.environ['N8N_URL'].rstrip('/')}/api/v1/workflows/{workflow_id}",
        data=data,
        method="PUT",
        headers={
            "X-N8N-API-KEY": os.environ["N8N_REST_API_KEY"],
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def main() -> None:
    js = CODE_PATH.read_text(encoding="utf-8")
    for wf_id in WORKFLOW_IDS:
        try:
            wf = api_get(f"/workflows/{wf_id}")
        except urllib.error.HTTPError:
            print("skip", wf_id, "not found")
            continue
        updated = False
        for node in wf.get("nodes", []):
            if node.get("name") == PUSH_NODE and node.get("type") == "n8n-nodes-base.code":
                node.setdefault("parameters", {})["jsCode"] = js
                updated = True
        if not updated:
            print("skip", wf_id, "no push node")
            continue
        api_put(wf_id, wf)
        print("deployed", wf_id, wf.get("name"))


if __name__ == "__main__":
    main()
