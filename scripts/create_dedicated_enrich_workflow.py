#!/usr/bin/env python3
"""Create/activate standalone n8n workflow for NocoDB ok → Pipedrive (no suppression cron)."""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

CODE_PATH = Path(__file__).with_name("n8n_push_organizaciones_code.js")
SOURCE_WORKFLOW_ID = "YEiosPHh8GxGSY64"
WORKFLOW_NAME = "TefSeguros NocoDB OK → Pipedrive Push"
WEBHOOK_PATH = "telefonica-org-pipedrive-push"


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


def load_enrich_config() -> list[dict]:
    wf = api("GET", f"/workflows/{SOURCE_WORKFLOW_ID}")
    for name in ("config_enrich_push", "config1"):
        try:
            config_node = next(n for n in wf["nodes"] if n["name"] == name)
            break
        except StopIteration:
            config_node = None
    if not config_node:
        raise RuntimeError("No config_enrich_push or config1 in source workflow")
    base_cfg = {
        a["name"]: a["value"]
        for a in config_node["parameters"]["assignments"]["assignments"]
    }
    keys = [
        "pipedrive_api_base",
        "pipedrive_api_token",
        "nocodb_base_url",
        "nocodb_api_token",
        "code_time_budget_ms",
    ]
    assignments = [
        {"id": f"cfg-enrich-{i}", "name": k, "value": base_cfg.get(k, ""), "type": "string"}
        for i, k in enumerate(keys)
    ]
    assignments.extend(
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
                "value": "15",
                "type": "string",
            },
        ]
    )
    return assignments


def build_workflow(assignments: list[dict], js_code: str) -> dict:
    push = "Push Enriched Organizaciones to Pipedrive"
    cfg = "config_enrich_push"
    nodes = [
        {
            "parameters": {},
            "type": "n8n-nodes-base.manualTrigger",
            "typeVersion": 1,
            "position": [-1200, 300],
            "id": "dedicated-manual",
            "name": "Manual",
        },
        {
            "parameters": {
                "rule": {"interval": [{"field": "minutes", "minutesInterval": 5}]},
            },
            "type": "n8n-nodes-base.scheduleTrigger",
            "typeVersion": 1.2,
            "position": [-1200, 480],
            "id": "dedicated-schedule",
            "name": "Every 5 minutes",
        },
        {
            "parameters": {
                "httpMethod": "POST",
                "path": WEBHOOK_PATH,
                "options": {},
            },
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2,
            "position": [-1200, 660],
            "id": "dedicated-webhook",
            "name": "NocoDB Webhook",
            "webhookId": "tefseguros-org-pipedrive-push",
        },
        {
            "parameters": {
                "content": "## Auto-sync\n\nPoll cada **5 min** filas con `pipedrive_status=ok`.\n\nWebhook (workflow activo): POST al path configurado.\n\nNocoDB **no** dispara n8n solo por editar una celda sin webhook.",
                "height": 200,
                "width": 460,
            },
            "type": "n8n-nodes-base.stickyNote",
            "typeVersion": 1,
            "position": [-1240, 80],
            "id": "dedicated-note",
            "name": "Sticky Note",
        },
        {
            "parameters": {"assignments": {"assignments": assignments}, "options": {}},
            "type": "n8n-nodes-base.set",
            "typeVersion": 3.4,
            "position": [-960, 480],
            "id": "dedicated-config",
            "name": cfg,
        },
        {
            "parameters": {"jsCode": js_code},
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [-720, 480],
            "id": "dedicated-push",
            "name": push,
        },
    ]
    connections = {
        "Manual": {"main": [[{"node": cfg, "type": "main", "index": 0}]]},
        "Every 5 minutes": {"main": [[{"node": cfg, "type": "main", "index": 0}]]},
        "NocoDB Webhook": {"main": [[{"node": cfg, "type": "main", "index": 0}]]},
        cfg: {"main": [[{"node": push, "type": "main", "index": 0}]]},
    }
    return {
        "name": WORKFLOW_NAME,
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1", "executionTimeout": 600},
    }


def find_existing_id() -> str | None:
    data = api("GET", "/workflows?limit=250")
    for wf in data.get("data", []):
        if wf.get("name") == WORKFLOW_NAME:
            return wf["id"]
    return None


def main() -> None:
    js_code = CODE_PATH.read_text(encoding="utf-8")
    body = build_workflow(load_enrich_config(), js_code)
    existing = find_existing_id()
    if existing:
        result = api("PUT", f"/workflows/{existing}", body)
        wf_id = existing
    else:
        result = api("POST", "/workflows", body)
        wf_id = result["id"]
    api("POST", f"/workflows/{wf_id}/activate", {})
    activated = api("GET", f"/workflows/{wf_id}")
    print(
        json.dumps(
            {
                "id": wf_id,
                "name": activated.get("name"),
                "active": activated.get("active"),
                "webhook_path": WEBHOOK_PATH,
                "webhook_url_hint": f"{os.environ['N8N_URL'].rstrip('/')}/webhook/{WEBHOOK_PATH}",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
