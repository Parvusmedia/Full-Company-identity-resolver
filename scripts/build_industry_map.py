#!/usr/bin/env python3
"""Build scripts/industry_map.js from LinkedIn v2 roots + legacy aliases.

The n8n code node cannot import files. This script inlines the same map
between INDUSTRY_MAP_START / INDUSTRY_MAP_END in
scripts/n8n_push_organizaciones_code.js.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
MAP_JS = ROOT / "industry_map.js"
PUSH_JS = ROOT / "n8n_push_organizaciones_code.js"
START = "// INDUSTRY_MAP_START"
END = "// INDUSTRY_MAP_END"


def normalize_industry(value: str) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.lower().strip().replace("&", " and ")
    text = re.sub(r"[,/]+", " ", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def load_json(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def build_map() -> tuple[dict[str, int], dict[int, str]]:
    options = load_json("pipedrive_industry_options.json")
    by_en = {row["label_en"]: row["id"] for row in options}
    labels = {row["id"]: row["label_es"] for row in options}
    mapping: dict[str, int] = {}

    def put(raw: str, option_id: int, source: str) -> None:
        key = normalize_industry(raw)
        if not key:
            raise SystemExit(f"empty key from {raw!r} ({source})")
        if option_id not in labels:
            raise SystemExit(f"unknown pipedrive id {option_id} for {raw!r}")
        previous = mapping.get(key)
        if previous is not None and previous != option_id:
            raise SystemExit(f"collision {raw!r}: {previous} vs {option_id} ({source})")
        mapping[key] = option_id

    for row in load_json("linkedin_industry_v2.json"):
        root = row["root"]
        if root not in by_en:
            raise SystemExit(f"LinkedIn root {root!r} is not a Pipedrive option")
        put(row["name"], by_en[root], "linkedin-v2")

    for row in options:
        put(row["label_en"], row["id"], "pipedrive-en")
        put(row["label_es"], row["id"], "pipedrive-es")

    for key, row in load_json("industry_legacy_aliases.json").items():
        put(key, int(row["id"]), "legacy")

    return mapping, labels


def render_js(mapping: dict[str, int], labels: dict[int, str]) -> str:
    map_json = json.dumps(mapping, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    label_json = json.dumps(
        {str(k): labels[k] for k in sorted(labels)},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"""{START}
const INDUSTRY_TO_PD = {map_json};
const PD_INDUSTRY_LABELS = {label_json};

function normalizeIndustry(value) {{
  return String(value || "")
    .normalize("NFD")
    .replace(/[\\u0300-\\u036f]/g, "")
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[,/]+/g, " ")
    .replace(/[^a-z0-9 ]+/g, " ")
    .replace(/\\s+/g, " ")
    .trim();
}}

function mapIndustry(value) {{
  const raw = String(value || "").trim();
  if (!raw) return {{ id: null, label: null, raw: "", status: "empty" }};
  const id = INDUSTRY_TO_PD[normalizeIndustry(raw)];
  if (!id) return {{ id: null, label: null, raw, status: "unmapped" }};
  return {{ id, label: PD_INDUSTRY_LABELS[String(id)] || null, raw, status: "mapped" }};
}}
{END}
"""


def splice_push(block: str) -> None:
    text = PUSH_JS.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
    if not pattern.search(text):
        raise SystemExit(f"markers missing in {PUSH_JS}")
    updated = pattern.sub(lambda _match: block.strip("\n"), text, count=1)
    if updated == text:
        return
    PUSH_JS.write_text(updated, encoding="utf-8")


def main() -> None:
    mapping, labels = build_map()
    block = render_js(mapping, labels)
    module = block + """
if (typeof module !== "undefined" && module.exports) {
  module.exports = { normalizeIndustry, mapIndustry, INDUSTRY_TO_PD, PD_INDUSTRY_LABELS };
}
"""
    MAP_JS.write_text(module, encoding="utf-8")
    splice_push(block)
    print(f"keys {len(mapping)} options {len(labels)}")


if __name__ == "__main__":
    main()
