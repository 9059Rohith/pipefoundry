const test = require("node:test");
const assert = require("node:assert/strict");
const ui = require("../src/pipefoundry/web/ui.js");

test("retry delays preserve long seconds and HTTP dates without early retries", () => {
  const now = Date.parse("2026-11-05T12:00:00.500Z");
  for (const [header, expected] of [
    ["120", 120],
    ["172800", 172800],
    ["Thu, 05 Nov 2026 12:02:00 GMT", 120],
    ["Sun, 08 Nov 2026 12:00:00 GMT", 259200],
    ["Thu, 05 Nov 2026 11:00:00 GMT", 1],
    [null, 60], ["", 60], ["garbage", 60], ["0", 60], ["-1", 60],
    ["Infinity", 60], ["NaN", 60], ["1.5", 60], ["1e6", 60],
    ["9".repeat(400), 60],
  ]) {
    assert.equal(ui.retryAfterSeconds(header, now), expected, String(header));
  }
});

test("manifest review cards escape evidence and filter findings", () => {
  const checks = [
    { id: "safe", title: "Non-root", status: "pass", evidence: [], source: "https://kubernetes.io/docs/" },
    { id: "risk", title: "<script>risk</script>", status: "warn", explanation: "<img src=x>",
      remediation: "Pin image", source: "javascript:alert(1)",
      evidence: [{path: "spec.image", value: "<svg onload=alert(1)>", passed: false}] },
  ];
  const html = ui.reviewChecks(checks, "findings");
  assert.ok(!html.includes("Non-root"));
  assert.ok(html.includes("&lt;script&gt;risk&lt;/script&gt;"));
  assert.ok(!html.includes("<svg onload"));
  assert.ok(!html.includes("javascript:"));
  assert.ok(ui.reviewChecks(checks, "all").includes("Non-root"));
  assert.ok(ui.reviewChecks([], "findings").includes("No matching checks"));
  assert.equal(ui.safeURL("https://kubernetes.io.evil.test/docs"), null);
});

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
