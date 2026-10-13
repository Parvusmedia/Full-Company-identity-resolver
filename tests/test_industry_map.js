const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { mapIndustry, INDUSTRY_TO_PD } = require("../scripts/industry_map");

const root = path.resolve(__dirname, "..");

function testKnownMappings() {
  const insurance = mapIndustry("Insurance");
  assert.equal(insurance.status, "mapped");
  assert.equal(insurance.id, 8);
  assert.equal(insurance.label, "Servicios financieros");

  assert.equal(mapIndustry("  insurance ").id, 8);
  assert.equal(mapIndustry("Servicios financieros").id, 8);
  assert.equal(mapIndustry("Financial Services").id, 8);
  assert.equal(mapIndustry("Insurance Carriers").id, 8);
  assert.equal(mapIndustry("Insurance Agencies and Brokerages").id, 8);

  assert.equal(mapIndustry("Movies, Videos, and Sound").id, 17);
  assert.equal(mapIndustry("Food & Beverages").id, 12);
  assert.equal(mapIndustry("Petróleo, gas y minería").id, 13);
  assert.equal(mapIndustry("Construction").id, 3);
  assert.equal(mapIndustry("Construcción").id, 3);

  assert.equal(mapIndustry("").status, "empty");
  assert.equal(mapIndustry("   ").status, "empty");
  assert.equal(mapIndustry(null).status, "empty");

  const unknown = mapIndustry("Not A Real Sector XYZ");
  assert.equal(unknown.status, "unmapped");
  assert.equal(unknown.id, null);

  assert.equal(mapIndustry("bank").status, "unmapped");
  assert.equal(mapIndustry("Banking").id, 8);
}

function testObservedNocoCoverage() {
  const counts = JSON.parse(
    fs.readFileSync(path.join(root, "tests/fixtures/noco_industry_counts.json"), "utf8"),
  );
  const unmapped = [];
  for (const raw of Object.keys(counts)) {
    const mapped = mapIndustry(raw);
    if (mapped.status !== "mapped" || !mapped.id) unmapped.push(raw);
  }
  assert.deepEqual(unmapped, []);
}

function testPushCodeEmbedsTheSameMap() {
  const push = fs.readFileSync(path.join(root, "scripts/n8n_push_organizaciones_code.js"), "utf8");
  const match = push.match(/const INDUSTRY_TO_PD = (\{.*?\});/s);
  assert.ok(match, "INDUSTRY_TO_PD missing from n8n push code");
  assert.deepEqual(JSON.parse(match[1]), INDUSTRY_TO_PD);
  assert.match(push, /payload\.industry = industry\.id/);
  assert.match(push, /industry_unmapped/);
  assert.doesNotMatch(push, /industry omitted/);
}

testKnownMappings();
testObservedNocoCoverage();
testPushCodeEmbedsTheSameMap();
console.log(`OK industry map (${Object.keys(INDUSTRY_TO_PD).length} keys)`);
