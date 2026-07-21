# Company Identity Resolver v2.1

Actor de Apify que recibe razones sociales, descubre candidatos mediante
Google, consulta el endpoint oficial HarvestAPI `Get Company` y devuelve
exactamente una fila consolidada por empresa.

## HarvestAPI implementado

```http
GET https://api.harvest-api.com/linkedin/company
X-API-Key: <HARVEST_API_KEY>

?url=https://www.linkedin.com/company/empresa/
```

El cliente admite también `universalName` y `search`, pero el flujo principal
usa `url`, porque Google ya ha encontrado una página candidata.

## Flujo

1. Dos búsquedas iniciales:
   - `"razón social" linkedin`
   - `"razón social" website`
2. Conserva títulos, snippets, posiciones y URLs.
3. Normaliza y deduplica páginas `/company/`.
4. Calcula un pre-score sin consumir Harvest.
5. Consulta Harvest únicamente para 1–3 candidatos plausibles.
6. Combina nombre, `universalName`, web, descripción, sede, ubicaciones,
   industrias, empleados, seguidores, actividad y verificación.
7. Ejecuta la tercera búsqueda por dominio solo si la confianza es baja.
8. Puede usar IA opcionalmente para resolver ambigüedades.
9. Publica una única fila por razón social.

## Secrets

Configura en Apify:

- `APIFY_TOKEN`
- `HARVEST_API_KEY`
- `OPENAI_API_KEY` — opcional.

El token de Apify compartido anteriormente debe revocarse y sustituirse.

## Entrada mínima

```json
{
  "queries": "Albrok Mediacion S.A.\nOtra Empresa S.L.",
  "max_harvest_candidates": 2,
  "debug": true
}
```

## Validación recomendada

Prueba primero 5–10 empresas conocidas con `debug=true` y revisa:

- `website_candidates`
- `candidates`
- `raw_harvest`
- `confidence`
- `evidence_summary`
- `match_status`

Los pesos del scoring deben calibrarse con resultados reales etiquetados antes
de automatizar decisiones irreversibles a gran escala.
