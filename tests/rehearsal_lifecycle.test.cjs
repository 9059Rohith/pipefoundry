const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

async function openRehearsal() {
  const nodes = new Map(), timers = new Map();
  let nextTimer = 0, resolveRequest;
  const pending = new Promise((resolve) => { resolveRequest = resolve; });
  function node(selector) {
    if (!nodes.has(selector)) {
      const listeners = new Map();
      const element = {
        value: selector === "#rehearsal-partition" ? "2026-11-09" : "",
        textContent: "", disabled: /#rehearsal-(export|config|yaml|output)$/.test(selector),
        classList: {add() {}, remove() {}},
        setAttribute() {}, querySelectorAll: () => [],
        addEventListener: (name, callback) => listeners.set(name, callback), listeners,
      };
      let markup = "";
      Object.defineProperty(element, "innerHTML", {
        get: () => markup,
        set(value) {
          markup = value;
          if (selector === "#content" && value.includes('id="rehearsal-form"')) {
            for (const key of nodes.keys()) if (key.startsWith("#rehearsal-")) nodes.delete(key);
          }
        },
      });
      nodes.set(selector, element);
    }
    return nodes.get(selector);
  }
  const context = vm.createContext({
    document: {body: {dataset: {page: "rehearsal"}}, querySelector: node,
      querySelectorAll: () => [], addEventListener() {}},
    window: {matchMedia: () => ({addEventListener() {}})},
    sessionStorage: {getItem: () => null, setItem() {}},
    Date, URL, AbortController, TextEncoder,
    setTimeout: (callback, delay) => { timers.set(++nextTimer, {callback, delay}); return nextTimer; },
    clearTimeout: (id) => timers.delete(id),
    fetch: async () => pending,
  });
  for (const file of ["ui.js", "app.js"])
    vm.runInContext(fs.readFileSync(require.resolve(`../src/pipefoundry/web/${file}`), "utf8"), context);
  async function initialize() {
    await new Promise(setImmediate);
    for (const [id, timer] of timers) if (timer.delay === 0) {
      timers.delete(id); timer.callback();
    }
  }
  await initialize();
  return {node, initialize, resolveRequest};
}

for (const success of [true, false]) {
  test(`repository reload ignores a prior rehearsal ${success ? "success" : "error"} response`, async () => {
    const app = await openRehearsal();
    app.node("#rehearsal-rows").value = '[{"id":"old","amount_cents":1,"currency":"usd"}]';
    const previousForm = app.node("#rehearsal-form");
    const submitting = previousForm.onsubmit({preventDefault() {}});
    app.node("#repository").value = "9059Rohith/pipefoundry";
    app.node("#repository-form").listeners.get("submit")({preventDefault() {}});
    await app.initialize();
    assert.notEqual(app.node("#rehearsal-form"), previousForm);
    const freshOutput = app.node("#rehearsal-result").innerHTML;
    app.resolveRequest({ok: success, status: success ? 200 : 503,
      headers: {get: () => null}, json: async () => success ? {
        evidence: {accepted: true, config: {name: "old-evidence"}, scope: "Old sample",
          summary: {input_rows: 1, output_rows: 1, replaced_rows: 0, currency_normalizations: 1},
          issues: [], duplicates: [], currency_totals: [], normalized_rows: []},
        evidence_sha256: "old-hash",
      } : {detail: "Old request error"},
    });
    await submitting;
    assert.equal(app.node("#rehearsal-rows").value, "");
    assert.equal(app.node("#rehearsal-result").innerHTML, freshOutput);
    for (const suffix of ["export", "config", "yaml", "output"])
      assert.equal(app.node(`#rehearsal-${suffix}`).disabled, true);
  });
}
