# Referencia de rollback: pipeline Google → Harvest-por-URL

Este documento congela **cómo resolvía identidad el actor antes de los fallbacks
de descubrimiento** (Harvest `search` + scrape de LinkedIn en la homepage).

Si el cambio no aporta (más falsos positivos, poco lift en `confidence<50`),
volver a este comportamiento **sin reescribir scoring**.

## Punto de restauración

| Qué | Valor |
|---|---|
| Commit de referencia | `6622d3b` (`Harden identity confidence against directory and homonym matches`) |
| Rama | `cursor/identity-score-hardening-644a` |
| PR de scoring | https://github.com/Parvusmedia/Full-Company-identity-resolver/pull/7 |

Opciones, de menos a más invasiva:

1. **Flags (preferido).** En el input del Actor:
   ```json
   {
     "fallback_harvest_search": false,
     "fallback_homepage_linkedin": false,
     "fallback_google_by_website": true
   }
   ```
   El código de descubrimiento no se ejecuta. El flujo queda como esta ficha.
2. **Revert del commit de discovery** sobre la rama de scoring, manteniendo
   techos de identidad (PR #7).
3. **Checkout** de `6622d3b` solo si hay que abandonar también el código nuevo.

No hace falta tocar NocoDB para “apagar” discovery: el siguiente run ya no
busca por `search` ni scrape de homepage.

## Flujo que hay que preservar (esta ficha)

Por cada `legal_name`:

1. Google (Apify `apify/google-search-scraper`), **sin Maps**:
   - `"RAZÓN SOCIAL" linkedin`
   - `"RAZÓN SOCIAL" website`
   - opcional `"CORE" linkedin` si el core (sin forma jurídica) es distinto
2. Filtrar solo `linkedin.com/company/*`, normalizar, deduplicar.
3. Pre-score barato → HarvestAPI **solo por `url`** de los top N candidatos
   (`GET /linkedin/company?url=`).
   **No** se usa `search` ni `universalName`.
4. Score final (identidad endurecida: techos 39/77, veto de directorios).
5. Si `confidence < fallback_confidence_threshold` (78): tercera query Google
   `site:linkedin.com/company "dominio"` y otra pasada Harvest-por-URL.
6. OpenAI opcional, apagado por defecto.

Si Google no devuelve `/company/`, Harvest **no se llama**. Ese es el hueco
que cubren los fallbacks nuevos.

## Qué no forma parte de esta ficha

- Techos de identidad, veto de Alimarket/TripAdvisor, mix de `token_set_ratio`
  (eso es PR #7, se mantiene al desactivar flags).
- Escritura NocoDB / Plan B de secretos.

## Cómo comprobar que se ha vuelto al modo actual

En un run de debug, `harvest_queries_used` solo contiene URLs
`https://www.linkedin.com/company/...`. No debe haber entradas
`search:…` ni `homepage:…`.
