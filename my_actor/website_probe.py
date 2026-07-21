"""Cheap homepage fetch to validate website candidates (no paid APIs)."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import httpx
from apify import Actor

from .models import WebsiteCandidate
from .normalization import (
    _ENTITY_QUALIFIER_TOKENS,
    _normalize_qualifier_set,
    core_name,
    distinctive_name_tokens,
    extract_registrable_domain,
    normalize_text,
    text_mentions_company,
    website_path_looks_about,
)


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


class _HomeHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title_parts: list[str] = []
        self.meta_description: str | None = None
        self._in_title = False
        self._in_script = False
        self._in_style = False
        self.body_parts: list[str] = []
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        attr = {k.lower(): (v or "") for k, v in attrs}
        if t == "title":
            self._in_title = True
        elif t in {"script", "style", "noscript"}:
            self._in_script = True
        elif t == "a":
            href = (attr.get("href") or "").strip()
            if href:
                self.hrefs.append(href)
        elif t == "meta":
            name = (attr.get("name") or attr.get("property") or "").lower()
            if name in {"description", "og:description", "twitter:description"}:
                content = attr.get("content") or ""
                if content and not self.meta_description:
                    self.meta_description = content
            # Some sites put social URLs in og tags
            if name in {"og:see_also", "al:android:url"} and "linkedin.com" in (attr.get("content") or "").lower():
                self.hrefs.append(attr.get("content") or "")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t == "title":
            self._in_title = False
        elif t in {"script", "style", "noscript"}:
            self._in_script = False

    def handle_data(self, data: str) -> None:
        if self._in_script:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        else:
            self.body_parts.append(text)


@dataclass
class HomepageProbe:
    url: str
    final_url: str | None = None
    title: str | None = None
    meta_description: str | None = None
    text_sample: str | None = None
    linkedin_urls: list[str] | None = None
    ok: bool = False
    error: str | None = None
    score_delta: float = 0.0
    reasons: list[str] | None = None
    reject: bool = False


_LINKEDIN_HREF_RE = re.compile(
    r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/[^\s\"'<>]+",
    re.IGNORECASE,
)


def extract_linkedin_company_urls_from_html(html: str) -> list[str]:
    """Return unique normalized LinkedIn /company/ URLs found in page HTML."""
    from .normalization import normalize_linkedin_company_url

    if not html:
        return []
    found: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        normalized = normalize_linkedin_company_url(raw)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        found.append(normalized)

    parser = _HomeHTMLParser()
    try:
        parser.feed(html)
        parser.close()
        for href in parser.hrefs:
            if "linkedin.com" in href.lower():
                _add(href)
    except Exception:
        pass
    # Regex fallback for JSON-LD / inline scripts the tag parser skips
    for match in _LINKEDIN_HREF_RE.findall(html):
        if "/company/" in match.lower():
            _add(match)
    return found


def parse_homepage_html(html: str) -> tuple[str | None, str | None, str, list[str]]:
    parser = _HomeHTMLParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        title = None
        text = _WS_RE.sub(" ", _TAG_RE.sub(" ", html))[:4000]
        return title, None, text, extract_linkedin_company_urls_from_html(html)
    title = _WS_RE.sub(" ", " ".join(parser.title_parts)).strip() or None
    meta = parser.meta_description
    body = _WS_RE.sub(" ", " ".join(parser.body_parts)).strip()
    linkedin_urls = extract_linkedin_company_urls_from_html(html)
    return title, meta, body[:5000], linkedin_urls


def evaluate_homepage_probe(legal_name: str, probe: HomepageProbe) -> HomepageProbe:
    """Score/reject a fetched homepage against the legal name."""
    reasons: list[str] = []
    delta = 0.0
    reject = False

    if not probe.ok:
        reasons.append(f"homepage_fetch_failed:{probe.error or 'unknown'}")
        probe.score_delta = -3.0
        probe.reasons = reasons
        probe.reject = False  # soft: network failures should not discard alone
        return probe

    core = core_name(legal_name)
    tokens = distinctive_name_tokens(legal_name)
    blob = normalize_text(
        " ".join(x for x in (probe.title, probe.meta_description, probe.text_sample) if x)
    )
    title_n = normalize_text(probe.title or "")
    legal_tokens = set(core.split())
    wants_local = bool(_normalize_qualifier_set(legal_tokens & _ENTITY_QUALIFIER_TOKENS))

    title_hit = text_mentions_company(probe.title or "", legal_name)
    body_hit = text_mentions_company(
        f"{probe.meta_description or ''} {(probe.text_sample or '')[:1500]}",
        legal_name,
    )
    token_hits = sum(1 for t in tokens if t in blob) if tokens else 0

    if title_hit:
        delta += 18.0
        reasons.append("homepage_title_mentions_company")
    if body_hit:
        delta += 10.0
        reasons.append("homepage_body_mentions_company")
    if token_hits:
        delta += min(12.0, token_hits * 4.0)
        reasons.append(f"homepage_token_hits={token_hits}")

    # Local legal entities should not resolve to a generic global brand homepage
    # that never mentions the local qualifier (iberica / espana / …).
    if wants_local:
        quals = _normalize_qualifier_set(legal_tokens & _ENTITY_QUALIFIER_TOKENS)
        qual_hit = any(q in blob for q in quals)
        host = (urlparse(probe.final_url or probe.url).netloc or "").lower().removeprefix("www.")
        apex = extract_registrable_domain(host) or host
        is_apex_host = host == apex
        if not qual_hit and is_apex_host and not host.endswith(".es"):
            delta -= 25.0
            reject = True
            reasons.append("homepage_global_without_local_qualifier")
        elif qual_hit:
            delta += 8.0
            reasons.append("homepage_local_qualifier_present")
        elif not is_apex_host:
            # Country/service subdomain kept — weaker positive if brand tokens present
            if token_hits:
                delta += 4.0
                reasons.append("homepage_meaningful_subdomain")

    # Empty/near-empty shells are weak evidence
    if len(blob) < 40:
        delta -= 8.0
        reasons.append("homepage_too_little_text")

    # Strong negative: page has none of the distinctive tokens at all
    if tokens and token_hits == 0 and not title_hit:
        delta -= 20.0
        reasons.append("homepage_no_company_tokens")
        # Reject only when we expected a clear owned site signal
        if wants_local or len(tokens) >= 1:
            reject = True

    probe.score_delta = delta
    probe.reasons = reasons
    probe.reject = reject
    return probe


async def fetch_homepage(url: str, *, timeout: float = 12.0) -> HomepageProbe:
    probe = HomepageProbe(url=url)
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; FullCompanyIdentityResolver/0.1; "
                    "+https://apify.com)"
                ),
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "es-ES,es;q=0.9,en;q=0.5",
            },
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            ctype = (response.headers.get("content-type") or "").lower()
            if "html" not in ctype and "text/" not in ctype and ctype:
                probe.error = f"non_html:{ctype.split(';')[0]}"
                return probe
            html = response.text or ""
            title, meta, text, linkedin_urls = parse_homepage_html(html)
            probe.final_url = str(response.url)
            probe.title = title
            probe.meta_description = meta
            probe.text_sample = text
            probe.linkedin_urls = linkedin_urls
            probe.ok = True
            return probe
    except Exception as exc:  # noqa: BLE001
        probe.error = type(exc).__name__
        return probe


async def discover_linkedin_from_website(url: str) -> list[str]:
    """Fetch a website homepage and return LinkedIn /company/ URLs found on it."""
    probe = await fetch_homepage(url)
    return list(probe.linkedin_urls or [])


async def validate_website_candidates(
    legal_name: str,
    candidates: list[WebsiteCandidate],
    *,
    max_probes: int = 3,
    concurrency: int = 3,
) -> list[WebsiteCandidate]:
    """Fetch top homepage candidates and re-rank / drop mismatches.

    Cost: one HTTP GET per probed URL (no Google/Harvest spend).
    """
    if not candidates or max_probes <= 0:
        return candidates

    to_probe = candidates[: max(1, max_probes)]
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _one(cand: WebsiteCandidate) -> tuple[WebsiteCandidate, HomepageProbe]:
        async with sem:
            probe = await fetch_homepage(cand.url)
            probe = evaluate_homepage_probe(legal_name, probe)
            return cand, probe

    Actor.log.info(
        "Probing %s website homepages for %s",
        len(to_probe),
        core_name(legal_name) or legal_name,
    )
    pairs = await asyncio.gather(*[_one(c) for c in to_probe])

    kept: list[WebsiteCandidate] = []
    probed_urls = {c.url for c, _ in pairs}
    for cand, probe in pairs:
        reasons = list(probe.reasons or [])
        new_score = cand.score + probe.score_delta
        prior_probe = cand.homepage_probe if isinstance(cand.homepage_probe, dict) else {}
        ai_backed = bool(prior_probe.get("ai_overview_backed"))
        about_backed = any(
            text_mentions_company(ev.snippet or "", legal_name)
            and (
                website_path_looks_about(ev.url)
                or any(
                    t in (ev.title or "").casefold()
                    for t in ("quiénes somos", "quienes somos", "about us", "sobre nosotros")
                )
            )
            for ev in cand.google_evidences
        )
        probe_dump = {
            **prior_probe,
            "ok": probe.ok,
            "final_url": probe.final_url,
            "title": probe.title,
            "score_delta": probe.score_delta,
            "reasons": reasons,
            "reject": probe.reject,
            "error": probe.error,
            "linkedin_urls": list(probe.linkedin_urls or []),
        }
        updated = cand.model_copy(
            update={
                "score": new_score,
                "homepage_probe": probe_dump,
            }
        )
        # AI Overview already corroborated the company↔URL link; do not discard
        # solely because the homepage lacks brand tokens (e.g. WTW Spain portal).
        # Same for Google about-pages whose SERP snippet self-identifies the firm.
        if probe.reject and not ai_backed and not about_backed:
            Actor.log.info(
                "Rejecting website %s after homepage probe (%s)",
                cand.url,
                "; ".join(reasons[:4]),
            )
            continue
        if probe.reject and (ai_backed or about_backed):
            Actor.log.info(
                "Keeping %s-backed website %s despite probe reject (%s)",
                "AI Overview" if ai_backed else "about-page",
                cand.url,
                "; ".join(reasons[:4]),
            )
            probe_dump["reject_overridden_by_ai_overview" if ai_backed else "reject_overridden_by_about_page"] = True
        kept.append(updated)

    # Append non-probed tail unchanged (lower ranked)
    for cand in candidates:
        if cand.url not in probed_urls:
            kept.append(cand)

    kept.sort(key=lambda c: c.score, reverse=True)
    return kept
