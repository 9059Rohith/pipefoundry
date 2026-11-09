const test = require("node:test");
const assert = require("node:assert/strict");
const ui = require("../src/pipefoundry/web/ui.js");

test("sample report exposes reject-all quality diagnostics without rendering untrusted markup", () => {
  const html = ui.rehearsalReport({evidence: {
    accepted: false, scope: "Sample only", invalid_rows: 1,
    summary: {input_rows: 2, output_rows: 0, replaced_rows: 0, currency_normalizations: 0},
    issues: [{row: 2, field: "<img src=x onerror=alert(1)>", rule: "Use an integer"}],
    issues_truncated: true, duplicates: [], currency_totals: [], normalized_rows: [],
  }, evidence_sha256: "abc"});
  assert.ok(html.includes("Batch rejected"));
  assert.ok(html.includes("&lt;img src=x onerror=alert(1)&gt;"));
  assert.ok(!html.includes("<img"));
  assert.ok(html.includes("first 100"));
  assert.ok(html.includes("No output rows"));
});

test("sample report shows per-currency cents and duplicate winner rows", () => {
  const html = ui.rehearsalReport({evidence: {
    accepted: true, scope: "Sample only", invalid_rows: 0,
    sample_source: {captured_at_utc: "2026-11-05T04:53:11.824138+00:00",
      selected_record_count: 100, original_record_count: 1000,
      mapping: "Mapped NYC fares", source_url: "https://data.cityofnewyork.us/resource/4b4i-vvec.json",
      source_sha256: "source-hash", partition_note: "Storage date only"},
    summary: {input_rows: 3, output_rows: 2, replaced_rows: 1, currency_normalizations: 2},
    issues: [], issues_truncated: false,
    duplicates: [{id: "a", source_rows: [1, 3], winner_row: 3}],
    currency_totals: [{currency: "EUR", amount_cents: 700, rows: 1},
      {currency: "USD", amount_cents: 250, rows: 1}],
    normalized_rows: [{partition_date: "2026-11-09", id: "a", amount_cents: 250, currency: "USD"}],
  }, evidence_sha256: "abc"});
  assert.ok(html.includes("Sample accepted"));
  assert.ok(html.includes("EUR"));
  assert.ok(html.includes("700"));
  assert.ok(html.includes("USD"));
  assert.ok(html.includes("250"));
  assert.ok(html.includes("1, 3"));
  assert.ok(html.includes("2026-11-09"));
  assert.ok(html.includes("2026-11-05T04:53:11.824138+00:00"));
  assert.ok(html.includes("100 of 1000"));
  assert.ok(html.includes("Mapped NYC fares"));
  assert.ok(html.includes("Storage date only"));
});
