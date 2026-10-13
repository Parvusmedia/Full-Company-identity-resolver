// n8n Code Node — Push telefonica-seguros_organizaciones → Pipedrive
// Mode: Run Once for All Items

const PD_KEYS = {
  commercial_name: 'ad92da1357d2612b282574a28ea8d5f18e09b13a',
  confidence: '628cc21653e5dca37e601419181fb80749078d08',
  employees: 'e55be59bd4c78ea7f813a11cabad9923b88cd00c',
  followers: 'a299f56478797e7f5bc6fbdd16665f54e99c03c4',
  enriched_at: 'f0d998fd9c76c525ff78cd4eb3795bfdc55312b7',
  locality: '1b2e98a01d96b81cfaa6de62322c3d61fc76e8c1',
  province: '29f32f4d646e1bf02a89a15c3a180201a3c783d0',
};

function toPositiveInt(value, fallback) {
  const num = Number(value);
  return Number.isFinite(num) && num > 0 ? Math.floor(num) : fallback;
}

function getRecords(resp) {
  if (!resp) return [];
  if (Array.isArray(resp.list)) return resp.list;
  if (Array.isArray(resp.records)) return resp.records;
  return [];
}

function resolveWebsite(row) {
  const website = String(row.website || '').trim();
  if (website) return website;
  const domain = String(row.domain || '').trim();
  if (!domain) return '';
  if (domain.includes('://')) return domain;
  return `https://${domain}`;
}

function parseHeadquarters(text) {
  const raw = String(text || '').trim();
  if (!raw) return { locality: '', province: '' };
  const parts = raw.split(/[,;|]/).map((p) => p.trim()).filter(Boolean);
  if (parts.length >= 2) {
    return { locality: parts[0], province: parts[parts.length - 1] };
  }
  return { locality: raw, province: '' };
}

function toPipedriveDate(value) {
  const raw = String(value || '').trim();
  if (!raw) return new Date().toISOString().slice(0, 10);
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return new Date().toISOString().slice(0, 10);
  return d.toISOString().slice(0, 10);
}

function orgIdFromRow(row) {
  const a = String(row.pipedrive_org_id || '').trim();
  const b = String(row.source_id || '').trim();
  const pick = a || b;
  if (!pick) return null;
  const num = Number(pick);
  return Number.isFinite(num) && num > 0 ? Math.floor(num) : null;
}

function buildNoteContent(row, hqExtra) {
  const lines = [
    '[Enriquecimiento identity resolver]',
    `match_status: ${row.match_status || ''}`,
    `relationship: ${row.relationship || ''}`,
    `evidence_summary: ${row.evidence_summary || ''}`,
  ];
  if (hqExtra) lines.push(`headquarters_text: ${hqExtra}`);
  lines.push(`synced_at: ${new Date().toISOString()}`);
  return lines.join('\n');
}

function isPdValueEmpty(value) {
  if (value === null || value === undefined) return true;
  if (typeof value === 'string') return value.trim() === '';
  if (typeof value === 'number' && Number.isNaN(value)) return true;
  return false;
}

/** Keep only fields that are empty in the current Pipedrive organization. */
function filterPayloadEmptyOnly(existingOrg, desiredPayload) {
  const filtered = {};
  const skipped = [];
  for (const [key, newValue] of Object.entries(desiredPayload)) {
    const current = existingOrg ? existingOrg[key] : undefined;
    if (isPdValueEmpty(current)) {
      filtered[key] = newValue;
    } else {
      skipped.push(key);
    }
  }
  return { payload: filtered, skipped };
}

function buildDesiredPayload(row) {
  const payload = {};
  const linkedin = String(row.linkedin_url || '').trim();
  if (linkedin) payload.linkedin = linkedin;

  const website = resolveWebsite(row);
  if (website) payload.website = website;

  // industry omitted: Pipedrive rejects free-text values not in org field options.

  const commercial = String(row.commercial_name || '').trim();
  if (commercial) payload[PD_KEYS.commercial_name] = commercial;

  if (row.confidence !== null && row.confidence !== undefined && row.confidence !== '') {
    payload[PD_KEYS.confidence] = Number(row.confidence);
  }
  if (row.employee_count !== null && row.employee_count !== undefined && row.employee_count !== '') {
    payload[PD_KEYS.employees] = Number(row.employee_count);
  }
  if (row.followers !== null && row.followers !== undefined && row.followers !== '') {
    payload[PD_KEYS.followers] = Number(row.followers);
  }

  payload[PD_KEYS.enriched_at] = toPipedriveDate(row.enriched_at);

  const hq = parseHeadquarters(row.headquarters_text);
  let hqExtra = '';
  if (hq.locality) payload[PD_KEYS.locality] = hq.locality;
  if (hq.province) payload[PD_KEYS.province] = hq.province;
  if (row.headquarters_text && !hq.locality && !hq.province) {
    hqExtra = String(row.headquarters_text);
  }

  const phone = String(row.phone || '').trim();
  if (phone) payload.phone = phone;

  return { payload, hqExtra };
}

async function fetchOrganization(context, pdBase, pdToken, orgId) {
  const res = await context.helpers.httpRequest({
    method: 'GET',
    url: `${pdBase}/organizations/${orgId}`,
    qs: { api_token: pdToken },
    json: true,
  });
  if (!res.success || !res.data) {
    throw new Error(res.error || res.error_info || 'Pipedrive get organization failed');
  }
  return res.data;
}

const cfg = $('config_enrich_push').first().json;
const pdToken = cfg.pipedrive_api_token;
const pdBase = String(cfg.pipedrive_api_base || 'https://api.pipedrive.com/v1').replace(/\/$/, '');
const ncBase = String(cfg.nocodb_base_url || '').replace(/\/$/, '');
const ncToken = cfg.nocodb_api_token;
const tableId = cfg.nocodb_organizaciones_table_id || 'mewh1ynmcokfsfi';
const maxRows = toPositiveInt(cfg.enrich_push_max_rows_per_run, 15);
const timeBudgetMs = toPositiveInt(cfg.code_time_budget_ms, 45000);

if (!pdToken || !ncToken || !tableId) {
  throw new Error('Missing pipedrive_api_token, nocodb_api_token, or nocodb_organizaciones_table_id in config_enrich_push');
}

const startedAt = Date.now();
const where = '(confidence,gt,60)~and(pipedrive_status,eq,ok)';
const ncHeaders = { 'xc-token': ncToken, 'Content-Type': 'application/json' };

const listResp = await this.helpers.httpRequest({
  method: 'GET',
  url: `${ncBase}/api/v2/tables/${tableId}/records`,
  qs: { where, limit: maxRows, offset: 0 },
  headers: { 'xc-token': ncToken },
  json: true,
});

const rows = getRecords(listResp);
const results = [];
let processed = 0;

for (const row of rows) {
  if (Date.now() - startedAt > timeBudgetMs) {
    results.push({ Id: row.Id, status: 'skipped', reason: 'time_budget' });
    break;
  }

  const orgId = orgIdFromRow(row);
  if (!orgId) {
    results.push({ Id: row.Id, status: 'error', reason: 'missing_org_id' });
    continue;
  }

  const { payload: desiredPayload, hqExtra } = buildDesiredPayload(row);

  try {
    const existingOrg = await fetchOrganization(this, pdBase, pdToken, orgId);
    const { payload, skipped } = filterPayloadEmptyOnly(existingOrg, desiredPayload);
    const fieldsWritten = Object.keys(payload).length;

    if (fieldsWritten > 0) {
      const updateRes = await this.helpers.httpRequest({
        method: 'PUT',
        url: `${pdBase}/organizations/${orgId}`,
        qs: { api_token: pdToken },
        body: payload,
        json: true,
      });

      if (!updateRes.success) {
        throw new Error(updateRes.error || updateRes.error_info || 'Pipedrive update failed');
      }

      const noteContent = buildNoteContent(row, hqExtra);
      await this.helpers.httpRequest({
        method: 'POST',
        url: `${pdBase}/notes`,
        qs: { api_token: pdToken },
        body: { content: noteContent, org_id: orgId },
        json: true,
      });
    }

    const syncedAt = new Date().toISOString();
    await this.helpers.httpRequest({
      method: 'PATCH',
      url: `${ncBase}/api/v2/tables/${tableId}/records`,
      headers: ncHeaders,
      body: [{ Id: row.Id, update_pipedrive: syncedAt, pipedrive_status: 'synced' }],
      json: true,
    });

    results.push({
      Id: row.Id,
      org_id: orgId,
      status: fieldsWritten > 0 ? 'synced' : 'synced_no_changes',
      fields_written: fieldsWritten,
      fields_skipped_existing: skipped,
      update_pipedrive: syncedAt,
    });
    processed += 1;
  } catch (error) {
    results.push({ Id: row.Id, org_id: orgId, status: 'error', reason: error.message });
  }
}

return [{
  json: {
    candidates_fetched: rows.length,
    processed_ok: processed,
    results,
    filter_where: where,
    completed_at: new Date().toISOString(),
    timed_out: Date.now() - startedAt > timeBudgetMs,
  },
}];
