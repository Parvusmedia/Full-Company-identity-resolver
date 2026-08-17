# Plan B: secretos de enriquecimiento vía n8n Variables

Por defecto, **siempre** debe existir este camino. El Plan A (secrets del environment de Cursor) es más directo, pero falla si el agente arranca sin environment o si Cursor no inyecta secretos de scope Environment.

Los valores **nunca** se commitean, se pegan en chats ni se imprimen en logs.

## Qué hay que tener en n8n

Instancia: `https://pmedia.app.n8n.cloud`

| Variable n8n | Uso |
|---|---|
| `APIFY_TOKEN` | Google Search Actor |
| `HARVEST_API_KEY` | HarvestAPI LinkedIn company |
| `NOCO_TOKEN` | NocoDB (`xc-token`) |

`NOCO_BASE` no es secreto. Valor operativo: `https://mpa.parvusmedia.com`.

Fuente de verdad: **Variables de n8n** (Settings → Variables), no Credentials ni Data Tables. La API pública de Data Tables no está disponible en esta instancia (`GET /api/v1/data-tables` → 404).

Workflow de apoyo (lee `$vars` y está marcado `availableInMCP`):

- Nombre: `cursor-secrets-vault`
- ID: `ptG1eDRElM5ietbu`
- URL: <https://pmedia.app.n8n.cloud/workflow/ptG1eDRElM5ietbu>

No hace falta ejecutarlo si hay clave REST: el loader llama a `/api/v1/variables`.

## Dos tokens n8n distintos

| Nombre en Cursor | JWT `aud` | Para qué sirve | Lee Variables? |
|---|---|---|---|
| `N8N_API_KEY` | `mcp-server-api` | MCP (buscar/ejecutar workflows) | **No** |
| `N8N_REST_API_KEY` | `public-api` | REST `X-N8N-API-KEY` | **Sí** |
| `N8N_URL` | — | Host n8n | — |

Sin `N8N_REST_API_KEY` (scope **Personal** en Cursor), el Plan B no funciona. No reutilices la clave MCP como REST.

Crear la REST key en n8n: Settings → API → Create API Key, scopes de lectura de variables (`variable:list` / equivalentes). Guardarla en Cursor como secreto **Personal** `N8N_REST_API_KEY`, tipo Runtime Secret.

## Cómo debe arrancar un agente

1. **Plan A:** Run on → Cloud + environment `Parvusmedia/Full-Company-identity-resolver`. Deben inyectarse `NOCO_TOKEN`, `APIFY_TOKEN`, `HARVEST_API_KEY`.
2. **Plan B (obligatorio como fallback):** el agente comprueba presencia (sin imprimir valores). Si falta alguno:

```bash
python3 scripts/load_n8n_vars.py
```

Eso hace `GET https://pmedia.app.n8n.cloud/api/v1/variables` con `N8N_REST_API_KEY` y exporta a `os.environ` solo las claves de `WANTED`. Salida típica:

```text
APIFY_TOKEN: SET
HARVEST_API_KEY: SET
NOCO_TOKEN: SET
Plan B OK (values not printed)
```

Desde Python:

```python
from scripts.load_n8n_vars import load_n8n_vars

flags = load_n8n_vars()  # {name: bool} — nunca los valores
```

3. Si Plan A y Plan B fallan: no inventar tokens y no pedir que se peguen en el chat. Pedir `N8N_REST_API_KEY` Personal en Cursor o relanzar con el environment.

## Orden de resolución

1. Variable ya inyectada en el entorno (Plan A) → se deja.
2. Si falta → n8n Variables (Plan B).
3. `N8N_API_KEY` con `aud=mcp-server-api` se ignora para este GET.

## NocoDB (contexto operativo)

- Base: `https://mpa.parvusmedia.com`
- Tabla organizaciones: `mewh1ynmcokfsfi`
- Universo `existing_customer`: `suppression_entities` (`m29pd9rqgfm3agu`), `reason=existing_customer`
- No tocar el registro diferido `source_id=2632`

## Qué no hacer

- No guardar tokens en git, `.env` commiteado, ni en el workflow como texto plano.
- No imprimir valores, JWT ni `xc-token`.
- No usar el token MCP contra `/api/v1/variables` (401).
- No duplicar un lote de enriquecimiento en dos agentes a la vez.
