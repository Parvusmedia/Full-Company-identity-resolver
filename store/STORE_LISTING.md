# Apify Store listing — Company Identity Resolver

Source of truth for **Publication** in Apify Console.

**Product model:** end users only paste company names.  
**You** (publisher) supply `APIFY_TOKEN` + `HARVEST_API_KEY` (+ optional OpenAI) as Actor env vars.  
Price must cover **all COGS + Apify’s ~20% cut**.

---

## 4) Identity

### Title
**Company Identity Resolver: Legal Name → LinkedIn & Website**

### Slug
`company-identity-resolver`

### One-line (≤160 chars)
Paste company or legal names → get LinkedIn, official website, domain, HQ, employees, confidence & evidence. All-inclusive — no API keys to configure.

### Store description

```text
Turn company / legal names into a clean B2B identity record — no API keys required.

What you provide
• Company name or legal name (razón social), one per line
• Optional city / country hints

What you get (one row per company)
• LinkedIn company URL
• Official website + domain (directories & registries filtered out)
• Industry, employees, followers, HQ (when available)
• match_status, confidence, relationship, evidence summary

This is not a raw LinkedIn scraper. It combines web discovery, scoring, homepage checks
and firmographic enrichment into a single paid service.

Ideal for: CRM enrichment, prospecting lists, LinkedIn Ads audiences.

Strongest today on Spanish / ES search results; country & language are configurable.

Pricing: all-inclusive pay-per-company (see Pricing). You only pay Apify for this Actor —
no Harvest, OpenAI or extra Google API keys to bring.
```

### Tags
Lead generation · Business · Automation · CRM · LinkedIn · enrichment · legal name · prospecting

---

## 1) Pricing (all-inclusive for the user)

### Your real COGS per company (you pay these)

| Cost | Typical | Notes |
|---|---|---|
| Nested Google Search (~2 queries) | $0.02–0.05 | Billed as Apify platform usage on *your* account |
| Actor compute + homepage GET | $0.01–0.03 | Platform usage |
| Harvest LinkedIn enrichment | $0.03–0.08 | **Your** HarvestAPI invoice (not Apify) |
| Optional OpenAI (rare) | ~$0.00–0.01 | Usually off |
| Retries / hard cases / Maps (if on) | buffer | |
| **COGS mid** | **~$0.08** | |
| **COGS high** | **~$0.12–0.15** | |

### Apify take
You keep **~80%** of PPE revenue.  
`profit ≈ 0.8 × price − COGS`  
(if you absorb platform usage; recommended for “all-inclusive” UX)

### Recommended list price

| | |
|---|---|
| **PPE primary event** | `apify-default-dataset-item` |
| **Price** | **$0.18 per company** ≈ **$180 / 1,000** |
| **Platform usage** | **Absorb** (do **not** pass to user) so the Store page shows one clear price |
| Actor start event | keep Apify default (tiny) |

### Unit economics at $0.18

| | Amount |
|---|---|
| User pays | $0.18 |
| You receive (80%) | $0.144 |
| COGS mid ($0.08) | −$0.08 |
| **Net ≈** | **~$0.06 / company** |
| COGS high ($0.12) | −$0.12 |
| **Net ≈** | **~$0.02 / company** |

That is tight on hard rows — monitor **Analytics → cost per 1,000**.  
If Harvest average > $0.06, raise to **$0.22** ($220/1k) after the 14-day notice window.

### Launch ladder

| Phase | Price / company | When |
|---|---|---|
| Soft launch | $0.15 | First reviews (thin margin — watch COGS) |
| **Standard** | **$0.18** | Default |
| Premium | $0.22–0.25 | Multi-country / higher fill rate |

### Do not
- Ask users for Harvest / OpenAI / Google keys  
- Use rental pricing (sunset 2026)  
- Price like a $5/1k scraper — this is enrichment

### Abuse controls (with embedded keys)
- Cap run size in README (e.g. recommend ≤500 companies/run)  
- Optional hard cap in code later (`max_companies`)  
- Memory/timeout defaults that discourage mega-abuse  

---

## 3) Money flow

```text
User pastes company names → runs Actor
        ↓
Pays Apify: $0.18 × rows  (+ their Apify plan)
        ↓
Apify keeps ~20% of PPE
        ↓
You get ~80% of PPE, and YOU pay Harvest + platform usage from that
        ↓
Monthly payout (~11th): PayPal/Wise (≥$20) or bank (≥$100)
```

Configure: **Settings → Billing / Payouts** + **Actor → Publication → Monetization**.

---

## 2) Store assets in this repo

| File | Use |
|---|---|
| `store/example_input.json` | Example — names only |
| `store/example_output.json` | Dataset sample |
| `store/screenshot_mockup.html` | 3 screenshots |
| `store/banner.png` | Banner |
| `.actor/input_schema.json` | **No API key fields** |

### Publisher-only env vars (Actor → Settings → Environment)

| Var | Required |
|---|---|
| `APIFY_TOKEN` | Yes (nested Google Search) |
| `HARVEST_API_KEY` | Yes (firmographics) |
| `OPENAI_API_KEY` | Optional |

Never document these as user input.

### Screenshots
1. Hero value prop  
2. Input = company names only  
3. Output table LinkedIn + website + status  

---

## Publication checklist

1. Identity verification + payout method  
2. Env vars set on the Actor (your tokens)  
3. Title + description from this file  
4. Screenshots + banner  
5. Monetization: PPE **$0.18** / dataset item, **absorb** platform usage  
6. Publish public  
7. Watch cost/1k weekly; raise price if margin < ~$0.03  
