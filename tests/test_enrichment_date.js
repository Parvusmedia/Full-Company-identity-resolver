const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const code = fs.readFileSync(
  path.join(__dirname, "../scripts/n8n_push_organizaciones_code.js"),
  "utf8",
);
const match = code.match(/function enrichmentWriteDate\(now = new Date\(\)\) \{[\s\S]*?\n\}/);
assert.ok(match, "enrichmentWriteDate missing from push code");
const enrichmentWriteDate = new Function(`${match[0]}\nreturn enrichmentWriteDate;`)();

assert.equal(enrichmentWriteDate(new Date("2026-10-13T10:00:00Z")), "2026-10-13");
assert.equal(enrichmentWriteDate(new Date("2026-10-13T22:30:00Z")), "2026-10-14");
assert.equal(enrichmentWriteDate(new Date("2026-01-15T00:30:00Z")), "2026-01-15");
assert.match(code, /payload\[PD_KEYS\.enriched_at\] = enrichmentWriteDate\(\)/);
assert.doesNotMatch(code, /row\.enriched_at/);

console.log("OK enrichment write date");
