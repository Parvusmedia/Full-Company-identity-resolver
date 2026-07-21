# Company Identity Resolver

Apify Actor that turns a **company name, legal name (razón social), or brand** into
**exactly one enrichment row**: LinkedIn company URL, official website, domain,
firmographics, confidence and evidence.

Built for **prospecting, CRM enrichment and LinkedIn / paid-media** workflows — not a
raw LinkedIn scraper.

> Store listing pack (pricing, screenshots, payout FAQ): [`store/STORE_LISTING.md`](store/STORE_LISTING.md)

## Pipeline

1. Parse `companies` (priority) or newline-separated `queries`
2. Optionally skip rows that already have a non-noise website + confirmed/high_confidence
3. Normalize legal name and strip legal forms (SA, SL, SLU, Sociedad Limitada, …)
4. Batched Google Search (2 queries/company): exact LinkedIn + soft website; core LinkedIn only if no `/company/`
5. Keep only `linkedin.com/company/*`, normalize and dedupe; score websites (about-page / AI Overview bridge)
6. Cheap homepage probe (default top-1) + optional Maps (off by default)
7. Pre-score → Harvest top candidates (skip #2 when pre-score gap ≥ 15)
8. Optional domain→LinkedIn Google only when LinkedIn is weak and website is strong
9. Optional OpenAI only for ambiguous cases
10. Push **one** dataset item per input company

## Project layout

```text
.actor/
  actor.json
  input_schema.json
my_actor/
  __main__.py          # python -m my_actor
  main.py
  models.py
  normalization.py
  google_search.py
  harvest.py
  scoring.py
  resolver.py
  ai_resolver.py
Dockerfile
requirements.txt
README.md
```

## Secrets (Apify environment variables)

Configure in the Actor settings / environment — **never commit secrets**:

| Variable | Required | Purpose |
|---|---|---|
| `APIFY_TOKEN` | Yes (for Google) | Call Google Search Actor |
| `HARVEST_API_KEY` | Yes (for enrichment) | `GET https://api.harvest-api.com/linkedin/company` |
| `OPENAI_API_KEY` | Optional | Ambiguous-case disambiguation |

Input may accept the same keys as fallbacks for local tests (`apify_token`,
`harvest_api_key`, `openai_api_key`). Tokens are **never** written to logs.

If an Apify token was shared in a previous chat, treat it as compromised and rotate it.

## Connect this repository in Apify

1. Open [Apify Console](https://console.apify.com/) → **Actors** → **Develop new** → **Link Git repository**
2. Connect `https://github.com/Parvusmedia/Full-Company-identity-resolver` (or your fork)
3. Ensure the build uses the root `Dockerfile` (`python -m my_actor`)
4. Set `APIFY_TOKEN`, `HARVEST_API_KEY` (and optionally `OPENAI_API_KEY`) in Actor environment variables
5. Build and run with the sample input below

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Syntax / import checks
python -m compileall my_actor
python -c "import my_actor; import my_actor.main"

# Run Actor (requires Apify local env / tokens)
python -m my_actor
```

Without input, the Actor exits with a readable error asking for `queries` or `companies`.

## First test input

```json
{
  "queries": "Albrok Mediacion S.A.\nOtra Empresa S.L.",
  "google_results_per_page": 10,
  "max_harvest_candidates": 2,
  "fallback_google_by_website": true,
  "use_ai_for_ambiguous": false,
  "batch_size": 20,
  "debug": true
}
```

Structured input (takes priority over `queries`):

```json
{
  "companies": [
    {
      "source_id": "pipedrive-123",
      "legal_name": "Empresa Uno S.L.",
      "tax_id": "B12345678",
      "city": "Madrid",
      "province": "Madrid",
      "country": "España"
    }
  ],
  "debug": true
}
```

## Output

One dataset row per company. Important fields:

- `legal_name`, `commercial_name`, `linkedin_url`, `website`, `domain`
- `industry`, `employee_count`, `followers`, `headquarters_*`
- `relationship`, `match_status`, `confidence`, `evidence_summary`
- `candidates_found`, `candidates_enriched`, `google_queries_used`, `error`

With `debug=true` the row also includes `candidates`, `website_candidates`,
`ai_decision` and nested `raw_harvest` per candidate. With `debug=false`,
`raw_harvest` is **not** published.

### Match status guide

| Score | Status |
|---|---|
| ≥ 90 | `confirmed` |
| 78–89 | `high_confidence` |
| 60–77 | `probable` |
| 40–59 | `ambiguous` |
| < 40 | `not_found` |

Close scores between the top two candidates reduce the classification.

## HarvestAPI

```http
GET https://api.harvest-api.com/linkedin/company
X-API-Key: <HARVEST_API_KEY>
?url=https://www.linkedin.com/company/empresa/
```

Also supports `universalName` and `search`. The Actor uses `url` for candidates
discovered by Google. Response `element` fields are mapped into the output row.

## Notes

- Official websites are stripped to the registrable homepage (`https://www.telefonica.es/`,
  never `/es/nosotros/`; city subdomains collapse to apex). Directories, gazettes and
  media (`infoempresa.com`, `boe.es`, `elespanol.com`, …) are rejected. Google brand/group
  domains are kept only when the **title** mentions the company (Verspieren → `alkora.es`).
- Batch Google evidence is attributed by **exact query**, not substring, to avoid
  cross-company bleed (`MAPFRE S.A.` vs `MAPFRE ESPANA S.A.`).
- Parent/global LinkedIn pages (e.g. Marsh for Marsh Iberica) are penalized vs local
  entity pages. `/posts/` URLs are not turned into fake `/company/` pages.
- These quality gates are deterministic and add **no** extra Google or Harvest calls.
  Homepage validation does one cheap HTTP GET per top website candidate (default 3).
- When Search scoring still leaves no website, a free **Google AI Overview** layer
  reuses overview text/sources already returned by the Google Search Actor (before
  the paid Google Maps fallback).
- Cache via named Key-Value Store is intentionally **not** included in this first
  build (priority: correct build → correct run → correct results).
- No dataset schema is published yet, to keep the Actor definition minimal and valid.
- A Harvest failure does not discard Google evidence (`enrichment_status=harvest_failed_google_kept`).
- Companies without LinkedIn return `match_status=not_found` or `partial` and do not abort the batch.

## Pricing (Apify Store)

Recommended model: **Pay per event** — **$0.10 per company row** (dataset item),
≈ **$100 / 1,000 companies**, with **platform usage passed to the user**.

You pay Apify; Apify pays the developer (~80% of PPE revenue − any absorbed usage).
See [`store/STORE_LISTING.md`](store/STORE_LISTING.md) for the full monetization guide.

## Example input / output

- Input: [`store/example_input.json`](store/example_input.json)
- Output sample: [`store/example_output.json`](store/example_output.json)
- Screenshot mockups: open [`store/screenshot_mockup.html`](store/screenshot_mockup.html)
