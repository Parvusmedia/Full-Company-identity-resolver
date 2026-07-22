"""Unit-cost model for Full Company Identity Resolver.

Prices are operator COGS (what we pay providers), not client list prices.
Sources and assumptions are documented in docs/COST_AND_PRICING.md.
Update UNIT_COSTS when provider rate cards change.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


# --- Provider unit costs (USD) — Free / list tier, mid-2026 ---
# Google: apify/google-search-scraper PPE "from $1.80 / 1,000 pages"
# Harvest: HarvestAPI company detail ~$3–$4 / 1,000 (use $4 conservative)
# OpenAI: gpt-4o-mini ~$0.15/1M in + $0.60/1M out ≈ $0.0006 for one short call
# Apify CU: light HTTP actor amortized per company in a batch

UNIT_COSTS_USD: dict[str, float] = {
    "google_serp_page": 0.0018,  # $1.80 / 1,000 search pages
    "harvest_company": 0.0040,  # $4.00 / 1,000 company enrichments
    "openai_disambiguation": 0.0006,  # one gpt-4o-mini JSON call
    "apify_compute_per_company": 0.0020,  # own Actor CU + transfer overhead
}

# Apify Store PPE: developer keeps 80% of event revenue
APIFY_STORE_REVENUE_SHARE = 0.80


@dataclass(frozen=True)
class EnrichmentUsage:
    """Billable external units consumed for one company."""

    google_queries: int
    harvest_calls: int
    openai_calls: int = 0
    label: str = ""
    description: str = ""


@dataclass(frozen=True)
class CostBreakdown:
    label: str
    description: str
    google_queries: int
    harvest_calls: int
    openai_calls: int
    google_usd: float
    harvest_usd: float
    openai_usd: float
    compute_usd: float
    total_cogs_usd: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def estimate_cogs(usage: EnrichmentUsage, unit_costs: dict[str, float] | None = None) -> CostBreakdown:
    """Estimate our COGS for one company given unit consumption."""
    costs = unit_costs or UNIT_COSTS_USD
    google_usd = usage.google_queries * costs["google_serp_page"]
    harvest_usd = usage.harvest_calls * costs["harvest_company"]
    openai_usd = usage.openai_calls * costs["openai_disambiguation"]
    compute_usd = costs["apify_compute_per_company"]
    total = google_usd + harvest_usd + openai_usd + compute_usd
    return CostBreakdown(
        label=usage.label,
        description=usage.description,
        google_queries=usage.google_queries,
        harvest_calls=usage.harvest_calls,
        openai_calls=usage.openai_calls,
        google_usd=round(google_usd, 6),
        harvest_usd=round(harvest_usd, 6),
        openai_usd=round(openai_usd, 6),
        compute_usd=round(compute_usd, 6),
        total_cogs_usd=round(total, 6),
    )


def client_price_for_target_margin(
    cogs_usd: float,
    *,
    net_margin: float = 0.40,
    revenue_share: float = APIFY_STORE_REVENUE_SHARE,
) -> float:
    """Minimum client list price so that after marketplace share we keep `net_margin`.

    net_profit = revenue_share * price - cogs
    We want net_profit / (revenue_share * price) >= net_margin
    => price >= cogs / (revenue_share * (1 - net_margin))
    """
    if not 0 <= net_margin < 1:
        raise ValueError("net_margin must be in [0, 1)")
    if not 0 < revenue_share <= 1:
        raise ValueError("revenue_share must be in (0, 1]")
    return cogs_usd / (revenue_share * (1.0 - net_margin))


def break_even_client_price(
    cogs_usd: float,
    *,
    revenue_share: float = APIFY_STORE_REVENUE_SHARE,
) -> float:
    """Client price where net profit is exactly zero after marketplace commission."""
    return client_price_for_target_margin(cogs_usd, net_margin=0.0, revenue_share=revenue_share)


# Pipeline scenarios matching resolver.py defaults / caps
SCENARIOS: tuple[EnrichmentUsage, ...] = (
    EnrichmentUsage(
        label="minimo",
        description=(
            "Nombre sin forma jurídica distinta del core; match claro. "
            "2 Google (linkedin+website) + 2 Harvest. Sin fallback ni AI."
        ),
        google_queries=2,
        harvest_calls=2,
        openai_calls=0,
    ),
    EnrichmentUsage(
        label="estandar",
        description=(
            "Defaults del Actor: 3 Google (legal linkedin + website + core linkedin) "
            "+ 2 Harvest. Sin fallback ni AI."
        ),
        google_queries=3,
        harvest_calls=2,
        openai_calls=0,
    ),
    EnrichmentUsage(
        label="con_fallback",
        description=(
            "Confianza < 78 y dominio conocido: +1 Google domain fallback "
            "+ hasta 2 Harvest adicionales sobre URLs nuevas."
        ),
        google_queries=4,
        harvest_calls=4,
        openai_calls=0,
    ),
    EnrichmentUsage(
        label="agresivo",
        description=(
            "max_harvest_candidates=5, con fallback y nuevas URLs, sin AI. "
            "Cerca del techo de consumo sin OpenAI."
        ),
        google_queries=4,
        harvest_calls=8,
        openai_calls=0,
    ),
    EnrichmentUsage(
        label="peor_caso",
        description=(
            "Techo del código: 3 Google iniciales + 1 fallback, hasta 5+5 Harvest "
            "(top N + nuevas en fallback), +1 OpenAI si use_ai_for_ambiguous=true."
        ),
        google_queries=4,
        harvest_calls=10,
        openai_calls=1,
    ),
)


def all_scenario_costs(unit_costs: dict[str, float] | None = None) -> list[CostBreakdown]:
    return [estimate_cogs(s, unit_costs) for s in SCENARIOS]


def pricing_recommendation(
    *,
    design_scenario: str = "peor_caso",
    net_margin: float = 0.40,
    unit_costs: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Recommend client PPE price anchored on a design (usually worst-case) COGS."""
    costs = {c.label: c for c in all_scenario_costs(unit_costs)}
    if design_scenario not in costs:
        raise KeyError(f"Unknown scenario: {design_scenario}")
    design = costs[design_scenario]
    list_price = client_price_for_target_margin(design.total_cogs_usd, net_margin=net_margin)
    be = break_even_client_price(design.total_cogs_usd)
    our_revenue = list_price * APIFY_STORE_REVENUE_SHARE
    net_profit = our_revenue - design.total_cogs_usd
    return {
        "design_scenario": design_scenario,
        "design_cogs_usd": design.total_cogs_usd,
        "apify_revenue_share": APIFY_STORE_REVENUE_SHARE,
        "target_net_margin": net_margin,
        "break_even_client_price_usd": round(be, 4),
        "recommended_client_price_usd": round(list_price, 4),
        "rounded_list_price_usd": round(list_price + 0.005, 2),  # commercial round-up to cent
        "our_revenue_after_commission_usd": round(our_revenue, 4),
        "net_profit_on_design_usd": round(net_profit, 4),
        "scenarios": {label: c.as_dict() for label, c in costs.items()},
    }


def format_report(recommendation: dict[str, Any] | None = None) -> str:
    rec = recommendation or pricing_recommendation()
    lines = [
        "Full Company Identity Resolver — COGS & pricing",
        "=" * 56,
        "",
        "Unit costs (USD):",
    ]
    for key, value in UNIT_COSTS_USD.items():
        lines.append(f"  - {key}: ${value:.4f}")
    lines.extend(["", "Scenarios (COGS per company):"])
    for label, data in rec["scenarios"].items():
        lines.append(
            f"  - {label}: ${data['total_cogs_usd']:.4f} "
            f"(G={data['google_queries']} H={data['harvest_calls']} AI={data['openai_calls']})"
        )
    lines.extend(
        [
            "",
            f"Design scenario: {rec['design_scenario']} @ ${rec['design_cogs_usd']:.4f} COGS",
            f"Apify Store keep: {rec['apify_revenue_share']:.0%} of client price",
            f"Target net margin (on our keep): {rec['target_net_margin']:.0%}",
            f"Break-even client price: ${rec['break_even_client_price_usd']:.4f}",
            f"Recommended client price: ${rec['recommended_client_price_usd']:.4f}",
            f"Commercial list (rounded): ${rec['rounded_list_price_usd']:.2f} / company",
            f"Our keep @ list: ${rec['our_revenue_after_commission_usd']:.4f}",
            f"Net profit @ design: ${rec['net_profit_on_design_usd']:.4f}",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    print(format_report())
