const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const code = fs.readFileSync(
  path.join(__dirname, "../scripts/n8n_push_organizaciones_code.js"),
  "utf8",
);
const match = code.match(/function shouldYieldToOlderRun\(selfId, running, nowMs = Date\.now\(\), staleMs = 8 \* 60 \* 1000\) \{[\s\S]*?\n\}/);
assert.ok(match, "shouldYieldToOlderRun missing from push code");
const shouldYieldToOlderRun = new Function(`${match[0]}\nreturn shouldYieldToOlderRun;`)();

const now = Date.parse("2026-10-13T10:32:00.000Z");
const recent = "2026-10-13T10:31:58.000Z";
const stale = "2026-10-13T10:20:00.000Z";

assert.equal(shouldYieldToOlderRun(20, [{ id: 10, startedAt: recent }], now), true);
assert.equal(shouldYieldToOlderRun(20, [{ id: 30, startedAt: recent }], now), false);
assert.equal(shouldYieldToOlderRun(20, [{ id: 20, startedAt: recent }], now), false);
assert.equal(shouldYieldToOlderRun(20, [{ id: 10, startedAt: stale }], now), false);
assert.equal(shouldYieldToOlderRun(null, [{ id: 10, startedAt: recent }], now), false);
assert.equal(shouldYieldToOlderRun(5, [], now), false);
assert.match(code, /reason: 'another_run_in_progress'/);
assert.match(code, /enrich_push_max_rows_per_run, 50/);
assert.match(code, /function isDirectoryIdentityRow/);
const start = code.indexOf("function isDirectoryIdentityRow");
let depth = 0;
let end = start;
for (let i = code.indexOf("{", start); i < code.length; i += 1) {
  if (code[i] === "{") depth += 1;
  else if (code[i] === "}") {
    depth -= 1;
    if (depth === 0) {
      end = i + 1;
      break;
    }
  }
}
const isDirectoryIdentityRow = new Function(
  `${code.slice(start, end)}\nreturn isDirectoryIdentityRow;`,
)();
assert.equal(isDirectoryIdentityRow({ website: "https://www.alimarket.es/", linkedin_url: "", domain: "" }), true);
assert.equal(isDirectoryIdentityRow({ domain: "alimarket.es" }), true);
assert.equal(
  isDirectoryIdentityRow({ linkedin_url: "https://www.linkedin.com/company/publicaciones-alimarket-s.a./" }),
  true,
);
assert.equal(isDirectoryIdentityRow({ website: "https://www.construnews.com/", domain: "construnews.com" }), true);
assert.equal(isDirectoryIdentityRow({ website: "https://www.iberinform.es/empresa/208128/eco-mora" }), true);
assert.equal(isDirectoryIdentityRow({ linkedin_url: "https://www.linkedin.com/company/idaeenergia/" }), true);
assert.equal(isDirectoryIdentityRow({ website: "https://example.com", linkedin_url: "https://www.linkedin.com/company/acme/" }), false);

console.log("OK single flight");
