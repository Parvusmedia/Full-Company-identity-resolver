"""Normalization helpers for Spanish legal names and LinkedIn URLs."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse, urlunparse

LEGAL_FORMS = [
    r"sociedad\s+de\s+responsabilidad\s+limitada\s+unipersonal",
    r"sociedad\s+de\s+responsabilidad\s+limitada",
    r"sociedad\s+limitada\s+profesional",
    r"sociedad\s+limitada\s+unipersonal",
    r"sociedad\s+limitada\s+laboral",
    r"sociedad\s+anonima\s+laboral",
    r"sociedad\s+anónima\s+laboral",
    r"sociedad\s+anonima",
    r"sociedad\s+anónima",
    r"sociedad\s+cooperativa",
    r"sociedad\s+civil",
    r"sociedad\s+colectiva",
    r"sociedad\s+comanditaria",
    r"comunidad\s+de\s+bienes",
    r"s\.?\s*l\.?\s*u\.?",
    r"s\.?\s*l\.?\s*p\.?",
    r"s\.?\s*l\.?\s*l\.?",
    r"s\.?\s*a\.?\s*u\.?",
    r"s\.?\s*a\.?\s*l\.?",
    r"s\.?\s*coop\.?",
    r"s\.?\s*com\.?",
    r"s\.?\s*c\.?",
    r"s\.?\s*l\.?",
    r"s\.?\s*a\.?",
    r"slu\b",
    r"slp\b",
    r"sll\b",
    r"sau\b",
    r"sal\b",
    r"sl\b",
    r"sa\b",
    r"cb\b",
]

_LEGAL_FORM_RE = re.compile(
    r"(?:,?\s*(?:y\s+)?(?:" + "|".join(LEGAL_FORMS) + r"))+\.?$",
    re.IGNORECASE,
)

_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]+")
_MULTI_SPACE_RE = re.compile(r"\s+")
_LINKEDIN_COMPANY_RE = re.compile(
    r"^(?:[a-z]{2,3}\.)?linkedin\.com$",
    re.IGNORECASE,
)

BRANCH_TERMS = (
    "delegacion",
    "delegación",
    "sucursal",
    "oficina",
    "filial",
    "branch",
    "subsidiary",
    "sede",
)


def strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    text = strip_accents(value).lower().strip()
    text = _NON_ALNUM_RE.sub(" ", text)
    text = _MULTI_SPACE_RE.sub(" ", text).strip()
    return text


def remove_legal_forms(legal_name: str) -> str:
    """Remove Spanish legal-form suffixes from a company name."""
    name = (legal_name or "").strip()
    if not name:
        return ""
    # Normalize fancy dots / spacing around legal forms
    cleaned = re.sub(r"\s+", " ", name)
    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = _LEGAL_FORM_RE.sub("", cleaned).strip(" ,.-")
    return cleaned.strip()


def core_name(legal_name: str) -> str:
    return normalize_text(remove_legal_forms(legal_name))


def slug_from_linkedin_url(url: str) -> str | None:
    normalized = normalize_linkedin_company_url(url)
    if not normalized:
        return None
    path = urlparse(normalized).path.rstrip("/")
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2 and parts[0] == "company":
        return parts[1]
    return None


def is_linkedin_company_url(url: str) -> bool:
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
    except Exception:
        return False
    host = (parsed.netloc or "").lower().removeprefix("www.")
    if not _LINKEDIN_COMPANY_RE.match(host):
        return False
    parts = [p for p in parsed.path.split("/") if p]
    if not parts or parts[0].lower() != "company":
        return False
    if len(parts) < 2:
        return False
    # Reject jobs / posts / people-like paths under company when present as second segment markers
    second = parts[1].lower()
    if second in {"jobs", "posts", "life", "people", "about"}:
        return False
    return True


def should_reject_linkedin_url(url: str) -> bool:
    """Reject personal profiles, jobs, school, pulse, posts, and non-company URLs."""
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
    except Exception:
        return True
    host = (parsed.netloc or "").lower().removeprefix("www.")
    if "linkedin.com" not in host:
        return True
    path = parsed.path.lower()
    rejected_prefixes = (
        "/in/",
        "/pub/",
        "/jobs/",
        "/school/",
        "/showcase/",
        "/posts/",
        "/pulse/",
        "/company-beta/",
        "/sales/",
        "/learning/",
        "/feed/",
    )
    if any(path.startswith(prefix) for prefix in rejected_prefixes):
        return True
    if "/company/" not in path:
        return True
    return not is_linkedin_company_url(url)


def normalize_linkedin_company_url(url: str) -> str | None:
    """Normalize to https://www.linkedin.com/company/<slug>/."""
    if not url:
        return None
    raw = url.strip()
    if should_reject_linkedin_url(raw):
        return None
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    parts = [p for p in parsed.path.split("/") if p]
    # Keep only company/<slug>
    company_idx = next((i for i, p in enumerate(parts) if p.lower() == "company"), None)
    if company_idx is None or company_idx + 1 >= len(parts):
        return None
    slug = parts[company_idx + 1]
    if not slug or slug.lower() in {"jobs", "posts", "life", "people", "about"}:
        return None
    path = f"/company/{slug}/"
    return urlunparse(("https", "www.linkedin.com", path, "", "", ""))


def extract_registrable_domain(url_or_domain: str | None) -> str | None:
    if not url_or_domain:
        return None
    value = url_or_domain.strip()
    if not value:
        return None
    if "://" not in value and "/" not in value and " " not in value:
        host = value.lower().removeprefix("www.")
        return host or None
    try:
        import tldextract

        parsed = urlparse(value if "://" in value else f"https://{value}")
        extracted = tldextract.extract(parsed.netloc or parsed.path)
        if not extracted.domain or not extracted.suffix:
            host = (parsed.netloc or "").lower().removeprefix("www.")
            return host or None
        return f"{extracted.domain}.{extracted.suffix}".lower()
    except Exception:
        parsed = urlparse(value if "://" in value else f"https://{value}")
        host = (parsed.netloc or "").lower().removeprefix("www.")
        return host or None


def contains_branch_terms(*texts: str | None) -> bool:
    blob = normalize_text(" ".join(t for t in texts if t))
    return any(term in blob for term in (normalize_text(t) for t in BRANCH_TERMS))
