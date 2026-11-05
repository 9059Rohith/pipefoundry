const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

async function openAgent(status, retryAfter, preferredModel = "gemini-3.5-flash-lite") {
  let now = Date.parse("2026-11-05T12:00:00Z");
  const nodes = new Map(), timeouts = new Map(), intervals = new Map(), requests = [];
  let timer = 0;
  const node = (selector) => {
    if (!nodes.has(selector)) nodes.set(selector, {
      value: selector === "#agent-question" ? "Inspect recent releases" : "",
      innerHTML: "", textContent: "", disabled: false,
      classList: { add() {}, remove() {} },
      setAttribute() {}, addEventListener() {}, querySelectorAll: () => [],
    });
    return nodes.get(selector);
  };
  const document = {
    body: { dataset: { page: "agent" } },
    querySelector: node, querySelectorAll: () => [], addEventListener() {},
  };
  class Clock extends Date { static now() { return now; } }
  const context = vm.createContext({
    document, Date: Clock, AbortController, URL,
    window: { matchMedia: () => ({ addEventListener() {} }) },
    sessionStorage: { getItem: () => null, setItem() {} },
    setTimeout: (callback, delay) => { timeouts.set(++timer, { callback, delay }); return timer; },
    clearTimeout: (id) => timeouts.delete(id),
    setInterval: (callback) => { intervals.set(++timer, callback); return timer; },
    clearInterval: (id) => intervals.delete(id),
    fetch: async (url) => {
      requests.push(url);
      const integrations = url.endsWith("integrations");
      return {
        ok: integrations || status === 200, status: integrations ? 200 : status,
        headers: { get: () => retryAfter },
        json: async () => integrations
          ? { ai_configured: true, ai_model: "private-operator-model",
              public_ai: { preferred_model: preferredModel, configured: !!preferredModel } }
          : status === 200
            ? { answer: "Source-based analysis", trace: [], provider: "gemini", model: "test" }
            : { detail: "Provider unavailable" },
      };
    },
  });
  for (const file of ["ui.js", "app.js"])
    vm.runInContext(fs.readFileSync(require.resolve(`../src/pipefoundry/web/${file}`), "utf8"), context);
  await new Promise(setImmediate);
  for (const [id, item] of timeouts) if (item.delay === 0) {
    timeouts.delete(id);
    item.callback();
  }
  await node("#agent-submit").onclick();
  return {
    button: node("#agent-submit"), output: node("#agent-output"), requests, intervals,
    content: node("#content"),
    advance(seconds) { now += seconds * 1000; for (const tick of intervals.values()) tick(); },
  };
}

for (const status of [429, 503]) {
  for (const header of ["172800", "Sat, 07 Nov 2026 12:00:00 GMT"]) {
    test(`${status} respects the entire ${header} cooldown without resubmitting`, async () => {
      const app = await openAgent(status, header);
      assert.equal(app.button.disabled, true);
      assert.equal(app.button.textContent, "Try again in 172800s");
      app.advance(86401);
      assert.equal(app.button.disabled, true);
      assert.equal(app.button.textContent, "Try again in 86399s");
      app.advance(86398);
      assert.equal(app.button.disabled, true);
      app.advance(1);
      assert.equal(app.button.disabled, false);
      assert.equal(app.button.textContent, "Ask Foundry");
      assert.equal(app.intervals.size, 0);
      assert.equal(app.requests.filter((url) => url.endsWith("demo-agent")).length, 1);
    });
  }
}

test("other provider errors keep the normal manual retry button", async () => {
  const app = await openAgent(502, "120");
  assert.equal(app.button.disabled, false);
  assert.equal(app.intervals.size, 0);
  assert.match(app.output.innerHTML, /Analysis not completed/);
  assert.match(app.output.innerHTML, /Provider unavailable/);
});

test("successful analysis still renders and enables another manual question", async () => {
  const app = await openAgent(200, null);
  assert.equal(app.button.disabled, false);
  assert.equal(app.intervals.size, 0);
  assert.match(app.output.innerHTML, /Source-based analysis/);
  assert.equal(app.requests.filter((url) => url.endsWith("demo-agent")).length, 1);
});

test("public agent identifies the public preferred model independently of operator settings", async () => {
  const app = await openAgent(200, null, "gemini-3.1-flash-lite");
  assert.match(app.content.innerHTML, /gemini-3\.1-flash-lite \/ Public demo/);
  assert.ok(!app.content.innerHTML.includes("private-operator-model"));
  assert.match(app.output.innerHTML, /Provider: gemini · test/);
});

test("unavailable public configuration disables public analysis despite configured operator AI", async () => {
  const app = await openAgent(200, null, null);
  assert.match(app.content.innerHTML, /id="agent-submit" disabled/);
  assert.match(app.content.innerHTML, /The provider is not configured/);
  assert.ok(!app.content.innerHTML.includes("private-operator-model"));
});
