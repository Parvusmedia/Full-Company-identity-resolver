# Company Identity Resolver

Paste **company names or legal names** → get **one enrichment row** each:
LinkedIn company URL, official website, domain, firmographics, confidence and evidence.

**No API keys to configure.** Search, website validation and LinkedIn enrichment are
included in the Actor price (publisher-operated).

Built for **prospecting, CRM enrichment and LinkedIn Ads**.

> Store pack: [`store/STORE_LISTING.md`](store/STORE_LISTING.md)

## How to use (end users)

1. Paste names in **Company names** (one per line) or use the `companies` JSON list  
2. Optionally set search country/language (`es` by default)  
3. Run → download the dataset  

That’s it. You do **not** need Harvest, OpenAI or Google API keys.

## Pipeline (what we run for you)

1. Parse company names  
2. Google discovery (LinkedIn + website)  
3. Score / filter directories & registries  
4. Homepage validation  
5. LinkedIn firmographic enrichment  
6. Optional domain→LinkedIn fallback when web is known but LinkedIn is missing  
7. One output row per company  

## Pricing (Apify Store)

**All-inclusive pay-per-company:** recommended **$0.18 / row** (≈ **$180 / 1,000**).

That price is designed to cover:
- Google Search + compute (platform usage we absorb)
- LinkedIn enrichment (Harvest — our cost)
- Apify’s marketplace commission (~20% of PPE)

See the full unit-economics table in [`store/STORE_LISTING.md`](store/STORE_LISTING.md).

## Example input / output

- [`store/example_input.json`](store/example_input.json) — names only  
- [`store/example_output.json`](store/example_output.json)  
- Screenshots: [`store/screenshot_mockup.html`](store/screenshot_mockup.html)  

## Publisher setup (not for Store users)

Set these as **Actor environment variables** in Apify Console (never in user input):

| Variable | Required | Purpose |
|---|---|---|
| `APIFY_TOKEN` | Yes | Nested Google Search Actor |
| `HARVEST_API_KEY` | Yes | LinkedIn company enrichment |
| `OPENAI_API_KEY` | Optional | Rare ambiguous disambiguation |

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export APIFY_TOKEN=...
export HARVEST_API_KEY=...
python -m my_actor
```

## Output fields

- `legal_name`, `commercial_name`, `linkedin_url`, `website`, `domain`
- `industry`, `employee_count`, `followers`, `headquarters_*`
- `relationship`, `match_status`, `confidence`, `evidence_summary`

### Match status

| Score | Status |
|---|---|
| ≥ 90 | `confirmed` |
| 78–89 | `high_confidence` |
| 60–77 | `probable` |
| 40–59 | `ambiguous` |
| < 40 | `not_found` / `partial` if website only |

## Notes

- Strongest on Spanish SERPs today; `country_code` / `language_code` are configurable.  
- Directories/gazettes/news are rejected as official websites.  
- Rows with website but no LinkedIn return `partial` (still a useful result).  
