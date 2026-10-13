# NocoDB organizaciones → Pipedrive (Telefónica Seguros)

## Workflow n8n

- **ID:** `YEiosPHh8GxGSY64`
- **URL:** https://pmedia.app.n8n.cloud/workflow/YEiosPHh8GxGSY64
- **Rama nueva:** `Push Organizaciones (Manual)` / `Push Organizaciones (Every 2h)` → `config_enrich_push` → `Push Enriched Organizaciones to Pipedrive` (independiente del cron de supresiones en `config1`)

La rama histórica (Pipedrive → `suppression_entities`) no se elimina.

## NocoDB

- Tabla: `telefonica-seguros_organizaciones` (`mewh1ynmcokfsfi`)
- Filtro: `confidence > 60` y `pipedrive_status = ok`
- Tras éxito: `update_pipedrive` (ISO) y `pipedrive_status = synced`

## ID organización

`pipedrive_org_id` si existe; si no, `source_id`. **No usar `source_id` solo** si difiere del ID real en Pipedrive.

## Campos Pipedrive

| NocoDB | Pipedrive |
|--------|-----------|
| `linkedin_url` | Perfil de LinkedIn |
| `website` / `domain` | Sitio web |
| `commercial_name` | Nombre Comercial |
| `confidence` | Confianza_enriquecimiento |
| `employee_count` | Empleados |
| `followers` | Linkedin_followers |
| `enriched_at` | Fecha_enriquecimiento |
| `headquarters_text` | Localidad / Provincia (parse simple) o nota |
| `match_status`, `relationship`, `evidence_summary` | Nota de organización |

`industry` no se envía: Pipedrive solo acepta valores de su lista de opciones.

## Mantenimiento en repo

- `scripts/n8n_push_organizaciones_code.js` — código del nodo Code
- `scripts/patch_n8n_workflow_organizaciones.py` — publicar cambios vía API (`N8N_REST_API_KEY`, `N8N_URL`)
- `scripts/test_organizaciones_push_once.py` — prueba de una fila con `pipedrive_status=ok`

## Uso

1. Marcar filas con `pipedrive_status = ok`.
2. En n8n, ejecutar **Push Organizaciones (Manual)** (workflow puede permanecer inactivo para no lanzar el cron de supresiones).
3. Revisar ejecución y columnas `update_pipedrive` / `synced`.
