"""Normalization helpers for Spanish legal names and LinkedIn URLs."""

from __future__ import annotations

import re
import unicodedata
from typing import Any
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

# Detect Spanish sociedad forms even mid/end (S.L., S.A.U., SL, …).
_SPANISH_LEGAL_FORM_HINT_RE = re.compile(
    r"\b(?:s\.?\s*l\.?\s*[upl]?\.?|s\.?\s*a\.?\s*[ul]?\.?|slu|slp|sll|sau|sal|sl|sa)\b",
    re.IGNORECASE,
)


def has_spanish_legal_form(legal_name: str) -> bool:
    return bool(_SPANISH_LEGAL_FORM_HINT_RE.search(legal_name or ""))

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
    """Derive /company/<slug>/ from a LinkedIn post URL.

    Disabled by default for identity resolution: person posts use the same
    ``/posts/<slug>_activity-...`` shape and would invent fake company pages.
    Callers that already verified the slug as a company may use this helper.
    """
    return None


def normalize_linkedin_company_url(url: str) -> str | None:
    """Normalize to https://www.linkedin.com/company/<slug>/."""
    import unicodedata
    from urllib.parse import quote

    if not url:
        return None
    raw = unquote(url.strip())
    # Do not invent company pages from /posts/ (person posts look identical).
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
    # Prefer ASCII slug (LinkedIn canonical); keep unicode if no ASCII fold.
    folded = unicodedata.normalize("NFKD", slug)
    ascii_slug = "".join(c for c in folded if not unicodedata.combining(c))
    if ascii_slug and all(ord(c) < 128 for c in ascii_slug):
        slug = ascii_slug
    path = f"/company/{slug}/"
    return urlunparse(("https", "www.linkedin.com", path, "", "", ""))


def extract_registrable_domain(url_or_domain: str | None) -> str | None:
    if not url_or_domain:
        return None
    value = url_or_domain.strip()
    if not value:
        return None
    try:
        import tldextract

        if "://" in value:
            parsed = urlparse(value)
            host = parsed.netloc or parsed.path
        else:
            host = value.split("/")[0]
        host = (host or "").lower().removeprefix("www.").split("@")[-1]
        if ":" in host:
            name, _, port = host.rpartition(":")
            if port.isdigit():
                host = name
        extracted = tldextract.extract(host)
        if extracted.domain and extracted.suffix:
            return f"{extracted.domain}.{extracted.suffix}".lower()
        return host or None
    except Exception:
        parsed = urlparse(value if "://" in value else f"https://{value}")
        host = (parsed.netloc or "").lower().removeprefix("www.")
        return host or None


# Company registries, directories, official gazettes, social, etc. — never official websites.
WEBSITE_NOISE_DOMAINS = {
    "zoominfo.com",
    "coursehero.com",
    "instagram.com",
    "facebook.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "tiktok.com",
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
    "infojobs.net",
    "infojobs.es",
    "indeed.com",
    "lasprovincias.es",
    "elmundo.es",
    "elpais.com",
    "abc.es",
    "lavanguardia.com",
    "20minutos.es",
    "idealista.com",
    "emis.com",
    "opencorporates.com",
    "companieshouse.gov.uk",
    "datocapital.com",
    "empresia.es",
    "infocif.es",
    "datoscif.es",
    "datosif.es",
    "e-informa.com",
    "einforma.com",
    "economia3.com",
    "empresite.com",
    "rankia.com",
    "expansion.com",
    "cincodias.com",
    "dirce.es",
    "axesor.es",
    "iberinform.es",
    "creditsafe.com",
    "creditsafe.es",
    "solunion.es",
    "cesce.es",
    "companywall.es",
    "borrmat.com",
    "corredurias.org",
    "opendi.es",
    "conductordeprimera.com",
    "apiempresas.es",
    "apiempresas.com",
    "einforma.com",
    "guiaempresas.wolterskluwer.es",
    "wolterskluwer.es",
    "sabi.bvdinfo.com",
    "bvdinfo.com",
    "orbis.bvdinfo.com",
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
    "elespanol.com",
    "elconfidencial.com",
    "larazon.es",
    "abc.es",
    "elmundo.es",
    "elpais.com",
    "cincodias.elpais.com",
    "expansion.com",
    "europapress.es",
    "20minutos.es",
    "lavanguardia.com",
    "eldiario.es",
    "okdiario.com",
    "vozpopuli.com",
    "negocios.com",
    "invertia.com",
    "bolsamania.com",
    "estrategiasdeinversion.com",
    "media-marketing.es",
    "adnkronos.com",
    "reuters.com",
    "bloomberg.com",
    "ft.com",
    "wsj.com",
    "forbes.com",
    "businessinsider.com",
    "medium.com",
    "substack.com",
    # Public investment / startup directories — not company homepages.
    "catalonia.com",
    "startupshub.catalonia.com",
    "accio.gencat.cat",
    "gencat.cat",
    "icex.es",
    "investinspain.org",
    # Local business directories / lead platforms / NGO lookalikes.
    "qdq.com",
    "qdq.es",
    "f6s.com",
    "ilo.org",
    "agentsync.io",
    "intelectium.com",
    "merited.com.mx",
    "merited.com",
    "paginasamarillas.es",
    "yellowpages.com",
    "yelp.com",
}

_WEAK_PATH_MARKERS = (
    "/politica-de-privacidad",
    "/privacy",
    "/cookies",
    "/contacto",
    "/contact",
    # Note: /quienes-somos, /nosotros, /about, /aviso-legal are intentional
    # identity pages (official self-description), not rejectable editorial paths.
    "/blog/",
    "/noticias/",
    "/news/",
    "/press/",
    "/landing/",
    "/diario_borme",
    "/borme",
    "/pdfs/",
    "/catalogo-entidades",
    "/catalogo/",
)

_ABOUT_PATH_MARKERS = (
    "/quienes-somos",
    "/quien-somos",
    "/nosotros",
    "/about",
    "/about-us",
    "/sobre-nosotros",
    "/empresa",
)

# Legal-notice pages often name the razón social (Weecover aviso-legal) but are
# weaker than true about pages and can appear on third-party sites (willplatine).
_LEGAL_NOTICE_PATH_MARKERS = (
    "/aviso-legal",
    "/avisos-legales",
    "/informacion-corporativa",
    "/información-corporativa",
    "/legal-notice",
    "/legal",
    "/terms",
    "/terminos",
    "/términos",
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

# Geographic / market qualifiers that distinguish a local legal entity from the parent brand.
_ENTITY_QUALIFIER_TOKENS = frozenset(
    {
        "iberica",
        "iberia",
        "espana",
        "spain",
        "portugal",
        "italia",
        "italy",
        "france",
        "francia",
        "deutschland",
        "germany",
        "uk",
        "usa",
        "mexico",
        "brasil",
        "brazil",
        "latam",
        "europe",
        "europa",
        "international",
        "internacional",
        "global",
    }
)

_QUALIFIER_ALIASES = {
    "iberica": "iberia",
    "iberia": "iberia",
    "espana": "spain",
    "spain": "spain",
    "francia": "france",
    "france": "france",
    "italia": "italy",
    "italy": "italy",
    "deutschland": "germany",
    "germany": "germany",
    "brasil": "brazil",
    "brazil": "brazil",
    "europa": "europe",
    "europe": "europe",
    "internacional": "international",
    "international": "international",
}


def _normalize_qualifier_set(tokens: set[str]) -> set[str]:
    return {_QUALIFIER_ALIASES.get(t, t) for t in tokens}


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


_REGISTRY_TITLE_MARKERS = (
    "datoscif",
    "infoempresa",
    "einforma",
    "e-informa",
    "empresite",
    "northdata",
    "opencorporates",
    "axesor",
    "iberinform",
    "creditsafe",
    "companywall",
    "borrmat",
    "wolters kluwer",
    "paginas amarillas",
    "yellow pages",
    "borme",
    "boe.es",
    "razon social",
    "cif ",
    "cif:",
    "nif ",
    "nif:",
    "apiempresas",
)


_DIRECTORY_LISTING_MARKERS = (
    "corredurias en",
    "datos de contacto de",
    "datos de contacto",
    "listado de",
    "directorio de",
    "directorio",
    "empresas en",
    "oficina de seguros",
    "ubicacion",
    "descripcion",
    "sobre "  # weak alone; combined below
)


def evidence_looks_like_directory_listing(title: str | None, snippet: str | None) -> bool:
    """Detect association/directory pages that list a company without being its site."""
    title_n = normalize_text(title or "")
    snip_n = normalize_text(snippet or "")
    blob = f"{title_n} {snip_n}".strip()
    if not blob:
        return False
    if any(m in snip_n for m in (
        "corredurias en",
        "datos de contacto de",
        "listado de",
        "directorio de",
        "inscrita en el registro administrativo",
        "registro administrativo especial de mediadores",
        "startup hub",
        "startupshub",
        "invest in catalonia",
        "trade & investment",
        "trade and investment",
    )):
        return True
    # Title is bare company name + snippet is a short directory card
    if title_n and snip_n:
        dir_hits = sum(1 for m in ("descripcion", "ubicacion", "direccion", "telefono", "landline", "place:") if m in snip_n)
        if dir_hits >= 2:
            return True
    return False


def title_looks_like_registry(title: str | None) -> bool:
    blob = normalize_text(title or "")
    if not blob:
        return False
    return any(marker in blob for marker in _REGISTRY_TITLE_MARKERS)


def text_mentions_company(text: str | None, legal_name: str, *, min_hits: int | None = None) -> bool:
    """True when title/snippet contains distinctive tokens from the legal name."""
    blob = normalize_text(text or "")
    if not blob:
        return False
    tokens = distinctive_name_tokens(legal_name)
    if not tokens:
        # Fallback: whole core must appear loosely
        core = core_name(legal_name)
        return bool(core) and core in blob
    required = min_hits if min_hits is not None else (2 if len(tokens) >= 2 else 1)
    hits = sum(1 for t in tokens if t in blob)
    return hits >= min(required, len(tokens))


def token_coverage(reference: str, candidate: str) -> float:
    """Fraction of distinctive reference tokens present in candidate text."""
    tokens = distinctive_name_tokens(reference)
    if not tokens:
        return 0.0
    blob = normalize_text(candidate or "")
    if not blob:
        return 0.0
    hits = sum(1 for t in tokens if t in blob)
    return hits / len(tokens)


def looks_like_parent_or_group_name(legal_name: str, page_name: str | None) -> bool:
    """
    True when the LinkedIn/page name is a short token subset of the legal name
    (e.g. legal 'Marsh Iberica' vs page 'Marsh' / 'Marsh McLennan').
    """
    if not page_name:
        return False
    legal_norm = core_name(legal_name)
    page_norm = normalize_text(page_name)
    if not legal_norm or not page_norm:
        return False
    legal_tokens = set(legal_norm.split())
    page_tokens = set(page_norm.split()) - _WEAK_NAME_TOKENS
    # Qualifiers present in the legal name but missing on the page
    legal_qualifiers = _normalize_qualifier_set(legal_tokens & _ENTITY_QUALIFIER_TOKENS)
    page_qualifiers = _normalize_qualifier_set(set(page_norm.split()) & _ENTITY_QUALIFIER_TOKENS)
    missing_qualifiers = legal_qualifiers - page_qualifiers
    brand_tokens = distinctive_name_tokens(legal_name)
    if not brand_tokens:
        return False
    page_has_brand = any(t in page_norm for t in brand_tokens)
    if not page_has_brand:
        return False
    # Parent/global page: brand matches but local market qualifier is absent
    if missing_qualifiers and len(page_tokens) <= len(brand_tokens) + 2:
        return True
    # Page name is much shorter and only covers brand tokens
    if missing_qualifiers and len(page_norm.split()) < len(legal_norm.split()):
        return True
    return False


# Carrier/insurer portals — never the official site of an independent correduría
# unless the legal name itself is that carrier.
_INSURER_PORTAL_DOMAINS = frozenset(
    {
        "allianz.es",
        "allianz.com",
        "mapfre.es",
        "mapfre.com",
        "axa.es",
        "axa.com",
        "sanitas.es",
        "adeslas.es",
        "asisa.es",
        "zurich.es",
        "zurich.com",
        "generali.es",
        "generali.com",
        "catalanaoccidente.com",
        "ocaso.es",
        "mutua.es",
        "mutuamadrileña.es",
        "mutua-madrileña.es",
        "helvetia.es",
        "libertyseguros.es",
        "reale.es",
        "pelayo.com",
        "segurosbilbao.com",
        "kpmg.com",
        "kpmg.es",
        "deloitte.com",
        "deloitte.es",
        "pwc.com",
        "pwc.es",
        "ey.com",
    }
)


def is_insurer_portal_domain(domain: str | None, legal_name: str) -> bool:
    """True when domain is a big insurer/consultancy portal unrelated to this broker."""
    if not domain:
        return False
    d = domain.lower().removeprefix("www.")
    matched = next((p for p in _INSURER_PORTAL_DOMAINS if d == p or d.endswith("." + p)), None)
    if not matched:
        return False
    label = domain_label(matched)
    core = core_name(legal_name)
    core_tokens = set(core.split())
    # Allow if legal name clearly is that carrier (Mapfre España, Allianz …).
    if label and (label in core_tokens or label in core):
        return False
    return True


def is_noise_website_domain(domain: str | None) -> bool:
    if not domain:
        return True
    d = domain.lower().removeprefix("www.")
    if d in WEBSITE_NOISE_DOMAINS:
        return True
    if any(d.endswith(f".{noise}") or d == noise for noise in WEBSITE_NOISE_DOMAINS):
        return True
    return is_garbage_website_domain(d)


def is_garbage_website_domain(domain: str | None) -> bool:
    """Reject malformed hosts that are never real company sites (s.l, *.explora, …)."""
    if not domain:
        return True
    d = domain.lower().removeprefix("www.")
    try:
        import tldextract

        extracted = tldextract.extract(d)
    except Exception:
        return True
    # No public suffix → not a real registrable web domain.
    if not extracted.suffix:
        return True
    label = (extracted.domain or "").lower()
    if len(label) <= 2:
        return True
    return False


# Country-specific suffixes (longest first). Generic gTLDs (.com/.net/.org/.eu)
# are intentionally excluded — they are valid everywhere (Weecover, WTW, …).
_COUNTRY_SPECIFIC_SUFFIXES = (
    ".com.br",
    ".com.mx",
    ".com.ar",
    ".com.co",
    ".com.pt",
    ".com.pe",
    ".com.cl",
    ".co.uk",
    ".org.uk",
    ".org.br",
    ".br",
    ".mx",
    ".ar",
    ".it",
    ".fr",
    ".de",
    ".uk",
    ".ee",
    ".pt",
    ".pe",
    ".cl",
    ".uy",
    ".ec",
    ".bo",
    ".py",
    ".ve",
    ".cr",
    ".pa",
    ".gt",
    ".hn",
    ".sv",
    ".ni",
    ".do",
    ".be",
    ".nl",
    ".pl",
    ".ro",
    ".ch",
    ".at",
    ".si",
    ".sk",
    ".cz",
    ".hu",
    ".se",
    ".no",
    ".dk",
    ".fi",
    ".ie",
    ".gr",
    ".bg",
    ".hr",
    ".rs",
    ".es",
    ".cat",
)

# Preferred ccTLDs per ISO country_code used by the Google Search Actor.
_PREFERRED_SUFFIXES_BY_COUNTRY: dict[str, tuple[str, ...]] = {
    "es": (".es", ".cat"),
    "fr": (".fr",),
    "it": (".it",),
    "pt": (".pt", ".com.pt"),
    "de": (".de",),
    "uk": (".co.uk", ".org.uk", ".uk"),
    "gb": (".co.uk", ".org.uk", ".uk"),
    "br": (".com.br", ".org.br", ".br"),
    "mx": (".com.mx", ".mx"),
    "ar": (".com.ar", ".ar"),
    "co": (".com.co",),
    "cl": (".cl", ".com.cl"),
    "pe": (".pe", ".com.pe"),
    "be": (".be",),
    "nl": (".nl",),
    "ch": (".ch",),
    "at": (".at",),
    "ie": (".ie",),
}

_GENERIC_GTLD_SUFFIXES = (
    ".com",
    ".net",
    ".org",
    ".eu",
    ".io",
    ".app",
    ".dev",
    ".biz",
    ".info",
    ".xyz",
    ".online",
    ".tech",
    ".site",
    ".cloud",
    ".co",  # bare .co is widely used as a brand TLD; Colombia uses .com.co
)


def preferred_domain_suffixes(country_code: str | None) -> tuple[str, ...]:
    cc = (country_code or "").strip().lower()
    return _PREFERRED_SUFFIXES_BY_COUNTRY.get(cc, ())


def is_generic_gtld_domain(domain: str | None) -> bool:
    if not domain:
        return False
    d = domain.lower().removeprefix("www.")
    if any(d.endswith(suf) for suf in _COUNTRY_SPECIFIC_SUFFIXES):
        return False
    return any(d.endswith(suf) for suf in _GENERIC_GTLD_SUFFIXES)


def domain_matches_country(domain: str | None, country_code: str | None) -> bool:
    """True when the domain uses the batch country's preferred ccTLD."""
    preferred = preferred_domain_suffixes(country_code)
    if not domain or not preferred:
        return False
    d = domain.lower().removeprefix("www.")
    return any(d.endswith(suf) for suf in preferred)


def is_mismatched_country_domain(domain: str | None, country_code: str | None) -> bool:
    """True when the domain uses another country's ccTLD (not a generic gTLD).

    Soft geo signal for scoring — never a hard "only .es" rule. Unknown
    country codes or unknown TLDs are treated as non-mismatched.
    """
    if not domain:
        return False
    preferred = preferred_domain_suffixes(country_code)
    if not preferred:
        return False
    d = domain.lower().removeprefix("www.")
    if any(d.endswith(suf) for suf in preferred):
        return False
    if is_generic_gtld_domain(d):
        return False
    return any(d.endswith(suf) for suf in _COUNTRY_SPECIFIC_SUFFIXES)


def is_foreign_to_spain_domain(domain: str | None) -> bool:
    """Backward-compatible alias: mismatched vs Spain (country_code=es)."""
    return is_mismatched_country_domain(domain, "es")


# Sector cues mined from SERP titles/snippets — including directories that are
# rejected as official websites (eInforma, Axesor, …). Used only as scoring hints.
_SECTOR_HINT_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "insurance": (
        re.compile(r"\bseguros?\b", re.IGNORECASE),
        re.compile(r"\bcorredur", re.IGNORECASE),
        re.compile(r"\breaseguro", re.IGNORECASE),
        re.compile(r"\bmediadores?\b", re.IGNORECASE),
        re.compile(r"\bcnae\s*6622\b", re.IGNORECASE),
        re.compile(r"\binsurance\b", re.IGNORECASE),
        re.compile(r"\bbrokers?\b", re.IGNORECASE),
        re.compile(r"\binsurtech\b", re.IGNORECASE),
        re.compile(r"\bassurances?\b", re.IGNORECASE),
        re.compile(r"\bpolizas?\b", re.IGNORECASE),
        re.compile(r"\basegurador", re.IGNORECASE),
    ),
}

_OFF_SECTOR_MARKERS: dict[str, tuple[str, ...]] = {
    "insurance": (
        "montessori",
        "colegio",
        "escuela infantil",
        "escuela ",
        "universidad",
        "university",
        "school ",
        "football",
        "soccer",
        "restaurant",
        "hotel ",
        "turismo escolar",
    ),
}


def extract_sector_hints(*texts: str | None) -> frozenset[str]:
    """Return sector keys detected in free text (legal name, SERP title/snippet)."""
    blob = " ".join(t for t in texts if t)
    if not blob.strip():
        return frozenset()
    found: set[str] = set()
    for sector, patterns in _SECTOR_HINT_PATTERNS.items():
        if any(p.search(blob) for p in patterns):
            found.add(sector)
    return frozenset(found)


def collect_sector_hints_from_evidences(
    legal_name: str,
    evidences: list[Any],
) -> frozenset[str]:
    """Mine sector hints from legal name + all SERP rows (including directories)."""
    texts: list[str | None] = [legal_name]
    for ev in evidences:
        texts.append(getattr(ev, "title", None))
        texts.append(getattr(ev, "snippet", None))
    return extract_sector_hints(*texts)


def sector_alignment_delta(
    *,
    title: str | None,
    snippet: str | None,
    domain: str | None,
    sector_hints: frozenset[str] | set[str] | None,
) -> tuple[float, list[str]]:
    """Score delta for a website candidate vs mined sector hints."""
    if not sector_hints:
        return 0.0, []
    blob = f"{title or ''} {snippet or ''} {domain or ''}"
    blob_n = normalize_text(blob)
    delta = 0.0
    reasons: list[str] = []
    for sector in sector_hints:
        patterns = _SECTOR_HINT_PATTERNS.get(sector) or ()
        if any(p.search(blob) for p in patterns):
            delta += 14.0
            reasons.append(f"sector_match:{sector}")
        off = _OFF_SECTOR_MARKERS.get(sector) or ()
        if any(marker in blob_n for marker in off):
            delta -= 22.0
            reasons.append(f"sector_mismatch:{sector}")
    return delta, reasons


_DISPOSABLE_SUBDOMAINS = frozenset(
    {
        "www",
        "www2",
        "www3",
        "m",
        "mobile",
        "blog",
        "blogs",
        "news",
        "shop",
        "store",
        "cdn",
        "static",
        "img",
        "images",
        "assets",
    }
)


def normalize_homepage_url(url: str | None) -> str | None:
    """Return scheme+host homepage only (no path/query/fragment).

    Strips disposable hosts (``www``, ``blog``, …) but keeps meaningful
    subdomains such as ``servicios-seguros.wtwco.com`` or ``es.site.com``.
    City branch hosts like ``vigo.albroksa.com`` still collapse to apex.
    """
    if not url:
        return None
    raw = url.strip()
    if not raw:
        return None
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.netloc or "").lower()
    if not host:
        return None
    host = host.split("@")[-1]
    if ":" in host:
        name, _, port = host.rpartition(":")
        if not (port.isdigit() and port not in {"80", "443"}):
            host = name or host
    apex = extract_registrable_domain(host) or host.removeprefix("www.")
    if not apex:
        return None

    labels = host.removeprefix("www.").split(".")
    apex_labels = apex.split(".")
    # subdomain labels = host without apex
    if len(labels) > len(apex_labels):
        sub_labels = labels[: len(labels) - len(apex_labels)]
    else:
        sub_labels = []

    keep_sub: list[str] = []
    for label in sub_labels:
        if label in _DISPOSABLE_SUBDOMAINS:
            continue
        # Collapse obvious geographic branch hosts onto apex.
        if label in {
            "vigo",
            "madrid",
            "barcelona",
            "valencia",
            "sevilla",
            "bilbao",
            "malaga",
            "zaragoza",
            "oviedo",
            "gijon",
            "aviles",
            "delegacion",
            "sucursal",
            "oficina",
        }:
            continue
        keep_sub.append(label)

    if keep_sub:
        final_host = ".".join(keep_sub + apex_labels)
    else:
        final_host = f"www.{apex}"
    return urlunparse(("https", final_host, "/", "", "", ""))


def website_path_looks_editorial(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url if "://" in url else f"https://{url}")
    path = (parsed.path or "").lower()
    if path.endswith(".pdf"):
        return True
    return any(marker in path for marker in _WEAK_PATH_MARKERS)


def website_path_looks_about(url: str | None) -> bool:
    """True for about/quienes-somos style paths (official self-description pages)."""
    if not url:
        return False
    parsed = urlparse(url if "://" in url else f"https://{url}")
    path = (parsed.path or "").lower()
    return any(marker in path for marker in _ABOUT_PATH_MARKERS)


def website_path_looks_legal_notice(url: str | None) -> bool:
    """True for aviso-legal / corporate-terms pages that often cite the legal name."""
    if not url:
        return False
    parsed = urlparse(url if "://" in url else f"https://{url}")
    path = (parsed.path or "").lower()
    return any(marker in path for marker in _LEGAL_NOTICE_PATH_MARKERS)


# Commercial / group brands that appear in titles while the legal name is only
# in the snippet (Willis Iberia → "Quienes Somos - Seguros - WTW").
_GROUP_BRAND_TITLE_TOKENS = frozenset(
    {
        "wtw",
        "willistowerswatson",
        "marsh",
        "mclennan",
        "aon",
        "allianz",
        "axa",
        "zurich",
        "generali",
        "mapfre",
    }
)


def title_has_group_brand(title: str | None) -> bool:
    tokens = set(normalize_text(title or "").split())
    return bool(tokens & _GROUP_BRAND_TITLE_TOKENS) or "willis towers watson" in normalize_text(
        title or ""
    )


def select_official_website(
    *,
    legal_name: str,
    harvest_website: str | None,
    google_website: str | None,
    google_domain: str | None,
    google_content_backed: bool = False,
    min_domain_similarity: float = 55.0,
    country_code: str | None = None,
) -> tuple[str | None, str | None, str | None, str | None]:
    """
    Choose a clean official homepage.

    Returns (website, domain, google_website_clean, harvest_website_clean).

    Pipeline priority (website selection):
      1. Strong Google result after full SERP analysis (content-backed / name match)
      2. Harvest website only when Google is missing or clearly weaker
      3. Soft country-ccTLD preference from ``country_code`` (never hard .es-only)

    Harvest URLs that lose are still returned as evidence (4th tuple slot).
    """
    from rapidfuzz import fuzz

    core = core_name(legal_name)
    cc = (country_code or "").strip().lower() or None

    def _sim(domain: str | None) -> float:
        label = domain_label(domain)
        if not label or not core:
            return 0.0
        return float(fuzz.token_set_ratio(core, normalize_text(label)))

    harvest_clean = None
    harvest_dom = extract_registrable_domain(harvest_website)
    harvest_sim = 0.0
    harvest_kept_for_evidence = None
    if harvest_website and harvest_dom and not is_noise_website_domain(harvest_dom):
        harvest_clean = normalize_homepage_url(harvest_website)
        harvest_kept_for_evidence = harvest_clean
        harvest_sim = _sim(harvest_dom)

    google_clean = None
    google_dom = google_domain or extract_registrable_domain(google_website)
    google_sim = 0.0
    if google_website and google_dom and not is_noise_website_domain(google_dom):
        google_sim = _sim(google_dom)
        if google_content_backed or google_sim >= min_domain_similarity:
            google_clean = normalize_homepage_url(google_website)
        else:
            google_dom = None

    def _rank(sim: float, domain: str | None) -> float:
        bonus = 0.0
        if domain_matches_country(domain, cc):
            bonus += 8.0
        elif is_mismatched_country_domain(domain, cc):
            bonus -= 18.0
        return sim + bonus

    harvest_rank = _rank(harvest_sim, harvest_dom) if harvest_clean else -1.0
    google_rank = _rank(google_sim, google_dom) if google_clean else -1.0

    # Soft: demote Harvest twins on another country's ccTLD so Google can win,
    # but keep the URL for evidence. Do not hard-null generic .com Harvest sites.
    harvest_usable = harvest_clean
    harvest_usable_dom = harvest_dom
    harvest_usable_rank = harvest_rank
    if harvest_clean and harvest_dom and is_mismatched_country_domain(harvest_dom, cc):
        harvest_usable = None
        harvest_usable_dom = None
        harvest_usable_rank = -1.0

    # 1) Google-first when content-backed or clearly better than Harvest.
    if google_clean and google_content_backed:
        if not harvest_usable:
            return google_clean, google_dom, google_clean, harvest_kept_for_evidence
        # Near-tie or better → keep the analyzed Google site (avoids UK/CO twins).
        if google_rank + 5 >= harvest_usable_rank or google_sim >= 70:
            return google_clean, google_dom, google_clean, harvest_kept_for_evidence

    # 2) Harvest when it is related and Google did not win above.
    if harvest_usable and harvest_sim >= 25:
        if (
            google_clean
            and google_content_backed
            and google_rank >= harvest_usable_rank + 8
        ):
            return google_clean, google_dom, google_clean, harvest_kept_for_evidence
        return harvest_usable, harvest_usable_dom, google_clean, harvest_kept_for_evidence

    # 3) Google without Harvest (or weak Harvest).
    if google_clean:
        return google_clean, google_dom, google_clean, harvest_kept_for_evidence

    # 4) Weak Harvest fallback.
    if harvest_usable and harvest_sim >= 20:
        return harvest_usable, harvest_usable_dom, google_clean, harvest_kept_for_evidence

    return None, None, None, harvest_kept_for_evidence


def contains_branch_terms(*texts: str | None) -> bool:
    blob = normalize_text(" ".join(t for t in texts if t))
    return any(term in blob for term in (normalize_text(t) for t in BRANCH_TERMS))
