# Sample rehearsal

Open `/workbench/rehearsal` after saving a pipeline in the editor. Paste your own
JSON array of 1–100 order records, select a UTC partition date, and run the
rehearsal. The form starts blank; no sample is presented as observed production
data. Input is processed in memory and is not stored by this application.

For real retained input, choose **Load retained NYC fare sample**. This optional
action loads the first 100 of the 1,000 actual NYC Open Data fare observations
retained on 5 November 2026. The default form remains blank. There is no external
fetch: the original response and metadata bytes are packaged and verified against
pinned SHA-256 fingerprints before use. Their original source URL and capture
timestamp appear beside the input and in the evidence export.

The mapping uses SHA-256 of each original UTF-8 `row_id` as the strict transform
ID, exact `fare_amount × 100` as integer cents, and USD as currency. The selected
fares sum to **232,603 cents**. These are mapped taxi fare observations, not
customer orders. The report includes all 100 original selected records so the
mapping can be inspected. The chosen partition is an output storage date; it does
not replace or convert the original pickup timestamps.

Editing the rows clears the retained-source claim. The server independently
rejects an altered sample submitted with a retained-source identifier. Changing
the partition preserves source provenance because the original rows remain
unchanged. Reloading the workspace while a request is in flight cannot restore
evidence or downloads into a new blank form.

This runs the **same `normalize_orders` function as the SQL worker**:

- Each record requires `id`, integer `amount_cents` and three-letter `currency`.
  Unknown fields, negative amounts, booleans and malformed records fail validation.
- Currency is uppercased. Duplicate IDs use the last observation within the sample
  partition, with input row numbers showing which observation wins.
- Any invalid record rejects the whole sample. Diagnostics identify row numbers
  and known fields without returning rejected values or unknown field names.
- Totals are reported separately by currency, in integer cents after duplicate
  replacement. They are not converted into a common currency.

The entire request is limited to 32 KiB. At most 100 diagnostics are returned;
the report explicitly indicates truncation and the total number of invalid rows.
Only SQL pipeline configurations are supported. Spark is rejected rather than
simulated with a different runtime.

On success download the normalized **output preview**, canonical pipeline JSON,
the actual server-rendered ConfigMap/CronJob YAML, or a fingerprinted evidence
JSON. Editing the date or records immediately invalidates previous downloads.
An input edit while a request is in flight cannot restore stale evidence.

The configured fixture or HTTP connector is **not read**. No SQL connection is
opened, no output is written, and no workload or deployment is launched. The
generated configuration and manifest retain the saved connector; sample rows are
not embedded into either artifact. The output preview includes `partition_date`
and is a diagnostic artifact, not an input file for the strict order schema.
This is not an execution receipt, production data-quality certification, or a
cluster admission check. Continue to Release review to inspect manifest policy.

## API

`GET /workbench/api/rehearsal/sample` returns the fixed bounded projection,
source provenance, original selected records and `sample_id`. Include that value
as `retained_sample_id` in the rehearsal POST only when submitting the unchanged
mapped `rows`. Both original files are hash-checked on every read; corrupted or
missing packaged evidence returns a sanitized HTTP 503.

Anonymous `POST /workbench/api/rehearsal` accepts the following envelope. These
are illustrative, caller-authored records, not observed data:

```json
{
  "config": {"name": "orders-hourly", "schedule": "0 * * * *"},
  "partition": "2026-11-09",
  "rows": [
    {"id": "example-a", "amount_cents": 100, "currency": "usd"},
    {"id": "example-a", "amount_cents": 250, "currency": "USD"},
    {"id": "example-b", "amount_cents": 700, "currency": "eur"}
  ]
}
```

The response contains `evidence` and `evidence_sha256`. Above, the input has
three rows, output has two, row 2 replaces row 1, and totals are USD 250 cents and
EUR 700 cents. HTTP 200 with `accepted: false` means a well-formed request whose
sample failed data validation. Invalid envelope/config/date/row-count or Spark
returns sanitized HTTP 422; a body larger than 32 KiB returns HTTP 413.

`sample_sha256` covers the submitted array, including order and duplicates.
`config_sha256` covers the validated default-expanded pipeline.
`evidence_sha256` covers the entire evidence object. Each uses SHA-256 of
sorted-key compact UTF-8 JSON (`ensure_ascii=False`). Fingerprints establish
content consistency; they are not signatures. Rejected sample values are absent
from the exported report; its sample fingerprint remains available.

## Verification

```powershell
.venv/Scripts/python -m pytest -q
node --test tests/*.test.cjs
.venv/Scripts/python -m ruff check src tests scripts
.venv/Scripts/python -m ruff format --check src tests scripts
.venv/Scripts/python -m bandit -r src -q
```

Regression coverage checks exact normalized output, independent currency totals,
duplicate lineage, deterministic hashes, reject-all semantics, safe diagnostics,
input bounds, unsupported connectors, unchanged filesystem state and protected
execution. Node tests exercise the rendered report and HTML escaping.
