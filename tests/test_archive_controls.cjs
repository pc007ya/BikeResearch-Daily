const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const app = fs.readFileSync("docs/app.js", "utf8");
const html = fs.readFileSync("docs/index.html", "utf8");
for (const id of ["btn-download-pptx", "btn-slide-pptx"]) {
  assert.match(html, new RegExp('id="' + id + '" aria-disabled="true"'));
}
const from = app.indexOf("function updateDeckControls");
const upto = app.indexOf("function newBadgeHtml", from);
assert.ok(from >= 0 && upto > from);
const nodes = {};
const calls = [];
const window = { document: { getElementById(id) { return nodes[id] ??= {
  setAttribute(key, val) { this[key] = val; }, removeAttribute(key) { delete this[key]; },
}; } }, fetch: url => new Promise(ok => calls.push({url, ok})) };
for (const f of [
  "renderMastheadSources", "renderConclusions", "renderComponentShares", "renderBikeSelector",
  "selectBike", "renderIntelTables", "buildWebSlides",
]) window[f] = () => {};
vm.createContext(window);
vm.runInContext("let reportLoadVersion = 0; let currentReport = null; " + app.slice(from, upto), window);
const check = date => {
  for (const id of ["btn-download-pptx", "btn-slide-pptx"]) {
    if (date) {
      assert.equal(nodes[id].href, "data/archive/" + date + "_briefing.pptx");
      assert.equal(nodes[id]["aria-disabled"], undefined);
    } else {
      assert.equal(nodes[id].href, undefined);
      assert.equal(nodes[id]["aria-disabled"], "true");
    }
  }
};
const resolve = (idx, date) => calls[idx].ok({ok: true, json: async () => ({
  date, pptx_file: "data/daily_briefing.pptx", complete_bikes: [],
})});
(async () => {
  let a = window.loadReport("data/latest.json");
  check(null);
  resolve(0, "2026-11-24");
  await a;
  check("2026-11-24");
  let b = window.loadReport("data/archive/2026-11-23.json");
  let c = window.loadReport("data/archive/2026-11-22.json");
  check(null);
  resolve(2, "2026-11-22");
  await c;
  resolve(1, "2026-11-23");
  await b;
  check("2026-11-22");
  let mismatch = window.loadReport("data/archive/2026-11-23.json");
  resolve(3, "2026-11-22");
  await mismatch;
  check(null);
  console.log("PASS dated links on both actual app controls, stale responses ignored, date mismatch closed");
})().catch(e => {console.error(e);process.exitCode = 1;});
