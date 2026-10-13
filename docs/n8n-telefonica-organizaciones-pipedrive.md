# NocoDB organizaciones → Pipedrive (Telefónica Seguros)

## Workflows n8n

### Producción (activo, polling)

- **Nombre:** `TefSeguros NocoDB OK → Pipedrive Push`
- Creado/actualizado con `scripts/create_dedicated_enrich_workflow.py`
- **Cada 5 minutos** busca filas con `pipedrive_status = ok` y las procesa
- Webhook POST (mismo flujo): `{N8N_URL}/webhook/telefonica-org-pipedrive-push` (requiere workflow **activo**)

**Importante:** marcar `ok` en NocoDB **no** ejecuta n8n por sí solo. Hace falta este workflow activo (poll) o un webhook NocoDB → URL anterior.

### Legacy (inactivo)

- **ID:** `YEiosPHh8GxGSY64` — incluye supresiones + rama manual; dejar **inactivo** para no lanzar el cron de clientes Pipedrive.

## NocoDB

- Tabla: `telefonica-seguros_organizaciones` (`mewh1ynmcokfsfi`)
- Filtro: `confidence > 60` y `pipedrive_status = ok`
- Tras éxito: `update_pipedrive` (ISO) y `pipedrive_status = synced`
- **Pipedrive prevalece:** antes de cada sync se hace `GET` de la organización. **Solo** se escribe un campo si en Pipedrive está **vacío** y en NocoDB hay valor. Si Pipedrive ya tiene dato (aunque sea distinto al de NocoDB), **no se toca** y no hay `PUT` para ese campo. Si no hay ningún campo vacío que rellenar, **no hay actualización en Pipedrive** (solo marca `synced` en NocoDB). **No** se crean notas.

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
| `headquarters_text` | Localidad / Provincia (parse simple) |
| `match_status`, `relationship`, `evidence_summary` | Solo en NocoDB (no se envían a Pipedrive) |

`industry` no se envía: Pipedrive solo acepta valores de su lista de opciones.

## Mantenimiento en repo

- `scripts/n8n_push_organizaciones_code.js` — código del nodo Code
- `scripts/patch_n8n_workflow_organizaciones.py` — publicar cambios vía API (`N8N_REST_API_KEY`, `N8N_URL`)
- `scripts/test_organizaciones_push_once.py` — prueba de una fila con `pipedrive_status=ok`

## Uso

1. Marcar filas con `pipedrive_status = ok`.
2. En n8n, ejecutar **Push Organizaciones (Manual)** (workflow puede permanecer inactivo para no lanzar el cron de supresiones).
3. Revisar ejecución y columnas `update_pipedrive` / `synced`.
