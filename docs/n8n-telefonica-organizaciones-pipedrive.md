# NocoDB organizaciones → Pipedrive (Telefónica Seguros)

## Workflows n8n

### Producción (activo, polling)

- **Nombre:** `TefSeguros NocoDB OK → Pipedrive Push`
- **ID:** `7A1xSnh6x5QeynjU`
- Creado/actualizado con `scripts/create_dedicated_enrich_workflow.py`
- **Cada 5 minutos** busca filas con `pipedrive_status = ok` y las procesa
- Webhook POST (mismo flujo): `{N8N_URL}/webhook/telefonica-org-pipedrive-push` (requiere workflow **activo**)
- Una ejecución procesa hasta **50** filas, una detrás de otra, con un presupuesto de 4 minutos
- Si llegan varios webhooks a la vez, solo sigue la ejecución más antigua. Las demás salen al momento, sin leer Noco ni escribir en Pipedrive

Marcar 50 filas en `ok` puede disparar 50 webhooks. No hace falta espaciarlos: el resto de ejecuciones no llama a Pipedrive. Las que no quepan en esa pasada siguen en `ok` y las recoge la siguiente.

### Legacy (inactivo)

- **ID:** `YEiosPHh8GxGSY64` — incluye supresiones + rama manual; dejar **inactivo** para no lanzar el cron de clientes Pipedrive.

## NocoDB

- Tabla: `telefonica-seguros_organizaciones` (`mewh1ynmcokfsfi`)
- Filtro: `confidence > 60` y `pipedrive_status = ok`
- Tras éxito: `update_pipedrive` (ISO) y `pipedrive_status = synced`
- Si Pipedrive rechaza la organización, `pipedrive_status` pasa a ser el código HTTP (`400`, `404`, …) y `error` guarda el motivo. Esa fila deja de estar en `ok` y no se reintenta sola. Para volver a lanzarla, hay que ponerla otra vez en `ok`.
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
| fecha del sync (Europe/Madrid, `AAAA-MM-DD`) | Fecha_enriquecimiento |
| `headquarters_text` | Localidad / Provincia (parse simple) |
| `industry` | Sector (`industry`), solo si el texto cae en una opción de Pipedrive |
| `match_status`, `relationship`, `evidence_summary` | Solo en NocoDB (no se envían a Pipedrive) |

`Fecha_enriquecimiento` no copia `enriched_at` de NocoDB. Es la fecha (zona Europe/Madrid) en la que el sync escribe datos de enriquecimiento. Pipedrive la guarda como fecha `AAAA-MM-DD` y la muestra en el formato de la cuenta, por ejemplo `13/10/2026`. Si el campo ya tiene fecha, no se pisa.

## Sector

Pipedrive no acepta texto libre en Sector. El campo es un enum de 20 opciones y la API guarda el **id** (por ejemplo `8` = Servicios financieros).

En el sync, `mapIndustry` normaliza el valor de NocoDB (minúsculas, sin acentos, `&` → `and`) y lo busca en:

1. La taxonomía LinkedIn v2, subiendo cada industria a su raíz (esas 20 raíces son las opciones de Pipedrive).
2. Alias de etiquetas LinkedIn v1 que ya no existen en v2 (`scripts/data/industry_legacy_aliases.json`).
3. Las etiquetas en inglés y en español de las propias opciones de Pipedrive.

Ejemplo: `Insurance`, `Insurance Carriers` y `Banking` → `8` Servicios financieros.

Si no hay correspondencia, **no se envía** `industry` (un texto libre haría fallar el PUT) y el resto de campos sí se sincroniza. La ejecución deja `industry_sync: "unmapped"` en la fila y el recuento en `industry_unmapped`. Un sector que Pipedrive ya tiene no se pisa.

## Directorios

`alimarket.es` y `https://www.linkedin.com/company/publicaciones-alimarket-s.a./` no son la empresa. Tampoco lo son otros directorios o medios que se cuelan igual (Construnews, Iberinform, IDAE, Doctoralia, prensa). Si una fila `ok` trae esa web, ese dominio, una ficha `/empresa/` o ese LinkedIn, el sync no escribe en Pipedrive: borra el enrich en NocoDB, deja `confidence` en 15 y `enrichment_status = rejected_directory`.

Para cubrir una etiqueta nueva: añadir el alias normalizado en `industry_legacy_aliases.json` y ejecutar `python3 scripts/build_industry_map.py`.

## Mantenimiento en repo

- `scripts/n8n_push_organizaciones_code.js` — código del nodo Code
- `scripts/patch_n8n_workflow_organizaciones.py` — publicar cambios vía API (`N8N_REST_API_KEY`, `N8N_URL`)
- `scripts/test_organizaciones_push_once.py` — prueba de una fila con `pipedrive_status=ok`

## Uso

1. Marcar filas con `pipedrive_status = ok`.
2. En n8n, ejecutar **Push Organizaciones (Manual)** (workflow puede permanecer inactivo para no lanzar el cron de supresiones).
3. Revisar ejecución y columnas `update_pipedrive` / `synced`.
