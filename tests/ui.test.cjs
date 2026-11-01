const test = require("node:test");
const assert = require("node:assert/strict");
const ui = require("../src/pipefoundry/web/ui.js");

test("pipeline drafts reject JSON primitives and arrays before saving", () => {
  for (const raw of ["null", "[]", "true", "17", '"data"']) {
    assert.throws(() => ui.parseDraft(raw), /JSON object/);
  }
  assert.deepEqual(ui.parseDraft('{"name":"orders"}'), { name: "orders" });
});

test("AI markdown escapes HTML and rejects unsafe citation destinations", () => {
  const html = ui.markdown(
    "## Finding\n- **Branch:** `main`\n- <img src=x onerror=alert(1)>\n\n[unsafe](javascript:alert) [source](https://api.github.com/repos/a/b)",
  );
  assert.ok(html.includes("<strong>Branch:</strong>"));
  assert.ok(html.includes("<code>main</code>"));
  assert.ok(!html.includes("<img"));
  assert.ok(!html.includes('href="javascript:'));
  assert.ok(html.includes('href="https://api.github.com/repos/a/b"'));
});
test("source links cannot impersonate GitHub or embed credentials", () => {
  for (const value of [
    "https://github.com.evil.test/a",
    "https://user:password@github.com/a",
    "data:text/html,a",
    "https://github.com:444/a",
  ]) {
    assert.equal(ui.safeURL(value), null);
  }
  assert.equal(ui.safeURL("https://github.com/a/b"), "https://github.com/a/b");
});
test("code highlighting preserves escaped content and separates keys", () => {
  const result = ui.highlightJSON('{"name":"<script>","cpu":250,"ok":true}');
  assert.ok(result.includes("syntax-key"));
  assert.ok(result.includes("&lt;script&gt;"));
  assert.ok(!result.includes("<script>"));
});
test("command search matches all query words without inventing destinations", () => {
  const commands = [
    {
      label: "Pipeline editor",
      detail: "Configure a draft",
      href: "/workbench/editor",
    },
    {
      label: "Validation",
      detail: "Check a pipeline",
      href: "/workbench/validation",
    },
  ];
  assert.deepEqual(
    ui.filterCommands(commands, "PIPELINE draft").map((x) => x.href),
    ["/workbench/editor"],
  );
  assert.equal(ui.filterCommands(commands, "unknown").length, 0);
});
