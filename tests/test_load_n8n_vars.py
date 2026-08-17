"""Unit checks for Plan B n8n variable loader (no live secrets)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.load_n8n_vars import _jwt_aud, load_n8n_vars, rest_api_key


def _jwt(aud: str) -> str:
    payload = json.dumps({"aud": aud, "iss": "n8n"}).encode()
    import base64

    mid = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    return f"aaa.{mid}.bbb"


def test_jwt_aud_and_mcp_skip() -> None:
    assert _jwt_aud(_jwt("public-api")) == "public-api"
    assert _jwt_aud(_jwt("mcp-server-api")) == "mcp-server-api"
    with patch.dict("os.environ", {"N8N_API_KEY": _jwt("mcp-server-api")}, clear=True):
        assert rest_api_key() is None
    with patch.dict(
        "os.environ",
        {"N8N_REST_API_KEY": _jwt("public-api"), "N8N_API_KEY": _jwt("mcp-server-api")},
        clear=True,
    ):
        key = rest_api_key()
        assert key is not None
        assert _jwt_aud(key) == "public-api"
    print("OK jwt aud / MCP skip")


def test_load_keeps_existing_and_fills_missing() -> None:
    fetched = {
        "APIFY_TOKEN": "from-n8n-apify",
        "HARVEST_API_KEY": "from-n8n-harvest",
        "NOCO_TOKEN": "from-n8n-noco",
    }
    env = {
        "N8N_REST_API_KEY": _jwt("public-api"),
        "N8N_URL": "https://example.invalid",
        "APIFY_TOKEN": "already-set",
    }
    with patch.dict("os.environ", env, clear=True):
        with patch("scripts.load_n8n_vars.fetch_n8n_variables", return_value=fetched):
            flags = load_n8n_vars()
        assert flags == {"APIFY_TOKEN": True, "HARVEST_API_KEY": True, "NOCO_TOKEN": True}
        import os

        assert os.environ["APIFY_TOKEN"] == "already-set"
        assert os.environ["HARVEST_API_KEY"] == "from-n8n-harvest"
        assert os.environ["NOCO_TOKEN"] == "from-n8n-noco"
    print("OK load keeps Plan A and fills Plan B")


def main() -> None:
    test_jwt_aud_and_mcp_skip()
    test_load_keeps_existing_and_fills_missing()
    print("All load_n8n_vars checks passed.")


if __name__ == "__main__":
    main()
