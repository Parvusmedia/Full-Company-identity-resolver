// n8n Code Node — Push telefonica-seguros_organizaciones → Pipedrive
// Mode: Run Once for All Items
//
// Regla: Pipedrive prevalece. GET org antes de escribir; por cada campo,
// solo PUT si el valor actual en Pipedrive está vacío y NocoDB trae dato.

const PD_KEYS = {
  commercial_name: 'ad92da1357d2612b282574a28ea8d5f18e09b13a',
  confidence: '628cc21653e5dca37e601419181fb80749078d08',
  employees: 'e55be59bd4c78ea7f813a11cabad9923b88cd00c',
  followers: 'a299f56478797e7f5bc6fbdd16665f54e99c03c4',
  enriched_at: 'f0d998fd9c76c525ff78cd4eb3795bfdc55312b7',
  locality: '1b2e98a01d96b81cfaa6de62322c3d61fc76e8c1',
  province: '29f32f4d646e1bf02a89a15c3a180201a3c783d0',
};

// INDUSTRY_MAP_START
const INDUSTRY_TO_PD = {"abrasives and nonmetallic minerals manufacturing":12,"accessible architecture and design":14,"accessible hardware manufacturing":12,"accommodation services":1,"accounting":14,"administracion publica":9,"administration of justice":9,"administrative and support services":2,"advertising services":14,"agricultura ganaderia y silvicultura":7,"agricultural chemical manufacturing":12,"agriculture construction mining machinery manufacturing":12,"air water and waste program management":9,"airlines and aviation":18,"alternative dispute resolution":14,"alternative fuel vehicle manufacturing":12,"alternative medicine":11,"ambulance services":11,"amusement parks and arcades":6,"animal feed manufacturing":12,"animation":17,"animation and post production":17,"apparel and fashion":12,"apparel manufacturing":12,"appliances electrical and electronics manufacturing":12,"architectural and structural metal manufacturing":12,"architecture and planning":14,"armed forces":9,"artificial rubber and synthetic fiber manufacturing":12,"artists and writers":6,"audio and video equipment manufacturing":12,"automation machinery manufacturing":12,"automotive":12,"aviation and aerospace component manufacturing":12,"baked goods manufacturing":12,"banking":8,"bars taverns and nightclubs":1,"bed and breakfasts hostels homestays":1,"beverage manufacturing":12,"biomass electric power generation":19,"biotechnology":14,"biotechnology research":14,"blockchain services":17,"blogs":17,"boilers tanks and shipping container manufacturing":12,"book and periodical publishing":17,"book publishing":17,"breweries":12,"broadcast media production and distribution":17,"building construction":3,"building equipment contractors":3,"building finishing contractors":3,"building materials":12,"building structure and exterior contractors":3,"business consulting and services":14,"business content":17,"business intelligence platforms":17,"business supplies and equipment":20,"cable and satellite programming":17,"capital markets":8,"caterers":1,"chemical manufacturing":12,"chemical raw materials manufacturing":12,"child day care services":11,"chiropractors":11,"circuses and magic shows":6,"civic and social organizations":4,"civil engineering":3,"claims adjusting actuarial services":8,"clay and refractory products manufacturing":12,"climate data and analytics":17,"climate technology product manufacturing":12,"coal mining":13,"collection agencies":2,"commercial and industrial equipment rental":15,"commercial and industrial machinery maintenance":4,"commercial and service industry machinery manufacturing":12,"commercial real estate":15,"communications equipment manufacturing":12,"community development and urban planning":9,"community services":11,"computer and network security":14,"computer games":17,"computer hardware":12,"computer hardware manufacturing":12,"computer networking products":17,"computers and electronics manufacturing":12,"conservation programs":9,"construccion":3,"construction":3,"construction hardware manufacturing":12,"consumer electronics":12,"consumer goods":12,"consumer goods rental":15,"consumer services":4,"correctional institutions":9,"cosmetics":12,"cosmetology and barber schools":5,"courts of law":9,"credit intermediation":8,"cutlery and handtool manufacturing":12,"dairy":7,"dairy product manufacturing":12,"dance companies":6,"data infrastructure and analytics":17,"data security software products":17,"defense and space manufacturing":12,"dentists":11,"design":14,"design services":14,"desktop computing software products":17,"digital accessibility services":14,"distilleries":12,"e learning":5,"e learning providers":5,"economic programs":9,"educacion":5,"education":5,"education administration programs":9,"education management":5,"electric lighting equipment manufacturing":12,"electric power generation":19,"electric power transmission control and distribution":19,"electrical equipment manufacturing":12,"electronic and precision equipment maintenance":4,"embedded software products":17,"emergency and relief services":11,"empresas de holding":10,"engineering services":14,"engines and power transmission equipment manufacturing":12,"entertainment":6,"entertainment providers":6,"environmental quality programs":9,"environmental services":14,"equipment rental services":15,"events services":2,"executive offices":9,"executive search services":2,"fabricated metal products":12,"facilities services":2,"family planning centers":11,"farming":7,"farming ranching forestry":7,"fashion accessories manufacturing":12,"financial services":8,"fine arts schools":5,"fire protection":9,"fisheries":7,"flight training":5,"food and beverage manufacturing":12,"food and beverage retail":16,"food and beverage services":1,"food and beverages":12,"food production":7,"footwear and leather goods repair":4,"footwear manufacturing":12,"forestry and logging":7,"fossil fuel electric power generation":19,"freight and package transportation":18,"fruit and vegetable preserves manufacturing":12,"fuel cell manufacturing":12,"fundraising":2,"funds and trusts":8,"furniture":12,"furniture and home furnishings manufacturing":12,"gambling facilities and casinos":6,"geothermal electric power generation":19,"glass ceramics and concrete manufacturing":12,"glass product manufacturing":12,"golf courses and country clubs":6,"government administration":9,"government relations services":14,"graphic design":14,"ground passenger transportation":18,"health and human services":9,"health wellness and fitness":6,"higher education":5,"highway street and bridge construction":3,"historical sites":6,"holding companies":10,"home health care services":11,"horticulture":7,"hospitales y cuidados sanitarios":11,"hospitality":1,"hospitals":11,"hospitals and health care":11,"hotels and motels":1,"household and institutional furniture manufacturing":12,"household appliance manufacturing":12,"household services":4,"housing and community development":9,"housing programs":9,"human resources":14,"human resources services":14,"hvac and refrigeration equipment manufacturing":12,"hydroelectric power generation":19,"import and export":20,"individual and family services":11,"industrial automation":12,"industrial machinery manufacturing":12,"industry associations":4,"information services":17,"information technology and services":17,"insurance":8,"insurance agencies and brokerages":8,"insurance and employee benefit funds":8,"insurance carriers":8,"interior design":14,"international affairs":9,"international trade and development":8,"internet marketplace platforms":17,"internet news":17,"internet publishing":17,"interurban and rural bus services":18,"investment advice":8,"investment banking":8,"investment management":8,"it services and it consulting":14,"it system custom software development":14,"it system data services":14,"it system design services":14,"it system installation and disposal":14,"it system operations and maintenance":14,"it system testing and evaluation":14,"it system training and support":14,"janitorial services":2,"landscaping services":2,"language schools":5,"laundry and drycleaning services":4,"law enforcement":9,"law practice":14,"leasing non residential real estate":15,"leasing residential real estate":15,"leather product manufacturing":12,"legal services":14,"legislative offices":9,"leisure travel and tourism":1,"libraries":17,"lime and gypsum products manufacturing":12,"loan brokers":8,"luxury goods and jewelry":16,"machinery manufacturing":12,"magnetic and optical media manufacturing":12,"manufactura":12,"manufacturing":12,"maritime":18,"maritime transportation":18,"market research":14,"marketing services":14,"mattress and blinds manufacturing":12,"measuring and control instrument manufacturing":12,"meat products manufacturing":12,"mechanical or industrial engineering":14,"media and telecommunications":17,"media production":17,"medical and diagnostic laboratories":11,"medical device":12,"medical equipment manufacturing":12,"medical practices":11,"mental health care":11,"metal ore mining":13,"metal treatments":12,"metal valve ball and roller manufacturing":12,"metalworking machinery manufacturing":12,"military and international affairs":9,"mining":13,"mobile computing software products":17,"mobile food services":1,"mobile gaming apps":17,"motor vehicle manufacturing":12,"motor vehicle parts manufacturing":12,"movies and sound recording":17,"movies videos and sound":17,"museums":6,"museums historical sites and zoos":6,"musicians":6,"nanotechnology research":14,"natural gas distribution":19,"natural gas extraction":13,"newspaper publishing":17,"non profit organization management":4,"non profit organizations":4,"nonmetallic mineral mining":13,"nonresidential building construction":3,"nuclear electric power generation":19,"nursing homes and residential care facilities":11,"office administration":2,"office furniture and fixtures manufacturing":12,"oil and coal product manufacturing":12,"oil and gas":13,"oil extraction":13,"oil gas and mining":13,"online and mail order retail":16,"online audio and video media":17,"operations consulting":14,"optometrists":11,"outpatient care centers":11,"outsourcing and offshoring consulting":14,"outsourcing offshoring":14,"packaging and containers":12,"packaging and containers manufacturing":12,"paint coating and adhesive manufacturing":12,"paper and forest product manufacturing":12,"paper and forest products":12,"pension funds":8,"performing arts":6,"performing arts and spectator sports":6,"periodical publishing":17,"personal and laundry services":4,"personal care product manufacturing":12,"personal care services":4,"pet services":4,"petroleo gas y mineria":13,"pharmaceutical manufacturing":12,"philanthropic fundraising services":4,"philanthropy":4,"photography":14,"physical occupational and speech therapists":11,"physicians":11,"pipeline transportation":18,"plastics and rubber product manufacturing":12,"plastics manufacturing":12,"political organizations":4,"postal services":18,"primary and secondary education":5,"primary metal manufacturing":12,"printing services":12,"professional organizations":4,"professional services":14,"professional training and coaching":5,"program development":4,"proveedores de ocio":6,"public assistance programs":9,"public health":9,"public policy":9,"public policy offices":9,"public relations and communications services":14,"public safety":9,"racetracks":6,"radio and television broadcasting":17,"rail transportation":18,"railroad equipment manufacturing":12,"ranching":7,"ranching and fisheries":7,"real estate":15,"real estate agents and brokers":15,"real estate and equipment rental services":15,"recreational facilities":6,"regenerative design":14,"religious institutions":4,"renewable energy equipment manufacturing":12,"renewable energy power generation":19,"renewable energy semiconductor manufacturing":12,"renewables and environment":19,"repair and maintenance":4,"research":14,"research services":14,"residential building construction":3,"restaurants":1,"retail":16,"retail apparel and fashion":16,"retail appliances electrical and electronic equipment":16,"retail art dealers":16,"retail art supplies":16,"retail books and printed news":16,"retail building materials and garden equipment":16,"retail florists":16,"retail furniture and home furnishings":16,"retail gasoline":16,"retail groceries":16,"retail health and personal care products":16,"retail luxury goods and jewelry":16,"retail motor vehicles":16,"retail musical instruments":16,"retail office equipment":16,"retail office supplies and gifts":16,"retail pharmacies":16,"retail recyclable materials and used merchandise":16,"reupholstery and furniture repair":4,"robot manufacturing":12,"robotics engineering":14,"rubber products manufacturing":12,"satellite telecommunications":17,"savings institutions":8,"school and employee bus services":18,"seafood product manufacturing":12,"secretarial schools":5,"securities and commodity exchanges":8,"security and investigations":2,"security guards and patrol services":2,"security systems services":2,"semiconductor manufacturing":12,"services for renewable energy":14,"services for the elderly and disabled":11,"servicios de administracion y soporte":2,"servicios de alojamiento":1,"servicios financieros":8,"servicios inmobiliarios y de alquiler de equipos":15,"servicios para el consumidor":4,"servicios profesionales":14,"servicios publicos":19,"sheet music publishing":17,"shipbuilding":12,"shuttles and special needs transportation services":18,"sightseeing transportation":18,"skiing facilities":6,"smart meter manufacturing":12,"soap and cleaning product manufacturing":12,"social networking platforms":17,"software development":17,"solar electric power generation":19,"sound recording":17,"space research and technology":9,"specialty trade contractors":3,"spectator sports":6,"sporting goods":12,"sporting goods manufacturing":12,"sports and recreation instruction":5,"sports teams and clubs":6,"spring and wire product manufacturing":12,"staffing and recruiting":2,"steam and air conditioning supply":19,"strategic management services":14,"subdivision of land":3,"sugar and confectionery product manufacturing":12,"surveying and mapping services":14,"taxi and limousine services":18,"technical and vocational training":5,"technology information and internet":17,"technology information and media":17,"tecnologia informacion y medios de comunicacion":17,"telecommunications":17,"telecommunications carriers":17,"telephone call centers":2,"temporary help services":2,"textile manufacturing":12,"theater companies":6,"think tanks":14,"tobacco":12,"tobacco manufacturing":12,"translation and localization":2,"transportation equipment manufacturing":12,"transportation logistics supply chain and storage":18,"transportation programs":9,"transportation trucking railroad":18,"transporte logistica cadena de suministro y almacenamiento":18,"travel arrangements":2,"truck transportation":18,"trusts and estates":8,"turned products and fastener manufacturing":12,"urban transit services":18,"utilities":19,"utilities administration":9,"utility system construction":3,"vehicle repair and maintenance":4,"venta al por mayor":20,"venta minorista":16,"venture capital and private equity principals":8,"veterinary":14,"veterinary services":14,"vocational rehabilitation services":11,"warehousing":18,"warehousing and storage":18,"waste collection":19,"waste treatment and disposal":19,"water supply and irrigation systems":19,"water waste steam and air conditioning services":19,"wellness and fitness services":6,"wholesale":20,"wholesale alcoholic beverages":20,"wholesale apparel and sewing supplies":20,"wholesale appliances electrical and electronics":20,"wholesale building materials":20,"wholesale chemical and allied products":20,"wholesale computer equipment":20,"wholesale drugs and sundries":20,"wholesale food and beverage":20,"wholesale footwear":20,"wholesale furniture and home furnishings":20,"wholesale hardware plumbing heating equipment":20,"wholesale import and export":20,"wholesale luxury goods and jewelry":20,"wholesale machinery":20,"wholesale metals and minerals":20,"wholesale motor vehicles and parts":20,"wholesale paper products":20,"wholesale petroleum and petroleum products":20,"wholesale photography equipment and supplies":20,"wholesale raw farm products":20,"wholesale recyclable materials":20,"wind electric power generation":19,"wine and spirits":12,"wineries":12,"wireless services":17,"women s handbag manufacturing":12,"wood product manufacturing":12,"writing and editing":2,"zoos and botanical gardens":6};
const PD_INDUSTRY_LABELS = {"1":"Servicios de alojamiento","2":"Servicios de administración y soporte","3":"Construcción","4":"Servicios para el consumidor","5":"Educación","6":"Proveedores de ocio","7":"Agricultura, ganadería y silvicultura","8":"Servicios financieros","9":"Administración pública","10":"Empresas de holding","11":"Hospitales y cuidados sanitarios","12":"Manufactura","13":"Petróleo, gas y minería","14":"Servicios profesionales","15":"Servicios inmobiliarios y de alquiler de equipos","16":"Venta minorista","17":"Tecnología, información y medios de comunicación","18":"Transporte, logística, cadena de suministro y almacenamiento","19":"Servicios públicos","20":"Venta al por mayor"};

function normalizeIndustry(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[,/]+/g, " ")
    .replace(/[^a-z0-9 ]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function mapIndustry(value) {
  const raw = String(value || "").trim();
  if (!raw) return { id: null, label: null, raw: "", status: "empty" };
  const id = INDUSTRY_TO_PD[normalizeIndustry(raw)];
  if (!id) return { id: null, label: null, raw, status: "unmapped" };
  return { id, label: PD_INDUSTRY_LABELS[String(id)] || null, raw, status: "mapped" };
}
// INDUSTRY_MAP_END

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

function enrichmentWriteDate(now = new Date()) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Europe/Madrid',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(now);
}

function shouldYieldToOlderRun(selfId, running, nowMs = Date.now(), staleMs = 8 * 60 * 1000) {
  const self = Number(selfId);
  if (!self) return false;
  const cutoff = nowMs - staleMs;
  for (const ex of running || []) {
    const id = Number(ex && ex.id);
    if (!id || id === self) continue;
    const started = Date.parse((ex && ex.startedAt) || '') || 0;
    if (started && started < cutoff) continue;
    if (id < self) return true;
  }
  return false;
}

function isDirectoryIdentityRow(row) {
  const DIRECTORY_HOSTS = [
    'alimarket.es', 'farmacias.es', 'smartgridsinfo.es', 'construnews.com', 'paginasgalegas.com',
    'leadingcourses.com', 'radio.es', 'infocif.es', 'einforma.com', 'axesor.es',
    'empresite.eleconomista.es', 'expansion.com', 'cincodias.elpais.com', 'iberinform.es',
    'informa.es', 'economia3.com', 'cadenadesuministro.es', 'canarias7.es', 'doctoralia.es',
    'eventplannerspain.com', 'gastroteca.cat', 'infobae.com', 'lavozdegalicia.es', 'nobroker.in',
    'tendata.com', 'vlex.es', 'cursodeinstalador.com', 'oleoteca.info', 'covermanager.com',
    'idae.es', 'congreso.es', 'facua.org', 'moma.org',
  ];
  const DIRECTORY_PROFILE_MARKERS = ['/empresa/', '/ficha-empresa', '/directorio-empresas', '/directorio/'];
  const DIRECTORY_LINKEDIN_SLUGS = [
    'publicaciones-alimarket', 'construnews-com', 'leadingcourses', 'farmacias.com',
    'radio-de-gmbh', 'smartgridsinfo', 'idaeenergia', 'cadenadesuministro', 'canarias7',
    'congreso-de-los-diputados', 'doctoralia-espana', 'event-planner-spain_2', 'facua',
    'gastroteca', 'infobae', 'la-voz-de-galicia', 'the-museum-of-modern-art', 'nobroker-in',
    'tendata', 'vlex-es', 'curso-de-instalador', 'covermanager',
  ];
  const website = String((row && row.website) || '').trim().toLowerCase();
  const domain = String((row && row.domain) || '').trim().toLowerCase().replace(/^www\./, '');
  const linkedin = String((row && row.linkedin_url) || '').trim().toLowerCase();
  const hosts = [domain];
  const site = website.includes('://') ? website : (website ? `https://${website}` : '');
  if (site) {
    try {
      hosts.push(new URL(site).hostname.replace(/^www\./, ''));
    } catch (error) {
      hosts.push(website.split('/')[0].replace(/^www\./, ''));
    }
  }
  const hostBlocked = hosts.some((host) => DIRECTORY_HOSTS.some((item) => host === item || host.endsWith(`.${item}`)));
  if (hostBlocked) return true;
  if (DIRECTORY_PROFILE_MARKERS.some((marker) => website.includes(marker))) return true;
  return DIRECTORY_LINKEDIN_SLUGS.some((slug) => linkedin.includes(`/company/${slug}`));
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function orgIdFromRow(row) {
  const a = String(row.pipedrive_org_id || '').trim();
  const b = String(row.source_id || '').trim();
  const pick = a || b;
  if (!pick) return null;
  const num = Number(pick);
  return Number.isFinite(num) && num > 0 ? Math.floor(num) : null;
}

function isPdValueEmpty(value) {
  if (value === null || value === undefined) return true;
  if (typeof value === 'string') return value.trim() === '';
  if (typeof value === 'number' && Number.isNaN(value)) return true;
  return false;
}

function isFieldEmpty(key, value) {
  if (key === 'industry' && (value === 0 || value === '0')) return true;
  return isPdValueEmpty(value);
}

function hasNocoValue(value) {
  return !isPdValueEmpty(value);
}

/**
 * Solo campos vacíos en Pipedrive y con valor en NocoDB.
 * Si Pipedrive ya tiene dato, no se incluye en el PUT (no sobrescribir).
 */
function filterPayloadEmptyOnly(existingOrg, desiredPayload) {
  const filtered = {};
  const skipped_existing = [];
  const skipped_no_noco = [];
  for (const [key, newValue] of Object.entries(desiredPayload)) {
    if (!hasNocoValue(newValue)) {
      skipped_no_noco.push(key);
      continue;
    }
    const current = existingOrg ? existingOrg[key] : undefined;
    if (isFieldEmpty(key, current)) {
      filtered[key] = newValue;
    } else {
      skipped_existing.push(key);
    }
  }
  return { payload: filtered, skipped_existing, skipped_no_noco };
}

function buildDesiredPayload(row) {
  const payload = {};
  const linkedin = String(row.linkedin_url || '').trim();
  if (linkedin) payload.linkedin = linkedin;

  const website = resolveWebsite(row);
  if (website) payload.website = website;

  const industry = mapIndustry(row.industry);
  if (industry.id) payload.industry = industry.id;

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

  payload[PD_KEYS.enriched_at] = enrichmentWriteDate();

  const hq = parseHeadquarters(row.headquarters_text);
  if (hq.locality) payload[PD_KEYS.locality] = hq.locality;
  if (hq.province) payload[PD_KEYS.province] = hq.province;

  const phone = String(row.phone || '').trim();
  if (phone) payload.phone = phone;

  return { payload, industry };
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
const maxRows = toPositiveInt(cfg.enrich_push_max_rows_per_run, 50);
const timeBudgetMs = toPositiveInt(cfg.code_time_budget_ms, 240000);
const settleMs = toPositiveInt(cfg.single_flight_settle_ms, 2000);

if (!pdToken || !ncToken || !tableId) {
  throw new Error('Missing pipedrive_api_token, nocodb_api_token, or nocodb_organizaciones_table_id in config_enrich_push');
}

const startedAt = Date.now();
const where = '(confidence,gt,60)~and(pipedrive_status,eq,ok)';
const ncHeaders = { 'xc-token': ncToken, 'Content-Type': 'application/json' };
const selfId = (typeof $execution !== 'undefined' && $execution) ? $execution.id : null;

let singleFlight = 'unchecked';
if (cfg.n8n_api_key && cfg.n8n_api_base && cfg.n8n_workflow_id && selfId) {
  await sleep(settleMs);
  try {
    const running = [];
    let cursor;
    for (let page = 0; page < 5; page++) {
      const qs = { workflowId: cfg.n8n_workflow_id, status: 'running', limit: 100 };
      if (cursor) qs.cursor = cursor;
      const listed = await this.helpers.httpRequest({
        method: 'GET',
        url: `${String(cfg.n8n_api_base).replace(/\/$/, '')}/api/v1/executions`,
        qs,
        headers: { 'X-N8N-API-KEY': cfg.n8n_api_key },
        json: true,
      });
      const batch = Array.isArray(listed.data) ? listed.data : [];
      running.push(...batch);
      cursor = listed.nextCursor;
      if (!cursor || !batch.length) break;
    }
    singleFlight = 'leader';
    if (shouldYieldToOlderRun(selfId, running)) {
      return [{
        json: {
          status: 'skipped',
          reason: 'another_run_in_progress',
          execution_id: selfId,
          single_flight: 'yielded',
          candidates_fetched: 0,
          processed_ok: 0,
          results: [],
        },
      }];
    }
  } catch (error) {
    singleFlight = 'unchecked';
  }
}

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

  if (isDirectoryIdentityRow(row)) {
    await this.helpers.httpRequest({
      method: 'PATCH',
      url: `${ncBase}/api/v2/tables/${tableId}/records`,
      headers: ncHeaders,
      body: [{
        Id: row.Id,
        commercial_name: null,
        linkedin_url: null,
        website: null,
        domain: null,
        industry: null,
        employee_count: null,
        followers: null,
        phone: null,
        headquarters_text: null,
        confidence: 15,
        match_status: 'not_found',
        relationship: 'requires_review',
        enrichment_status: 'rejected_directory',
        evidence_summary: 'Directorio excluido: web o LinkedIn de Publicaciones Alimarket. No se escribe en Pipedrive.',
      }],
      json: true,
    });
    results.push({ Id: row.Id, status: 'rejected_directory', org_id: orgId });
    continue;
  }

  const { payload: desiredPayload, industry } = buildDesiredPayload(row);

  try {
    const existingOrg = await fetchOrganization(this, pdBase, pdToken, orgId);
    const { payload, skipped_existing, skipped_no_noco } = filterPayloadEmptyOnly(
      existingOrg,
      desiredPayload,
    );
    const fieldsWritten = Object.keys(payload).length;
    let industrySync = industry.status;
    if (industry.id && Object.prototype.hasOwnProperty.call(payload, 'industry')) {
      industrySync = 'written';
    } else if (industry.id && skipped_existing.includes('industry')) {
      industrySync = 'kept_pipedrive';
    }

    // Sin campos vacíos que rellenar → no llamar PUT (Pipedrive intacto).
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
      fields_written_keys: Object.keys(payload),
      fields_skipped_pd_had_value: skipped_existing,
      fields_skipped_noco_empty: skipped_no_noco,
      industry_sync: industrySync,
      industry_raw: industry.raw || null,
      industry_pipedrive_id: industry.id,
      industry_pipedrive_label: industry.label,
      update_pipedrive: syncedAt,
    });
    processed += 1;
  } catch (error) {
    results.push({ Id: row.Id, org_id: orgId, status: 'error', reason: error.message });
  }
}

const industryUnmapped = {};
for (const item of results) {
  if (item.industry_sync === 'unmapped' && item.industry_raw) {
    industryUnmapped[item.industry_raw] = (industryUnmapped[item.industry_raw] || 0) + 1;
  }
}

return [{
  json: {
    candidates_fetched: rows.length,
    processed_ok: processed,
    single_flight: singleFlight,
    execution_id: selfId,
    results,
    industry_unmapped: industryUnmapped,
    filter_where: where,
    completed_at: new Date().toISOString(),
    timed_out: Date.now() - startedAt > timeBudgetMs,
  },
}];
