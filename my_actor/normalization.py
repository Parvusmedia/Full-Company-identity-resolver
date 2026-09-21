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

# Function words + legal leftovers that must not drive identity.
DISTINCTIVE_STOPWORDS = {
    "de",
    "del",
    "la",
    "las",
    "los",
    "el",
    "y",
    "i",
    "en",
    "para",
    "con",
    "the",
    "and",
    "of",
    "sa",
    "sl",
    "slu",
    "slp",
    "sau",
    "sal",
    "slne",
    "scp",
    "cb",
    "sociedad",
    "anonima",
    "limitada",
    "company",
    "co",
    "inc",
    "llc",
    "ltd",
    "gmbh",
}

GEO_TOKENS = {
    "madrid",
    "barcelona",
    "valencia",
    "sevilla",
    "zaragoza",
    "malaga",
    "bilbao",
    "vigo",
    "aviles",
    "gijon",
    "oviedo",
    "alicante",
    "murcia",
    "granada",
    "cordoba",
    "valladolid",
    "vitoria",
    "pamplona",
    "santander",
    "palma",
    "tenerife",
    "navarra",
    "catalunya",
    "cataluna",
    "galicia",
    "andalucia",
    "asturias",
    "cantabria",
    "extremadura",
    "murcia",
    "canarias",
    "baleares",
    "euskadi",
    "espana",
    "spain",
    "iberia",
    "europa",
    "europe",
    "worldwide",
}

# Sector/generic words that match directories and homonyms (Alimarket, TripAdvisor).
GENERIC_BIZ_TOKENS = {
    "group",
    "grupo",
    "grup",
    "holding",
    "partners",
    "partner",
    "solutions",
    "solution",
    "soluciones",
    "solucion",
    "servicios",
    "servicio",
    "services",
    "consultores",
    "consultoria",
    "asesores",
    "asesoria",
    "gestion",
    "inversiones",
    "seguros",
    "seguro",
    "reaseguros",
    "reaseguro",
    "correduria",
    "corredores",
    "corredor",
    "broker",
    "brokers",
    "asociados",
    "asociadas",
    "media",
    "digital",
    "global",
    "international",
    "internacional",
    "comercial",
    "industrial",
    "proyectos",
    "proyecto",
    "rehabilitaciones",
    "rehabilitacion",
    "tecnologias",
    "tecnologicas",
    "engineering",
    "logistic",
    "logistics",
    "logistica",
    "capital",
    "advanced",
    "center",
    "centre",
    "agencia",
    "vinculada",
    "call",
    "textil",
    "empresa",
    "school",
    "language",
    "turismo",
    "ocio",
    "instalacion",
    "mantenimiento",
    "informacion",
    "redes",
    "entidades",
    "aseguradoras",
    "experimentales",
    "financieros",
    "restauracion",
    "restauraciones",
    "restaurantes",
    "restaurante",
    "talleres",
    "taller",
    "auxiliares",
    "auxiliar",
    "industria",
    "industrias",
    "subcontratacion",
    "transportes",
    "transporte",
    "europeos",
    "europeo",
    "mercados",
    "abastecimientos",
    "publicaciones",
    "translations",
    "translation",
    "linguistic",
    "seguridad",
    "innovacion",
    "formacion",
    "autoescuelas",
    "interiors",
    "interior",
}

# Directories / publishers that must never count as the company website.
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
    "alimarket.es",
    "tripadvisor.com",
    "tripadvisor.es",
    "einforma.com",
    "axesor.es",
    "infocif.es",
    "e-informa.com",
    "rankia.com",
    "paginasamarillas.es",
    "expansion.com",
    "eleconomista.es",
    "elconfidencial.com",
    "lavanguardia.com",
    "elmundo.es",
    "abc.es",
    "elpais.com",
    "idealista.com",
    "infojobs.net",
    "indeed.com",
    "glassdoor.com",
    "emis.com",
    "opencorporates.com",
    "dunandbradstreet.com",
    "hoovers.com",
    "bloomberg.com",
    "ft.com",
    "linkedin.com",
}


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


def contains_branch_terms(*texts: str | None) -> bool:
    blob = normalize_text(" ".join(t for t in texts if t))
    return any(term in blob for term in (normalize_text(t) for t in BRANCH_TERMS))


def is_website_noise_domain(domain: str | None) -> bool:
    host = (domain or "").lower().removeprefix("www.")
    if not host:
        return False
    if host in WEBSITE_NOISE_DOMAINS:
        return True
    return any(host.endswith(f".{noise}") for noise in WEBSITE_NOISE_DOMAINS)


def distinctive_tokens(text: str | None) -> list[str]:
    """Content tokens after stripping legal forms and stopwords."""
    core = core_name(text or "")
    out: list[str] = []
    for token in core.split():
        if token in DISTINCTIVE_STOPWORDS or len(token) < 2:
            continue
        out.append(token)
    return out


def brand_tokens(legal_name: str | None) -> list[str]:
    """Distinctive tokens that are not generic geography or sector words."""
    return [
        token
        for token in distinctive_tokens(legal_name)
        if token not in GEO_TOKENS and token not in GENERIC_BIZ_TOKENS
    ]


def _token_hits_candidate(token: str, cand_tokens: set[str], cand_blob: str) -> bool:
    if token in cand_tokens:
        return True
    compact = cand_blob.replace(" ", "")
    if len(token) >= 4 and token in compact:
        return True
    for cand in cand_tokens:
        if len(token) >= 4 and len(cand) >= 4 and (token in cand or cand in token):
            return True
    return False


def identity_match_tier(legal_name: str, *candidate_texts: str | None) -> str:
    """How strongly candidate strings share identity with the legal name.

    * ``strong`` — enough brand tokens overlap (same entity).
    * ``brand`` — short commercial name / parent page (subset).
    * ``weak`` — geography or sector only, or no overlap (likely wrong).
    """
    cand_blob = normalize_text(" ".join(part for part in candidate_texts if part))
    cand_tokens = set(distinctive_tokens(cand_blob))
    brands = brand_tokens(legal_name)
    if brands:
        hits = [token for token in brands if _token_hits_candidate(token, cand_tokens, cand_blob)]
        if not hits:
            return "weak"
        if len(hits) >= max(1, (len(brands) + 1) // 2):
            return "strong"
        return "brand"

    legal_dist = [token for token in distinctive_tokens(legal_name) if token not in GEO_TOKENS]
    if not legal_dist:
        legal_dist = distinctive_tokens(legal_name)
    overlap = [token for token in legal_dist if _token_hits_candidate(token, cand_tokens, cand_blob)]
    if not overlap:
        return "weak"
    if len(overlap) / max(len(legal_dist), 1) >= 0.5:
        return "strong"
    return "brand"
