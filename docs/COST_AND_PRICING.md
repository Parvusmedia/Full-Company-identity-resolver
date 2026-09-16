# Coste de enriquecimiento y pricing al cliente

Análisis del **coste real (COGS)** de resolver **1 empresa completa** con el Actor
`full-company-identity-resolver`, escenarios de consumo, comisión de marketplace
Apify y precio recomendado al cliente.

El modelo vivo está en `my_actor/cost_model.py` (ejecutar: `python -m my_actor.cost_model`).

> Precios de proveedores revisados ~julio 2026. Son **tarifas de lista / Free**;
> planes Starter/Scale/Business de Apify suelen bajar el PPE de Google y Harvest.

---

## 1. Qué consume el flujo por empresa

| Paso | Proveedor | Unidad de coste |
|------|-----------|-----------------|
| Descubrimiento LinkedIn + web | `apify/google-search-scraper` | 1 evento `search-page-scraped` por query (1 página SERP) |
| Enrich LinkedIn company | HarvestAPI `GET /linkedin/company` | 1 llamada por URL candidata |
| Desambiguación (opcional) | OpenAI `gpt-4o-mini` | 1 chat completion |
| Orquestación | Apify CU del Actor propio | RAM × tiempo (amortizado por empresa) |

Código de referencia: `resolver.py` → Google batch → Harvest top N → fallback dominio → AI opcional.

### Knobs que mueven el gasto

| Parámetro | Default | Techo |
|-----------|---------|-------|
| Queries Google iniciales | 2 o 3 (si hay forma jurídica distinta del core) | 3 |
| `max_harvest_candidates` | 2 | 5 |
| `fallback_google_by_website` | true | +1 query + Harvest de URLs nuevas |
| `use_ai_for_ambiguous` | false | +1 llamada OpenAI si confianza &lt; 78 |

---

## 2. Costes unitarios (lo que pagamos nosotros)

| Concepto | Tarifa usada | $/unidad |
|----------|--------------|----------|
| Google SERP page (`apify/google-search-scraper`) | from **$1.80 / 1.000** pages | **$0.0018** |
| Harvest company | **~$4 / 1.000** (lista Apify/Harvest; usamos el extremo conservador) | **$0.0040** |
| OpenAI gpt-4o-mini (1 desambiguación corta) | $0.15/1M in + $0.60/1M out | **~$0.0006** |
| Compute Actor propio (batch amortizado) | ~0.01 CU @ $0.20/CU | **~$0.0020** |

Notas:

- El Google scraper oficial es **PPE**: no se cobra CU aparte de ese Actor; pagas el evento.
- Harvest en este repo va por **API directa** (`api.harvest-api.com`); el precio de referencia
  público alineado es el del Actor Harvest en Store (**from $3 / 1k**, README habla de **$4 / 1k**).
- OpenAI es irrelevante frente a Harvest/Google (&lt;2 % del peor caso).

---

## 3. Escenarios por 1 empresa

| Escenario | Google | Harvest | AI | **COGS estimado** | Cuándo ocurre |
|-----------|--------|---------|----|-------------------|-----------------|
| **Mínimo** | 2 | 2 | 0 | **~$0.014** | Nombre = core; match claro |
| **Estándar** (defaults) | 3 | 2 | 0 | **~$0.015** | Camino feliz típico ES |
| **Con fallback** | 4 | 4 | 0 | **~$0.025** | Confianza &lt; 78 + dominio |
| **Agresivo** | 4 | 8 | 0 | **~$0.042** | `max_harvest=5` + fallback |
| **Peor caso** | 4 | 10 | 1 | **~$0.050** | Techo código + AI on |

Desglose del **peor caso (~$0.050)**:

| Partida | Cálculo | USD |
|---------|---------|-----|
| Google | 4 × $0.0018 | $0.0072 |
| Harvest | 10 × $0.0040 | $0.0400 |
| OpenAI | 1 × $0.0006 | $0.0006 |
| Compute | fijo | $0.0020 |
| **Total** | | **$0.0498** |

**Conclusión operativa:** el coste lo marca sobre todo **Harvest** (número de candidatos enriquecidos). Google es barato; la AI casi no pesa.

### Mix realista (para P&L)

Si el 70 % cae en estándar, 25 % en fallback y 5 % en agresivo/peor:

`0.70×0.015 + 0.25×0.025 + 0.05×0.050 ≈ **$0.019 / empresa**` (blended).

Usar el **peor caso** para fijar precio de producto; el blended para forecast de margen.

---

## 4. Comisión marketplace Apify

Si vendéis el Actor en **Apify Store con Pay-per-event (PPE)**:

```text
profit = (0.8 × revenue_cliente) − platform_costs
```

- Apify se queda **20 %** del precio de eventos que cobráis al cliente.
- `platform_costs` = lo que vosotros gastáis (Google PPE + Harvest + CU + OpenAI).
- Solo cuentan usuarios en planes de pago de Apify para el profit del developer.

**Break-even** (beneficio cero en el diseño de coste `C`):

```text
P_be = C / 0.8
```

Para peor caso: `$0.05 / 0.8 ≈ **$0.0625**` por empresa.

**Precio con margen neto objetivo `m`** (margen sobre lo que *vosotros* retenéis tras el 20 %):

```text
P = C / (0.8 × (1 − m))
```

| Margen neto deseado | Precio cliente (anclado a peor caso $0.05) |
|---------------------|-------------------------------------------|
| 0 % (break-even) | **$0.063** |
| 30 % | **$0.089** |
| **40 %** (recomendado) | **~$0.104 → lista $0.10–$0.12** |
| 50 % | **$0.125** |

Si vendéis **fuera de Apify** (API propia / SaaS): no hay el 20 % de Store sobre vuestro fee,
pero seguís pagando Google/Harvest/CU. Entonces `P = C / (1 − m)` → con m=40 % y C=$0.05 → **~$0.083**.

---

## 5. Precio recomendado al cliente

### Recomendación principal (Apify Store PPE)

| Concepto | Valor |
|----------|-------|
| Ancla de coste | **Peor caso ~$0.05** |
| Comisión Apify | **20 %** |
| Margen neto objetivo | **40 %** sobre lo retenido |
| **Precio lista** | **$0.10 – $0.12 por empresa resuelta** |
| Evento PPE sugerido | `company-resolved` (1 charge por fila de dataset) |

Con **$0.12 / empresa**:

| Métrica | Cálculo | Resultado |
|---------|---------|-----------|
| Ingreso bruto cliente | | $0.120 |
| Tras comisión Apify (80 %) | 0.8 × 0.12 | $0.096 |
| COGS peor caso | | $0.050 |
| **Beneficio neto peor caso** | 0.096 − 0.050 | **$0.046 (~48 %)** |
| COGS estándar | | $0.015 |
| **Beneficio neto estándar** | 0.096 − 0.015 | **$0.081 (~84 %)** |

### Escalones comerciales

| Tier | Precio / empresa | Uso |
|------|------------------|-----|
| Volume / early | **$0.08** | Cubierto si el mix es mayoritariamente estándar/fallback; apurado en peor caso |
| **Standard (recomendado)** | **$0.10–$0.12** | Cubre peor caso + ~40 % margen + buffer de subidas de tarifa |
| Premium (AI siempre / harvest 5) | **$0.15–$0.18** | Si activáis AI por defecto o `max_harvest=5` de forma habitual |

### Packs orientativos (lista $0.12)

| Volumen | Precio pack | vs unitario |
|---------|-------------|-------------|
| 1.000 empresas | $120 | lista |
| 10.000 | $1.000 ($0.10/u) | −17 % |
| 50.000 | $4.500 ($0.09/u) | −25 % |

A $0.09 unitario, peor caso sigue en beneficio (~$0.022 neto tras comisión).

---

## 6. Sensibilidad y riesgos

1. **Subida Harvest** a $6/1k → peor caso ≈ $0.07 → subir lista a **$0.15**.
2. **`max_harvest_candidates=5` por defecto** → COGS medio sube fuerte; no bajar precio sin medir.
3. **Batches pequeños** (1 empresa / run) → más CU de arranque; el start fee del Google Actor es despreciable si batcheáis queries (`batch_size=20`).
4. **Reintentos / fallos** hoy no reintentan en código; si se añaden retries, multiplicar Google/Harvest en el modelo.
5. **Planes Apify altos** bajan el PPE de Google (Store discounts): mejora COGS, no bajar precio al cliente hasta ver factura real.

---

## 7. Checklist para publicar en Apify Store

1. Evento primario: `company-resolved` @ **$0.12** (o `apify-default-dataset-item` al mismo precio).
2. Mantener `apify-actor-start` sintético (cubre ~5 s de compute).
3. Limitar `maxMemoryMbytes` (Actor HTTP ligero: 512–1024 MB).
4. Medir 100–500 runs reales → sustituir estimaciones de este doc por media/P95 de factura.
5. Revisar `UNIT_COSTS_USD` en `cost_model.py` cada trimestre.

---

## 8. Cómo regenerar los números

```bash
python -m my_actor.cost_model
python -m unittest tests.test_cost_model -v
```
