#!/usr/bin/env python3
"""Dry-run style test: one NocoDB row with pipedrive_status=ok → Pipedrive + writeback."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

TABLE_ID = "mewh1ynmcokfsfi"
PD_KEYS = {
    "commercial_name": "ad92da1357d2612b282574a28ea8d5f18e09b13a",
    "confidence": "628cc21653e5dca37e601419181fb80749078d08",
    "employees": "e55be59bd4c78ea7f813a11cabad9923b88cd00c",
    "followers": "a299f56478797e7f5bc6fbdd16665f54e99c03c4",
    "enriched_at": "f0d998fd9c76c525ff78cd4eb3795bfdc55312b7",
}


def load_cfg_from_workflow() -> dict:
    wf = json.loads(Path("/tmp/n8n_wf_full.json").read_text())
    node = next(n for n in wf["nodes"] if n["name"] == "config1")
    return {a["name"]: a["value"] for a in node["parameters"]["assignments"]["assignments"]}


def http_json(req: urllib.request.Request) -> dict:
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def main() -> None:
    cfg = load_cfg_from_workflow()
    nc_token = os.environ.get("NOCO_TOKEN") or cfg["nocodb_api_token"]
    nc_base = cfg["nocodb_base_url"].rstrip("/")
    pd_base = cfg["pipedrive_api_base"].rstrip("/")
    pd_token = cfg["pipedrive_api_token"]

    where = "(confidence,gt,60)~and(pipedrive_status,eq,ok)"
    url = (
        f"{nc_base}/api/v2/tables/{TABLE_ID}/records?"
        + urllib.parse.urlencode({"where": where, "limit": 1})
    )
    rows = http_json(urllib.request.Request(url, headers={"xc-token": nc_token})).get("list") or []
    if not rows:
        raise SystemExit("no rows with pipedrive_status=ok")
    row = rows[0]
    org_id = int(row.get("pipedrive_org_id") or row.get("source_id"))
    payload = {}
    if row.get("linkedin_url"):
        payload["linkedin"] = row["linkedin_url"]
    website = (row.get("website") or "").strip()
    if not website and row.get("domain"):
        website = f"https://{row['domain']}" if "://" not in str(row["domain"]) else row["domain"]
    if website:
        payload["website"] = website
    # industry skipped — Pipedrive validates against fixed options only
    if row.get("commercial_name"):
        payload[PD_KEYS["commercial_name"]] = row["commercial_name"]
    if row.get("confidence") is not None:
        payload[PD_KEYS["confidence"]] = float(row["confidence"])
    if row.get("employee_count") is not None:
        payload[PD_KEYS["employees"]] = float(row["employee_count"])
    if row.get("followers") is not None:
        payload[PD_KEYS["followers"]] = float(row["followers"])
    payload[PD_KEYS["enriched_at"]] = str(row.get("enriched_at") or "")[:10] or __import__("datetime").date.today().isoformat()

    upd_url = f"{pd_base}/organizations/{org_id}?" + urllib.parse.urlencode({"api_token": pd_token})
    upd = http_json(
        urllib.request.Request(
            upd_url,
            data=json.dumps(payload).encode(),
            method="PUT",
            headers={"Content-Type": "application/json"},
        )
    )
    if not upd.get("success"):
        raise SystemExit(f"pipedrive update failed: {upd}")

    synced_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    patch_req = urllib.request.Request(
        f"{nc_base}/api/v2/tables/{TABLE_ID}/records",
        data=json.dumps([{"Id": row["Id"], "update_pipedrive": synced_at, "pipedrive_status": "synced"}]).encode(),
        method="PATCH",
        headers={"xc-token": nc_token, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(patch_req) as resp:
        patch_body = resp.read().decode()

    print(
        json.dumps(
            {
                "row_id": row["Id"],
                "org_id": org_id,
                "legal_name": row.get("legal_name"),
                "pipedrive_update": True,
                "nocodb_patch": patch_body,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
