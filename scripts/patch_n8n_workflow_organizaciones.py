#!/usr/bin/env python3
"""Patch YEiosPHh8GxGSY64 with NocoDB organizaciones → Pipedrive branch."""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

import urllib.request

WORKFLOW_ID = "YEiosPHh8GxGSY64"
CODE_PATH = Path(__file__).with_name("n8n_push_organizaciones_code.js")


def load_js() -> str:
    return CODE_PATH.read_text(encoding="utf-8")


def patch_workflow(workflow: dict) -> dict:
    js_code = load_js()

    config_node = next(n for n in workflow["nodes"] if n["name"] == "config1")
    base_cfg = {a["name"]: a["value"] for a in config_node["parameters"]["assignments"]["assignments"]}
    enrich_keys = [
        "pipedrive_api_base",
        "pipedrive_api_token",
        "nocodb_base_url",
        "nocodb_api_token",
        "code_time_budget_ms",
    ]
    enrich_assignments = [
        {
            "id": f"cfg-enrich-{i}",
            "name": key,
            "value": base_cfg.get(key, ""),
            "type": "string",
        }
        for i, key in enumerate(enrich_keys)
    ]
    enrich_assignments.extend(
        [
            {
                "id": "cfg-enrich-table",
                "name": "nocodb_organizaciones_table_id",
                "value": "mewh1ynmcokfsfi",
                "type": "string",
            },
            {
                "id": "cfg-enrich-max",
                "name": "enrich_push_max_rows_per_run",
                "value": "50",
                "type": "string",
            },
        ]
    )

    push_node_name = "Push Enriched Organizaciones to Pipedrive"
    config_enrich_node = {
        "parameters": {
            "assignments": {"assignments": enrich_assignments},
            "options": {},
        },
        "type": "n8n-nodes-base.set",
        "typeVersion": 3.4,
        "position": [-1160, 800],
        "id": "a8f3c2e1-config-enrich-0005",
        "name": "config_enrich_push",
    }
    new_nodes = [
        {
            "parameters": {},
            "type": "n8n-nodes-base.manualTrigger",
            "typeVersion": 1,
            "position": [-1400, 720],
            "id": "a8f3c2e1-push-org-manual-0001",
            "name": "Push Organizaciones (Manual)",
        },
        {
            "parameters": {
                "rule": {"interval": [{"field": "hours", "hoursInterval": 2}]},
            },
            "type": "n8n-nodes-base.scheduleTrigger",
            "typeVersion": 1.2,
            "position": [-1400, 900],
            "id": "a8f3c2e1-push-org-sched-0002",
            "name": "Push Organizaciones (Every 2h)",
        },
        {
            "parameters": {
                "content": "## NocoDB organizaciones → Pipedrive\n\nFiltro: `confidence > 60` y `pipedrive_status = ok`.\n\nTras éxito: `update_pipedrive` + `pipedrive_status = synced`.\n\nNota PD: match_status, relationship, evidence_summary (+ HQ si no parsea).",
                "height": 220,
                "width": 480,
            },
            "type": "n8n-nodes-base.stickyNote",
            "typeVersion": 1,
            "position": [-1440, 560],
            "id": "a8f3c2e1-push-org-note-0003",
            "name": "Sticky Note Enrich Push",
        },
        config_enrich_node,
        {
            "parameters": {"jsCode": js_code},
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [-920, 800],
            "id": "a8f3c2e1-push-org-code-0004",
            "name": push_node_name,
        },
    ]

    names = {n["name"] for n in workflow["nodes"]}
    for node in new_nodes:
        if node["name"] not in names:
            workflow["nodes"].append(node)

    conns = workflow.setdefault("connections", {})
    enrich_cfg = "config_enrich_push"
    for trigger in ("Push Organizaciones (Manual)", "Push Organizaciones (Every 2h)"):
        conns[trigger] = {"main": [[{"node": enrich_cfg, "type": "main", "index": 0}]]}
    conns[enrich_cfg] = {"main": [[{"node": push_node_name, "type": "main", "index": 0}]]}

    # Ensure config1 only feeds suppression branch (remove accidental enrich fork).
    cfg_main = conns.get("config1", {}).get("main", [[]])[0]
    conns["config1"] = {
        "main": [[item for item in cfg_main if item["node"] != push_node_name]]
    }

    return workflow


def api_put(workflow: dict) -> dict:
    base = os.environ["N8N_URL"].rstrip("/")
    key = os.environ["N8N_REST_API_KEY"]
    allowed_settings = {"executionOrder", "executionTimeout", "callerPolicy"}
    raw_settings = workflow.get("settings") or {}
    settings = {k: v for k, v in raw_settings.items() if k in allowed_settings}
    payload = {
        "name": workflow["name"],
        "nodes": workflow["nodes"],
        "connections": workflow["connections"],
        "settings": settings,
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/api/v1/workflows/{WORKFLOW_ID}",
        data=body,
        method="PUT",
        headers={"X-N8N-API-KEY": key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    src = Path("/tmp/n8n_wf_full.json")
    if not src.exists():
        print("missing workflow json", file=sys.stderr)
        return 1
    workflow = json.loads(src.read_text())
    patched = patch_workflow(workflow)
    Path("/tmp/n8n_wf_patched.json").write_text(json.dumps(patched, indent=2), encoding="utf-8")
    result = api_put(patched)
    print("updated", result.get("id"), result.get("name"), "nodes", len(result.get("nodes", [])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
