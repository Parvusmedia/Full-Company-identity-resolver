"""Normalization helpers for Spanish legal names and LinkedIn URLs."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import unquote, urlparse, urlunparse

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
    r"\bs\.?\s*l\.?\s*u\.?\b",
    r"\bs\.?\s*l\.?\s*p\.?\b",
    r"\bs\.?\s*l\.?\s*l\.?\b",
    r"\bs\.?\s*a\.?\s*u\.?\b",
    r"\bs\.?\s*a\.?\s*l\.?\b",
    r"\bs\.?\s*coop\.?\b",
    r"\bs\.?\s*com\.?\b",
    r"\bs\.?\s*c\.?\b",
    r"\bs\.?\s*l\.?\b",
    r"\bs\.?\s*a\.?\b",
    r"\bslu\b",
    r"\bslp\b",
    r"\bsll\b",
    r"\bsau\b",
    r"\bsal\b",
    r"\bsl\b",
    r"\bsa\b",
    r"\bcb\b",
]

_LEGAL_FORM_RE = re.compile(
    # Require a separator so we never strip letters from words like "Empresa".
    r"(?:(?:\s+|,)\s*(?:y\s+)?(?:" + "|".join(LEGAL_FORMS) + r"))+\.?$",
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


def _linkedin_host_ok(host: str) -> bool:
    host = (host or "").lower().removeprefix("www.")
    return bool(_LINKEDIN_COMPANY_RE.match(host)) or host.endswith("linkedin.com")


def company_url_from_linkedin_post(url: str) -> str | None:
    """Derive /company/<slug>/ from a LinkedIn post authored by a company page."""
    if not url:
        return None
    try:
        parsed = urlparse(unquote(url.strip()) if "://" in url else f"https://{unquote(url.strip())}")
    except Exception:
        return None
    if not _linkedin_host_ok(parsed.netloc):
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2 or parts[0].lower() != "posts":
        return None
    # posts/<company-or-person-slug>_activity-...
    raw_slug = parts[1]
    slug = raw_slug.split("_", 1)[0].strip()
    if not slug or len(slug) < 2:
        return None
    # Person posts often look similar; keep slug and let scoring/Harvest decide.
    return urlunparse(("https", "www.linkedin.com", f"/company/{slug}/", "", "", ""))


def normalize_linkedin_company_url(url: str) -> str | None:
    """Normalize to https://www.linkedin.com/company/<slug>/."""
    if not url:
        return None
    raw = unquote(url.strip())
    # Allow deriving a company URL from a company-authored post.
    if "/posts/" in raw.lower():
        derived = company_url_from_linkedin_post(raw)
        if derived:
            return derived
    if should_reject_linkedin_url(raw):
        return None
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    parts = [p for p in parsed.path.split("/") if p]
    # Keep only company/<slug>
    company_idx = next((i for i, p in enumerate(parts) if p.lower() == "company"), None)
    if company_idx is None or company_idx + 1 >= len(parts):
        return None
    slug = unquote(parts[company_idx + 1])
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


# Company registries, directories, official gazettes, social, etc. — never official websites.
WEBSITE_NOISE_DOMAINS = {
    "zoominfo.com",
    "coursehero.com",
    "facebook.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "youtube.com",
    "wikipedia.org",
    "crunchbase.com",
    "bloomberg.com",
    "yumpu.com",
    "slideshare.net",
    "scribd.com",
    "emis.com",
    "dnb.com",
    "infoempresa.com",
    "eleconomista.es",
    "empresite.eleconomista.es",
    "northdata.com",
    "northdata.de",
    "econodata.com.br",
    "boe.es",
    "borme.es",
    "axesor.es",
    "einforma.com",
    "informa.es",
    "expansion.com",
    "rankia.com",
    "emis.com",
    "opencorporates.com",
    "companieshouse.gov.uk",
    "datocapital.com",
    "empresia.es",
    "infocif.es",
    "librecon.es",
    "paginasamarillas.es",
    "yellowpages.com",
    "yelp.com",
    "glassdoor.com",
    "indeed.com",
    "talent.com",
    "rocketreach.co",
    "apollo.io",
    "lusha.com",
    "kompass.com",
    "europages.es",
    "europages.com",
    "google.com",
    "google.es",
    "bing.com",
    "realmadrid.com",
    "muysegura.com",
    "linkedin.com",
}

_WEAK_PATH_MARKERS = (
    "/aviso-legal",
    "/politica-de-privacidad",
    "/privacy",
    "/cookies",
    "/contacto",
    "/contact",
    "/quienes-somos",
    "/nosotros",
    "/about",
    "/blog/",
    "/noticias/",
    "/news/",
    "/press/",
    "/landing/",
    "/diario_borme",
    "/borme",
    "/pdfs/",
)


def domain_label(domain: str | None) -> str:
    if not domain:
        return ""
    return domain.split(".")[0].lower()


_WEAK_NAME_TOKENS = frozenset(
    {
        "grupo",
        "group",
        "holding",
        "company",
        "companies",
        "corp",
        "corporation",
        "iberica",
        "iberia",
        "espana",
        "spain",
        "europe",
        "europa",
        "international",
        "internacional",
        "global",
        "services",
        "servicios",
        "seguros",
        "insurance",
        "broker",
        "correduria",
        "reaseguros",
        "consultores",
        "partners",
        "media",
        "mediacion",
    }
)


def distinctive_name_tokens(legal_or_core: str) -> list[str]:
    """Tokens useful to confirm a page refers to this company (drop weak geographic/legal words)."""
    core = core_name(legal_or_core) if legal_or_core else ""
    out: list[str] = []
    for token in core.split():
        if len(token) < 4:
            continue
        if token in _WEAK_NAME_TOKENS:
            continue
        out.append(token)
    return out


def text_mentions_company(text: str | None, legal_name: str, *, min_hits: int = 1) -> bool:
    """True when title/snippet contains distinctive tokens from the legal name."""
    blob = normalize_text(text or "")
    if not blob:
        return False
    tokens = distinctive_name_tokens(legal_name)
    if not tokens:
        # Fallback: whole core must appear loosely
        core = core_name(legal_name)
        return bool(core) and core in blob
    hits = sum(1 for t in tokens if t in blob)
    return hits >= min(min_hits, len(tokens))


def is_noise_website_domain(domain: str | None) -> bool:
    if not domain:
        return True
    d = domain.lower().removeprefix("www.")
    if d in WEBSITE_NOISE_DOMAINS:
        return True
    return any(d.endswith(f".{noise}") or d == noise for noise in WEBSITE_NOISE_DOMAINS)


def normalize_homepage_url(url: str | None) -> str | None:
    """Return scheme+host homepage only (no path/query/fragment)."""
    if not url:
        return None
    raw = url.strip()
    if not raw:
        return None
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.netloc or "").lower()
    if not host:
        return None
    # Drop credentials/ports noise except keep non-default ports rarely needed
    host = host.split("@")[-1]
    scheme = "https"
    return urlunparse((scheme, host, "/", "", "", ""))


def website_path_looks_editorial(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url if "://" in url else f"https://{url}")
    path = (parsed.path or "").lower()
    if path.endswith(".pdf"):
        return True
    return any(marker in path for marker in _WEAK_PATH_MARKERS)


def select_official_website(
    *,
    legal_name: str,
    harvest_website: str | None,
    google_website: str | None,
    google_domain: str | None,
    google_content_backed: bool = False,
    min_domain_similarity: float = 55.0,
) -> tuple[str | None, str | None, str | None, str | None]:
    """
    Choose a clean official homepage.

    Returns (website, domain, google_website_clean, harvest_website_clean).
    Prefers Harvest when its domain resembles the company. Google results that
    already passed ranking (including brand/group pages whose domain differs
    from the legal name, e.g. Verspieren → alkora.es) are kept when
    ``google_content_backed`` is True or domain similarity is high enough.
    """
    from rapidfuzz import fuzz

    core = core_name(legal_name)

    def _sim(domain: str | None) -> float:
        label = domain_label(domain)
        if not label or not core:
            return 0.0
        return float(fuzz.token_set_ratio(core, normalize_text(label)))

    harvest_clean = None
    harvest_dom = extract_registrable_domain(harvest_website)
    harvest_sim = 0.0
    if harvest_website and harvest_dom and not is_noise_website_domain(harvest_dom):
        harvest_clean = normalize_homepage_url(harvest_website)
        harvest_sim = _sim(harvest_dom)

    google_clean = None
    google_dom = google_domain or extract_registrable_domain(google_website)
    google_sim = 0.0
    if google_website and google_dom and not is_noise_website_domain(google_dom):
        google_sim = _sim(google_dom)
        # Content-backed Google candidates (title/snippet mention the company) may
        # use a commercial brand domain that does not resemble the legal name.
        if google_content_backed or google_sim >= min_domain_similarity:
            google_clean = normalize_homepage_url(google_website)
        else:
            google_dom = None

    # Prefer Harvest when domain resembles the company; never keep a mismatched Harvest site
    # just because Google had nothing useful (avoids assigning another firm's homepage).
    if harvest_clean and harvest_sim >= 40:
        return harvest_clean, harvest_dom, google_clean, harvest_clean
    if google_clean and (google_sim > harvest_sim or google_content_backed):
        return google_clean, google_dom, google_clean, harvest_clean
    if harvest_clean and harvest_sim >= 35:
        return harvest_clean, harvest_dom, google_clean, harvest_clean
    if google_clean:
        return google_clean, google_dom, google_clean, harvest_clean
    return None, None, None, harvest_clean


def contains_branch_terms(*texts: str | None) -> bool:
    blob = normalize_text(" ".join(t for t in texts if t))
    return any(term in blob for term in (normalize_text(t) for t in BRANCH_TERMS))
