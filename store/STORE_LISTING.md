# Apify Store listing — Company Identity Resolver

Use this file as the source of truth when filling **Publication** in Apify Console.

---

## 4) Identity (name + positioning)

### Recommended Store title
**Company Identity Resolver — Legal Name to LinkedIn, Website & Domain**

### Actor name (URL slug)
`company-identity-resolver`  
(Console → Settings → rename if still `full-company-identity-resolver`)

### One-line SEO description (≤160 chars)
Resolves company / legal / LinkedIn names into one row: LinkedIn, website, domain, HQ, employees, confidence & evidence. For CRM, prospecting & LinkedIn Ads.

### Longer Store description (paste into Publication → Description)

```text
Turn messy company inputs into a clean B2B identity record.

Input any of:
• Legal name / razón social (e.g. “Willis Iberia Correduría…, S.A.”)
• Commercial / brand name
• Optional city / country hints

Output exactly one enrichment row per company with:
• LinkedIn company URL (normalized /company/…)
• Official website + domain (directories, gazettes & news rejected)
• Industry, employees, followers, HQ, phone, logo (when enrichment succeeds)
• match_status, confidence, relationship and an evidence summary

Why this is not “just a LinkedIn finder”
• Google discovery + scoring + homepage validation + optional AI Overview brand bridge
• Harvest enrichment for firmographics
• Explicit rejection of registry/directory noise (infoempresa, BORME, empresite, …)
• Built for prospecting lists, CRM enrichment and LinkedIn / paid-media audience building

Best fit today: Spain & Spanish-language SERPs (country_code=es). Country/language are configurable; global registry denylists can be extended.

Pricing: Pay per resolved company (dataset row). See README Pricing.
```

### Categories / tags (Console)
`Lead generation` · `AI` · `Automation` · `Business` · `Developer tools`  
Keywords: `linkedin company`, `crm enrichment`, `legal name`, `website finder`, `b2b identity`, `prospecting`, `razón social`

### Use-case bullets (README / Store)
1. Enrich CRM accounts from legal names before outreach  
2. Build LinkedIn Ads matched audiences from company lists  
3. Clean prospecting CSVs: legal name → LinkedIn + website + domain  
4. Disambiguate subsidiaries vs parent brand pages  

---

## 1) Pricing (rentable but reasonable)

### Cost structure (your COGS per company, typical)

| Step | Approx. cost |
|---|---|
| Nested Google Search (≈2 queries) | $0.01–0.04 |
| Actor compute + homepage GET | $0.005–0.02 |
| Harvest LinkedIn enrichment (1–2 calls) | $0.02–0.08 |
| **Total COGS** | **~$0.04–0.12** |

Your Actor is **enrichment**, not raw scrape — price above plain scrapers ($1–10 / 1k results).

### Recommended model: **Pay per event (PPE)** — primary

| Event | Price | Role |
|---|---|---|
| `apify-default-dataset-item` (**primary**) | **$0.10** / company row | Main charge ≈ **$100 / 1,000 companies** |
| `apify-actor-start` | leave default (~$0.00005–0.001) | Covers cold start; Apify often gives free first seconds |

**Also enable:** *Pass platform usage costs to the user* (at least for the first 60–90 days).  
That way nested Google Search + CU do not eat your 80% share while you learn real COGS.

### Profit sketch (PPE, usage passed to user)

- User pays: $0.10/result + platform usage  
- You receive: `0.8 × $0.10` = **$0.08 / company**  
- Your remaining COGS: mainly **Harvest API** (keep this in your margin)  
- At 10k companies/month ≈ **$800** gross to you before Harvest

### Alternative launch ladder

| Phase | Price / row | When |
|---|---|---|
| Launch | **$0.08** ($80/1k) | First reviews, Spain-focused |
| Standard | **$0.10** ($100/1k) | After stable quality |
| Premium | **$0.12–0.15** | If you add multi-country denylists / higher fill rate |

Do **not** use rental (sunset Apr–Oct 2026). Prefer PPE.

### Free-tier policy (transparent)
- Allow small demo runs (e.g. max 5 companies) **or** rely on Apify free plan limits.  
- State clearly in README: “Production enrichment requires an Apify paid plan + this Actor’s PPE charges.”

---

## 3) How money flows (user → Apify → you)

```text
End user (paid Apify plan)
   │  pays prepaid usage / invoice on Apify
   ▼
Apify Console
   │  charges PPE events + (optional) platform usage
   │  keeps ~20% marketplace share
   ▼
Your profit = 0.8 × PPE revenue  −  (platform usage you absorb*)
   │  *0 if you “pass usage to user”
   ▼
Monthly payout (invoice ~11th of next month)
   │  PayPal / Wise (min ~$20) or bank transfer (min ~$100)
   ▼
Your payout method in Console
```

### Where to configure

1. [Apify Console](https://console.apify.com/) → **Settings → Billing**  
   - Add billing / tax identity  
   - Identity verification (required for payouts)  
2. Same area → **Payout method** (PayPal, Wise, or bank)  
3. **Your Actor → Publication → Monetization → Set up monetization**  
   - Model: **Pay per event**  
   - Primary event: dataset item @ **$0.10**  
   - Toggle: **Pass platform usage to users**  
4. Analytics: **Development → Insights → Analytics** (revenue, cost/1k, profit)

Docs:  
- https://docs.apify.com/platform/actors/publishing/monetize  
- https://docs.apify.com/platform/actors/publishing/monetize/monthly-payouts  
- https://docs.apify.com/platform/actors/publishing/monetize/pay-per-event  

You never collect the end-user card yourself. **Apify is the merchant of record**; they pay you.

---

## 2) Store profile checklist (screens, data, instructions)

### Files in this repo
| File | Use |
|---|---|
| `store/example_input.json` | Console “Example input” + README |
| `store/example_output.json` | Screenshot of Dataset tab / docs |
| `store/screenshot_mockup.html` | Open in browser → capture 3 Store screenshots |
| `.actor/dataset_schema.json` | Output field documentation in Store |
| `.actor/actor.json` | Title + description |

### Screenshots to upload (Publication → Images)
Open `store/screenshot_mockup.html` locally and capture:

1. **Hero / value** — title + “1 legal name → LinkedIn + website + domain”  
2. **Input** — companies JSON with legal names  
3. **Output table** — dataset columns: legal_name, linkedin_url, website, domain, match_status, confidence  

Also run a real Console run and screenshot:
4. Run detail (Succeeded)  
5. Dataset preview with Willis / Albrok / Telefónica  

Recommended image size: 1280×720 or similar landscape.

### README sections Apify expects
- What it does / who it’s for  
- Input / output examples  
- Pricing  
- Limitations (Spain-strong; directories vary by country)  
- Secrets: `APIFY_TOKEN`, `HARVEST_API_KEY` (document that publisher may embed keys for Store users — **or** require BYO keys; decide before publish)

### Critical product decision before publish
**Who pays for Harvest + nested Google?**

| Option | Pros | Cons |
|---|---|---|
| **A. You embed keys** (recommended for Store UX) | One-click runs | You must price COGS into PPE; abuse risk → set max items / memory |
| **B. User BYO keys** | Lower your COGS risk | Worse conversion; more support |

Recommendation for Store: **A + pass Apify platform usage + PPE $0.10**, with `maxItems`-style limits via input validation if needed.

---

## Publication wizard steps (order)

1. Finish identity verification + payout method  
2. Rename Actor + paste title/description from this file  
3. Upload 3–5 screenshots  
4. Set README (repo README is fine once Store section is included)  
5. Monetization → PPE → $0.10 / dataset item → pass usage  
6. Publish to Store (Public)  
7. Share: LinkedIn, Reddit r/apify, Product Hunt, outbound to agencies doing ES lead-gen  

---

## Honest limitations (put in README)

- Strongest quality on **Spanish** SERPs / registries; other countries work but need denylist expansion.  
- Not a people scraper — **companies only**.  
- LinkedIn personal `/in/` profiles are ignored.  
- `partial` = website found, LinkedIn missing (still billable as a resolved row — be transparent).  
- Optional Maps / OpenAI increase cost; off by default.
