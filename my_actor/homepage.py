"""Extract LinkedIn company URLs from a company website homepage."""

from __future__ import annotations

import html as html_lib
import re
from urllib.parse import urlparse

import httpx
from apify import Actor

from .normalization import is_website_noise_domain, normalize_linkedin_company_url

HOMEPAGE_QUERY = "homepage"
MAX_HTML_CHARS = 1_000_000
MAX_URLS_PER_PAGE = 5
FETCH_TIMEOUT = 15.0

# Protocol-optional linkedin.com/company/<slug> (href, JSON-LD sameAs, footer text).
_LINKEDIN_COMPANY_RE = re.compile(
    r"(?:https?://|//)?(?:(?:www|[a-z]{2,3})\.)?linkedin\.com/company/([^\s\"'<>\\]+)",
    re.IGNORECASE,
)

_USER_AGENT = (
    "Mozilla/5.0 (compatible; FullCompanyIdentityResolver/0.1; "
    "+https://github.com/Parvusmedia/Full-Company-identity-resolver)"
)


def candidate_page_urls(url: str) -> list[str]:
    """The given URL plus the site origin, so a deep page still yields the footer homepage."""
    raw = (url or "").strip()
    if not raw:
        return []
    if "://" not in raw:
        raw = f"https://{raw}"
    try:
        parsed = urlparse(raw)
    except Exception:
        return [raw]
    host = (parsed.netloc or "").strip()
    if not host:
        return [raw]
    scheme = parsed.scheme or "https"
    origin = f"{scheme}://{host}/"
    out: list[str] = []
    for item in (raw, origin):
        if item.rstrip("/") not in {u.rstrip("/") for u in out}:
            out.append(item)
    return out[:2]


def extract_linkedin_company_urls(html: str) -> list[str]:
    """Return unique normalized LinkedIn company URLs found in HTML / JSON-LD / footers."""
    if not html:
        return []
    text = html_lib.unescape(html[:MAX_HTML_CHARS])
    found: list[str] = []
    seen: set[str] = set()
    for match in _LINKEDIN_COMPANY_RE.finditer(text):
        slug_and_rest = match.group(1) or ""
        slug = slug_and_rest.split("/")[0].split("?")[0].split("#")[0].rstrip(".,);")
        if not slug:
            continue
        raw_url = f"https://www.linkedin.com/company/{slug}/"
        normalized = normalize_linkedin_company_url(raw_url)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        found.append(normalized)
        if len(found) >= MAX_URLS_PER_PAGE:
            break
    return found


async def scrape_homepage_linkedin_urls(url: str, *, timeout: float = FETCH_TIMEOUT) -> list[str]:
    """GET a website (and its origin) and collect LinkedIn company URLs."""
    pages = candidate_page_urls(url)
    collected: list[str] = []
    seen: set[str] = set()
    if not pages:
        return collected

    headers = {"User-Agent": _USER_AGENT, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"}
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers=headers,
            max_redirects=5,
        ) as client:
            for page in pages:
                host = (urlparse(page).netloc or "").lower().removeprefix("www.")
                if is_website_noise_domain(host):
                    continue
                try:
                    response = await client.get(page)
                except Exception as exc:  # noqa: BLE001
                    Actor.log.info(
                        "Homepage fetch failed (%s): %s",
                        type(exc).__name__,
                        host,
                    )
                    continue
                content_type = (response.headers.get("content-type") or "").lower()
                if content_type and not any(
                    token in content_type for token in ("html", "xml", "text/", "json", "javascript")
                ):
                    continue
                if response.status_code >= 400:
                    Actor.log.info("Homepage HTTP %s for %s", response.status_code, host)
                    continue
                html = (response.text or "")[:MAX_HTML_CHARS]
                for linkedin_url in extract_linkedin_company_urls(html):
                    if linkedin_url not in seen:
                        seen.add(linkedin_url)
                        collected.append(linkedin_url)
    except Exception as exc:  # noqa: BLE001
        Actor.log.info("Homepage scrape aborted: %s", type(exc).__name__)
    return collected
