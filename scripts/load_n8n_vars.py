"""Plan B: load enrichment tokens from n8n Variables. Never print values."""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

WANTED = ("APIFY_TOKEN", "HARVEST_API_KEY", "NOCO_TOKEN")
DEFAULT_N8N_URL = "https://pmedia.app.n8n.cloud"


def _jwt_aud(token: str) -> str | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return None
    aud = data.get("aud")
    return aud if isinstance(aud, str) else None


def rest_api_key() -> str | None:
    """Prefer N8N_REST_API_KEY (public-api). Ignore MCP tokens."""
    explicit = (os.getenv("N8N_REST_API_KEY") or "").strip()
    if explicit:
        aud = _jwt_aud(explicit)
        if aud and aud != "public-api":
            print(
                f"N8N_REST_API_KEY aud={aud} (expected public-api); trying anyway",
                file=sys.stderr,
            )
        return explicit
    fallback = (os.getenv("N8N_API_KEY") or "").strip()
    if not fallback:
        return None
    aud = _jwt_aud(fallback)
    if aud == "mcp-server-api":
        print(
            "N8N_API_KEY is an MCP token (aud=mcp-server-api) and cannot read Variables. "
            "Set N8N_REST_API_KEY with a public-api key.",
            file=sys.stderr,
        )
        return None
    return fallback


def _get_json(url: str, key: str) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={"X-N8N-API-KEY": key, "Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        raw = resp.read().decode()
        return json.loads(raw) if raw else {}


def fetch_n8n_variables(*, n8n_url: str, api_key: str) -> dict[str, str]:
    data = _get_json(n8n_url.rstrip("/") + "/api/v1/variables?limit=50", api_key)
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise RuntimeError("n8n /api/v1/variables did not return a data list")
    out: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("key")
        value = item.get("value")
        if isinstance(name, str) and isinstance(value, str) and value:
            out[name] = value
    return out


def load_n8n_vars(*, overwrite: bool = False) -> dict[str, bool]:
    """Ensure WANTED vars are in os.environ. Returns presence flags only."""
    present_before = {name: bool(os.getenv(name)) for name in WANTED}
    if all(present_before.values()) and not overwrite:
        return present_before

    key = rest_api_key()
    if not key:
        return {name: bool(os.getenv(name)) for name in WANTED}

    n8n_url = (os.getenv("N8N_URL") or DEFAULT_N8N_URL).rstrip("/")
    try:
        fetched = fetch_n8n_variables(n8n_url=n8n_url, api_key=key)
    except urllib.error.HTTPError as exc:
        print(f"n8n variables HTTP {exc.code}", file=sys.stderr)
        return {name: bool(os.getenv(name)) for name in WANTED}

    for name in WANTED:
        value = fetched.get(name) or ""
        if not value:
            continue
        if overwrite or not os.getenv(name):
            os.environ[name] = value

    return {name: bool(os.getenv(name)) for name in WANTED}


def main() -> int:
    flags = load_n8n_vars()
    missing = [name for name, ok in flags.items() if not ok]
    for name, ok in flags.items():
        print(f"{name}: {'SET' if ok else 'MISSING'}")
    if missing:
        print("Plan B incomplete. Missing: " + ", ".join(missing), file=sys.stderr)
        return 1
    print("Plan B OK (values not printed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
