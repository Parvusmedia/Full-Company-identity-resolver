"""HarvestAPI LinkedIn company client."""

from __future__ import annotations

import ast
import asyncio
import json
from typing import Any

import httpx
from apify import Actor

HARVEST_COMPANY_URL = "https://api.harvest-api.com/linkedin/company"


class HarvestClient:
    def __init__(self, api_key: str, *, concurrency: int = 3, timeout: float = 45.0) -> None:
        self._api_key = api_key
        self._semaphore = asyncio.Semaphore(max(1, concurrency))
        self._timeout = timeout

    async def get_company(
        self,
        *,
        url: str | None = None,
        universal_name: str | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        if not any([url, universal_name, search]):
            raise ValueError("Harvest get_company requires url, universalName or search")

        params: dict[str, str] = {}
        if url:
            params["url"] = url
        if universal_name:
            params["universalName"] = universal_name
        if search:
            params["search"] = search

        headers = {"X-API-Key": self._api_key}

        async with self._semaphore:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(HARVEST_COMPANY_URL, params=params, headers=headers)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Unexpected Harvest response type")
                return payload

    async def get_company_element(
        self,
        *,
        url: str | None = None,
        universal_name: str | None = None,
        search: str | None = None,
    ) -> dict[str, Any] | None:
        payload = await self.get_company(url=url, universal_name=universal_name, search=search)
        element = payload.get("element")
        if isinstance(element, dict):
            return element
        # Some responses may return the company object at top-level
        if "universalName" in payload or "linkedinUrl" in payload or "name" in payload:
            return payload
        return None


async def enrich_candidates_with_harvest(
    urls: list[str],
    *,
    api_key: str | None,
    concurrency: int = 3,
) -> dict[str, dict[str, Any]]:
    """Fetch Harvest data for LinkedIn URLs. Returns map url -> {element, raw, error}."""
    results: dict[str, dict[str, Any]] = {}
    if not urls:
        return results
    if not api_key:
        Actor.log.warning("No HARVEST_API_KEY available; skipping Harvest enrichment.")
        for url in urls:
            results[url] = {"element": None, "raw": None, "error": "missing_harvest_api_key"}
        return results

    client = HarvestClient(api_key, concurrency=concurrency)

    async def _one(url: str) -> None:
        try:
            raw = await client.get_company(url=url)
            element = raw.get("element") if isinstance(raw.get("element"), dict) else None
            if element is None and isinstance(raw, dict) and ("name" in raw or "universalName" in raw):
                element = raw
            results[url] = {"element": element, "raw": raw, "error": None}
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            Actor.log.warning("Harvest HTTP error for company URL (status=%s)", status)
            results[url] = {
                "element": None,
                "raw": None,
                "error": f"http_{status}",
            }
        except Exception as exc:  # noqa: BLE001
            Actor.log.warning("Harvest enrichment failed: %s", type(exc).__name__)
            results[url] = {"element": None, "raw": None, "error": type(exc).__name__}

    await asyncio.gather(*[_one(url) for url in urls])
    return results


def harvest_phone(element: dict[str, Any] | None) -> str | None:
    if not element:
        return None
    phone = element.get("phone")
    if isinstance(phone, str):
        return phone.strip() or None
    if isinstance(phone, dict):
        number = phone.get("number") or phone.get("phoneNumber") or phone.get("value")
        extension = phone.get("extension")
        if number and extension:
            return f"{number} ext. {extension}"
        return str(number).strip() if number else None
    if isinstance(phone, list) and phone:
        return harvest_phone({"phone": phone[0]})
    return None


def harvest_logo_url(element: dict[str, Any] | None) -> str | None:
    if not element:
        return None
    logo = element.get("logo")
    if isinstance(logo, str):
        return logo
    if isinstance(logo, dict):
        return logo.get("url") or logo.get("rootUrl")
    logos = element.get("logos")
    if isinstance(logos, list) and logos:
        first = logos[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            return first.get("url") or first.get("rootUrl")
    return None


def harvest_employee_range(element: dict[str, Any] | None) -> tuple[str | None, int | None, int | None]:
    if not element:
        return None, None, None
    rng = element.get("employeeCountRange")
    if isinstance(rng, str):
        start, end = _parse_range_string(rng)
        return rng, start, end
    if isinstance(rng, dict):
        start = rng.get("start")
        end = rng.get("end")
        try:
            start_i = int(start) if start is not None else None
        except (TypeError, ValueError):
            start_i = None
        try:
            end_i = int(end) if end is not None else None
        except (TypeError, ValueError):
            end_i = None
        label = None
        if start_i is not None and end_i is not None:
            label = f"{start_i}-{end_i}"
        elif start_i is not None:
            label = f"{start_i}+"
        return label, start_i, end_i
    return None, None, None


def _parse_range_string(value: str) -> tuple[int | None, int | None]:
    text = value.replace(",", "").strip()
    if "-" in text:
        left, right = text.split("-", 1)
        try:
            return int(left.strip()), int(right.strip())
        except ValueError:
            return None, None
    if text.endswith("+"):
        try:
            return int(text[:-1].strip()), None
        except ValueError:
            return None, None
    try:
        n = int(text)
        return n, n
    except ValueError:
        return None, None


def harvest_headquarters_fields(element: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "headquarters": None,
        "headquarters_text": None,
        "headquarters_city": None,
        "headquarters_region": None,
        "headquarters_country": None,
    }
    if not element:
        return out
    hq = element.get("headquarter") or element.get("headquarters")
    out["headquarters"] = hq
    if isinstance(hq, dict):
        city = hq.get("city")
        region = hq.get("geographicArea") or hq.get("region") or hq.get("state")
        country = hq.get("country")
        line = hq.get("line1") or hq.get("address") or hq.get("description")
        parts = [p for p in [line, city, region, country] if p]
        out["headquarters_city"] = city
        out["headquarters_region"] = region
        out["headquarters_country"] = country
        out["headquarters_text"] = ", ".join(str(p) for p in parts) if parts else None
    elif isinstance(hq, str):
        out["headquarters_text"] = hq
    return out


def industry_name_from_value(value: Any) -> str | None:
    """Return a plain industry name from Harvest dicts, JSON, or Python repr strings."""
    if value is None:
        return None
    if isinstance(value, dict):
        name = (
            value.get("name")
            or value.get("localizedName")
            or value.get("title")
            or value.get("label")
        )
        if name is None:
            return None
        text = str(name).strip()
        return text or None
    if isinstance(value, (list, tuple)):
        for item in value:
            name = industry_name_from_value(item)
            if name:
                return name
        return None
    if not isinstance(value, str):
        return industry_name_from_value(str(value))

    text = value.strip()
    if not text:
        return None

    # Recover names from accidental str(dict) / JSON blobs written to NocoDB.
    if text[0] in "{[" and ("'name'" in text or '"name"' in text or "localizedName" in text):
        parsed: Any = None
        try:
            parsed = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            try:
                parsed = json.loads(text)
            except (TypeError, ValueError, json.JSONDecodeError):
                parsed = None
        if parsed is not None:
            name = industry_name_from_value(parsed)
            if name:
                return name

    # Plain name (reject leftover object-looking strings).
    if text.startswith("{") and ("'id'" in text or '"id"' in text or "urn:li:" in text):
        return None
    return text


def harvest_industry(element: dict[str, Any] | None) -> tuple[str | None, list[str] | None]:
    """Extract industry as plain name(s) only — never raw Harvest industry objects."""
    if not element:
        return None, None

    names: list[str] = []
    industries = element.get("industries")
    if isinstance(industries, list) and industries:
        for item in industries:
            name = industry_name_from_value(item)
            if name and name not in names:
                names.append(name)
    if not names:
        name = industry_name_from_value(element.get("industry"))
        if name:
            names.append(name)
    if not names:
        return None, None
    return names[0], names


def harvest_founded_year(element: dict[str, Any] | None) -> int | None:
    if not element:
        return None
    founded = element.get("foundedOn") or element.get("founded")
    if isinstance(founded, int):
        return founded
    if isinstance(founded, dict):
        year = founded.get("year")
        try:
            return int(year) if year is not None else None
        except (TypeError, ValueError):
            return None
    if isinstance(founded, str) and founded[:4].isdigit():
        return int(founded[:4])
    return None
