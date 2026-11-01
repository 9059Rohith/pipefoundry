"use strict";
const page = document.body.dataset.page;
const $ = (s) => document.querySelector(s);
const esc = (v) =>
  String(v ?? "—").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const safeURL = (v) => {
  try {
    const u = new URL(v);
    return u.protocol === "https:" &&
      ["github.com", "api.github.com"].includes(u.hostname)
      ? u.href
      : "#";
  } catch {
    return "#";
  }
};
const link = (url, label) =>
  `<a href="${esc(safeURL(url))}" target="_blank" rel="noopener noreferrer">${esc(label)} ↗</a>`;
const fmt = (v) =>
  v
    ? new Date(v).toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      })
    : "—";
const status = (s) =>
  `<span class="status ${["success", "completed", "active", "configured"].includes(s) ? "good" : ["failure", "timed_out", "cancelled", "unavailable"].includes(s) ? "bad" : "muted"}">${esc(s || "unknown")}</span>`;
const descriptions = {
  overview: "Build with intent. Inspect the evidence before your next release.",
  repository: "The repository, dependencies and signals behind your pipeline.",
  workflows: "Inspect the automation defined in your public GitHub repository.",
  runs: "Real workflow executions, read directly from GitHub Actions.",
  run: "Inspect the steps, outcomes and timestamps for a workflow run.",
  releases: "Published versions and downloadable assets from your repository.",
  commits: "Trace changes to their authors, commits and source.",
  editor:
    "Compose typed pipeline configuration. Save your draft, then validate.",
  validation: "Check your draft against the same schema used by the runtime.",
  manifests:
    "Render a concrete Kubernetes bundle from validated configuration.",
  plans:
    "Compare your draft with recorded deployment state, without executing.",
  policy:
    "Inspect the execution boundaries built into every rendered workload.",
  audit: "A local record of the actions you take in this browser session.",
  integrations:
    "Know what is connected, what is available and what needs credentials.",
  agent: "Investigate repository evidence with a bounded, read-only AI agent.",
};
$("#description").textContent = descriptions[page] || "";
document
  .querySelector(`[data-nav="${page === "run" ? "runs" : page}"]`)
  ?.classList.add("active");
let repo = readStore("pf.repo") || "9059Rohith/pipefoundry";
$("#repository").value = repo;
const defaultConfig = {
  name: "orders-hourly",
  schedule: "0 * * * *",
  input: { connector: "fixture", path: "orders.json" },
  transform: "normalize_orders",
  output: { connector: "sqlite", path: "orders.db" },
  resources: { cpu_millis: 250, memory_mib: 256 },
};
function readStore(key) {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}
function writeStore(key, value) {
  try {
    sessionStorage.setItem(key, value);
  } catch {
    notice(
      "Browser storage is unavailable. Keep this page open to retain your draft.",
    );
  }
}
function audit(action, detail) {
  let events = [];
  try {
    events = JSON.parse(readStore("pf.audit") || "[]");
  } catch {}
  events.unshift({ action, detail, time: new Date().toISOString() });
  writeStore("pf.audit", JSON.stringify(events.slice(0, 100)));
}
function notice(text, error = false) {
  $("#notice").innerHTML = text
    ? `<div class="notice ${error ? "error" : ""}">${esc(text)}</div>`
    : "";
}
async function request(url, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 95000);
  try {
    const r = await fetch(url, { ...options, signal: controller.signal });
    const data = await r.json();
    if (!r.ok)
      throw new Error(
        typeof data.detail === "string"
          ? data.detail
          : `Request failed (${r.status}). Check the configuration and try again.`,
      );
    return data;
  } catch (e) {
    if (e.name === "AbortError")
      throw new Error(
        "The request timed out. Retry when the service is available.",
      );
    throw e;
  } finally {
    clearTimeout(timeout);
  }
}
async function inspect(view, extra = "") {
  const result = await request(
    `/workbench/api/github?repo=${encodeURIComponent(repo)}&view=${view}${extra}`,
  );
  $("#source-status").textContent =
    `Observed ${new Date(result.observed_at).toLocaleTimeString()} · cached 60s`;
  audit("Repository inspected", `${repo} · ${view}`);
  return result;
}
function panel(title, body, subtitle = "", action = "") {
  return `<section class="panel"><div class="panel-head"><div><h2>${esc(title)}</h2>${subtitle ? `<p>${esc(subtitle)}</p>` : ""}</div>${action}</div>${body}</section>`;
}
function empty(title, text, href = "", cta = "") {
  return `<div class="empty"><span class="empty-icon">⌘</span><strong>${esc(title)}</strong>${esc(text)}${href ? `<br><a class="button" href="${href}">${esc(cta)}</a>` : ""}</div>`;
}
function table(headers, rows) {
  return `<div class="table-wrap"><table><thead><tr>${headers.map((x) => `<th scope="col">${esc(x)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
}
function metric(label, value, sub = "", small = false) {
  return `<div class="metric"><dt>${esc(label)}</dt><dd${small ? ' class="small"' : ""}>${esc(value)}</dd><small>${esc(sub)}</small></div>`;
}
function facts(items) {
  return `<dl class="facts">${items.map(([a, b]) => `<div><dt>${esc(a)}</dt><dd>${esc(b)}</dd></div>`).join("")}</dl>`;
}
function getDraft() {
  const raw = readStore("pf.draft");
  if (!raw) return defaultConfig;
  try {
    return JSON.parse(raw);
  } catch {
    throw new Error(
      "Your saved draft is invalid JSON. Open the pipeline editor to repair it.",
    );
  }
}
function download(name, content, type = "text/plain") {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  audit("Artifact downloaded", name);
}
async function validate() {
  const result = await request("/workbench/api/validate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ config: getDraft() }),
  });
  audit(
    result.valid ? "Configuration validated" : "Validation rejected",
    getDraft().name || "unnamed draft",
  );
  return result;
}
function authField() {
  return `<div class="form-field"><label for="access-token">Control plane API token</label><input id="access-token" type="password" autocomplete="off" placeholder="Enter an authorized API token"><small>Used only for this request. Never saved to browser storage.</small></div>`;
}
function tokenHeaders() {
  const token = $("#access-token").value.trim();
  if (!token) throw new Error("Enter an authorized control plane API token.");
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  };
}
function runRows(runs) {
  return runs.map(
    (r) =>
      `<tr><td><a href="/workbench/run?id=${r.id}">${esc(r.display_title || r.name)}</a><span class="secondary mono">${esc(r.name)} · #${r.run_number}</span></td><td>${status(r.conclusion || r.status)}</td><td class="mono">${esc(r.head_branch)}</td><td><time>${esc(fmt(r.created_at))}</time></td><td>${esc(r.event)}</td></tr>`,
  );
}
async function overview() {
  const [repository, runs, workflows] = await Promise.allSettled([
    inspect("repository"),
    inspect("runs"),
    inspect("workflows"),
  ]);
  if (repository.status === "rejected") throw repository.reason;
  const d = repository.value.data;
  const rs = runs.status === "fulfilled" ? runs.value.data.workflow_runs : [];
  const ws =
    workflows.status === "fulfilled" ? workflows.value.data.workflows : [];
  $("#page-actions").innerHTML =
    '<a class="button primary" href="/workbench/editor">＋ New pipeline</a>';
  return `<dl class="metrics">${metric("Repository", d.name, "Public GitHub source", true)}${metric("Workflow definitions", workflows.status === "fulfilled" ? ws.length : "Unavailable", "Up to 50 definitions")}${metric("Recent executions", runs.status === "fulfilled" ? rs.length : "Unavailable", "Latest 30 GitHub runs")}${metric("Default branch", d.default_branch, "Repository configuration", true)}</dl><div class="split">${panel("Recent executions", runs.status === "rejected" ? empty("Executions unavailable", runs.reason.message) : rs.length ? table(["Workflow / execution", "Outcome", "Branch", "Started", "Trigger"], runRows(rs.slice(0, 6))) : empty("No workflow executions", "GitHub returned no workflow runs for this repository."), "Evidence from GitHub Actions", '<a href="/workbench/runs">View all executions →</a>')}${panel(
    "Your next pipeline",
    `<div class="flow"><div class="flow-node">Source<small>Typed input</small></div><span class="flow-arrow">→</span><div class="flow-node">Transform<small>Normalize orders</small></div><span class="flow-arrow">→</span><div class="flow-node">Sink<small>Validated output</small></div></div><p class="note">A draft becomes a validated configuration, then a versioned manifest. Deployment requires your authenticated control plane.</p><div class="panel-body">${facts(
      [
        ["Runtime", "Python / FastAPI"],
        ["Configuration", "Strict Pydantic schema"],
        ["Public access", "Read-only inspection"],
        ["Draft storage", "This browser session"],
      ],
    )}</div>`,
    "A deliberate path from configuration to execution",
  )}</div><div class="split equal">${panel(
    "Repository activity",
    `<div class="panel-body"><h3>${esc(d.full_name)}</h3><p class="muted">${esc(d.description || "No repository description provided.")}</p>${facts(
      [
        ["Last push", fmt(d.pushed_at)],
        ["Language", d.language],
        ["Open issues", d.open_issues_count],
      ],
    )}</div>`,
    "Live repository metadata",
    link(d.html_url, "Open GitHub"),
  )}${panel("Build, inspect, release", `<div class="panel-body steps"><a class="step" href="/workbench/editor"><div><h3>Compose your configuration</h3><p>Use typed connectors, schedules and resource limits.</p></div></a><a class="step" href="/workbench/validation"><div><h3>Validate before execution</h3><p>Resolve schema and compatibility issues on the server.</p></div></a><a class="step" href="/workbench/plans"><div><h3>Preview the deployment</h3><p>Compare your desired configuration with recorded state.</p></div></a></div>`)}</div>`;
}
async function repository() {
  const { data: d, source } = await inspect("repository");
  return (
    panel(
      d.full_name,
      `<div class="panel-body"><p>${esc(d.description || "No description published.")}</p>${facts(
        [
          ["Visibility", d.visibility],
          ["Default branch", d.default_branch],
          ["Primary language", d.language],
          ["License", d.license?.name || "Not specified"],
          ["Created", fmt(d.created_at)],
          ["Last updated", fmt(d.updated_at)],
          ["Last push", fmt(d.pushed_at)],
          ["Size", `${d.size} KiB`],
          ["Archived", d.archived ? "Yes" : "No"],
          ["Fork", d.fork ? "Yes" : "No"],
        ],
      )}<p class="mono muted">Source: ${link(source, "GitHub REST API")}</p></div>`,
      "Repository metadata read directly from GitHub",
      link(d.html_url, "Browse source"),
    ) +
    panel(
      "Repository signals",
      `<dl class="metrics">${metric("Stars", d.stargazers_count)}${metric("Forks", d.forks_count)}${metric("Open issues", d.open_issues_count)}${metric("Watchers", d.subscribers_count)}</dl><div class="panel-body toolbar"><a class="button" href="/workbench/workflows">Inspect workflows →</a><a class="button" href="/workbench/commits">Explore commit history →</a></div>`,
    )
  );
}
async function workflows() {
  const { data: d } = await inspect("workflows");
  let ws = d.workflows || [];
  return (
    panel(
      "Workflow definitions",
      ws.length
        ? table(
            ["Workflow", "State", "Definition path", "Inspect"],
            ws.map(
              (w) =>
                `<tr><td>${link(w.html_url, w.name)}</td><td>${status(w.state)}</td><td class="mono">${esc(w.path)}</td><td><a href="/workbench/runs?workflow=${w.id}">View executions →</a></td></tr>`,
            ),
          )
        : empty(
            "No workflow definitions",
            "No public Actions workflows were returned by GitHub.",
          ),
      "Up to 50 workflow definitions in the selected repository",
    ) +
    panel(
      "How workflow inspection works",
      `<div class="panel-body"><p class="muted">Definitions and execution history are read from the public GitHub Actions API. PipeFoundry does not dispatch, cancel or rerun workflows through this public workbench.</p><p>${link(`https://github.com/${repo}/actions`, "Manage workflows on GitHub")}</p></div>`,
    )
  );
}
async function runs() {
  const { data: d } = await inspect("runs");
  let rs = d.workflow_runs || [];
  const workflow = new URLSearchParams(location.search).get("workflow");
  if (workflow) rs = rs.filter((r) => String(r.workflow_id) === workflow);
  const body = panel(
    "Execution history",
    `<div class="panel-body"><div class="toolbar"><input id="run-search" type="search" aria-label="Search executions" placeholder="Search workflow, branch or execution…"><select id="run-status" aria-label="Filter outcome"><option value="">All outcomes</option><option>success</option><option>failure</option><option>cancelled</option><option>in_progress</option><option>queued</option></select></div><div id="run-results"></div><p class="search-info">Only the latest 30 repository runs are inspected.${workflow ? " A workflow filter is active." : ""}</p></div>`,
    "Real execution history, including failures and incomplete runs",
  );
  setTimeout(() => {
    const draw = () => {
      const q = $("#run-search").value.toLowerCase(),
        s = $("#run-status").value;
      const filtered = rs.filter(
        (r) =>
          (!s || (r.conclusion || r.status) === s) &&
          `${r.name} ${r.display_title} ${r.head_branch}`
            .toLowerCase()
            .includes(q),
      );
      $("#run-results").innerHTML = filtered.length
        ? table(
            ["Workflow / execution", "Outcome", "Branch", "Started", "Trigger"],
            runRows(filtered),
          )
        : empty(
            "No matching executions",
            "Change the filters or inspect a repository with workflow runs.",
          );
    };
    $("#run-search").addEventListener("input", draw);
    $("#run-status").addEventListener("change", draw);
    draw();
  }, 0);
  return body;
}
async function run() {
  const id = new URLSearchParams(location.search).get("id");
  if (!id || !/^\d+$/.test(id))
    return panel(
      "Choose an execution",
      empty(
        "No execution selected",
        "Open an execution from the history to inspect real job steps.",
        "/workbench/runs",
        "Browse executions",
      ),
    );
  const { data: d, source } = await inspect("run", `&run_id=${id}`);
  return panel(
    `Execution #${id}`,
    d.jobs?.length
      ? d.jobs
          .map(
            (j) =>
              `<div class="panel-body"><div class="toolbar"><h3>${esc(j.name)}</h3>${status(j.conclusion || j.status)}<span class="muted mono">${esc(fmt(j.started_at))} → ${esc(fmt(j.completed_at))}</span>${link(j.html_url, "GitHub logs")}</div>${table(
                ["Step", "Outcome", "Started", "Completed"],
                (j.steps || []).map(
                  (s) =>
                    `<tr><td>${s.number}. ${esc(s.name)}</td><td>${status(s.conclusion || s.status)}</td><td><time>${esc(fmt(s.started_at))}</time></td><td><time>${esc(fmt(s.completed_at))}</time></td></tr>`,
                ),
              )}</div>`,
          )
          .join("")
      : empty("No public jobs", "GitHub has not returned jobs for this run."),
    "Job and step outcomes from GitHub Actions",
    link(source, "Source API"),
  );
}
async function releases() {
  const { data: releases } = await inspect("releases");
  if (!releases.length)
    return panel(
      "Published releases",
      empty(
        "No releases published",
        "GitHub returned no public releases. Commit history and workflow runs are available independently.",
        "/workbench/commits",
        "Explore commits",
      ),
    );
  return releases
    .map((r) =>
      panel(
        r.name || r.tag_name,
        `<div class="panel-body"><div class="toolbar"><span class="pill">${esc(r.tag_name)}</span><span class="muted mono">${esc(fmt(r.published_at))}</span>${r.prerelease ? '<span class="pill">Prerelease</span>' : ""}</div><div class="release-notes">${esc(r.body || "No release notes provided.")}</div><h3>Release assets</h3>${
          r.assets.length
            ? table(
                ["Asset", "Size", "Downloads", "Download"],
                r.assets.map(
                  (a) =>
                    `<tr><td>${esc(a.name)}</td><td>${esc((a.size / 1024).toFixed(1))} KiB</td><td>${a.download_count}</td><td>${link(a.browser_download_url, "Download")}</td></tr>`,
                ),
              )
            : '<p class="muted">No binary assets attached.</p>'
        }</div>`,
        "Published release evidence",
        link(r.html_url, "Open release"),
      ),
    )
    .join("");
}
async function commits() {
  const { data: commits } = await inspect("commits");
  return panel(
    "Commit history",
    commits.length
      ? table(
          ["Commit", "Author", "Date", "Source"],
          commits.map(
            (c) =>
              `<tr><td>${esc(c.commit.message.split("\n")[0])}<span class="secondary mono">${esc(c.sha.slice(0, 12))}</span></td><td>${esc(c.commit.author?.name)}</td><td><time>${esc(fmt(c.commit.author?.date))}</time></td><td>${link(c.html_url, "Review commit")}</td></tr>`,
          ),
        )
      : empty("No commits returned", "GitHub returned no commit history."),
    "Latest 30 commits on the default branch",
  );
}
function editor() {
  const raw = readStore("pf.draft") || JSON.stringify(defaultConfig, null, 2);
  setTimeout(() => {
    $("#config-editor").value = raw;
    $("#save-draft").onclick = () => {
      try {
        const config = JSON.parse($("#config-editor").value);
        writeStore("pf.draft", JSON.stringify(config, null, 2));
        audit("Draft saved", config.name || "unnamed");
        notice(
          "Draft saved for this browser session. Open Validation to run the server checks.",
        );
      } catch {
        notice("Invalid JSON. Resolve the syntax error before saving.", true);
      }
    };
    $("#reset-draft").onclick = () => {
      $("#config-editor").value = JSON.stringify(defaultConfig, null, 2);
      notice(
        "Starter configuration loaded into the editor. Save to replace your session draft.",
      );
    };
    $("#download-draft").onclick = () => {
      try {
        const content = JSON.stringify(
          JSON.parse($("#config-editor").value),
          null,
          2,
        );
        download("pipeline.json", content, "application/json");
      } catch {
        notice("Invalid JSON. Resolve syntax errors before downloading.", true);
      }
    };
  }, 0);
  return `<div class="split">${panel("Configuration workspace", `<div class="filebar"><span>pipeline.json</span><small>JSON · strict schema</small></div><textarea id="config-editor" class="editor" aria-label="Pipeline configuration JSON" spellcheck="false"></textarea><div class="panel-body toolbar"><button id="save-draft" class="primary">Save draft</button><button id="download-draft">Download JSON</button><button id="reset-draft">Load starter</button><a class="button" href="/workbench/validation">Validate →</a></div>`, "This starter is configuration only; it has not been executed.")}${panel(
    "Configuration guide",
    `<div class="panel-body">${facts([
      ["name", "Lowercase / hyphens, 1–40"],
      ["schedule", "Five-field cron · UTC"],
      ["transform", "normalize_orders"],
      ["CPU", "50–4,000 millicores"],
      ["Memory", "64–8,192 MiB"],
      ["Spark minimum", "1,024 MiB"],
    ])}<p class="muted">Fixture input works with SQLite or PostgreSQL. Spark JSON requires Parquet output. Paths must remain relative to the data root.</p><p class="note">Drafts are stored in sessionStorage. Closing the browser session clears them. Export JSON for a durable copy.</p></div>`,
    "Closed execution choices, validated on the server",
  )}</div>`;
}
async function validation() {
  const d = getDraft();
  setTimeout(() => {
    $("#validate-button").onclick = async () => {
      const b = $("#validate-button");
      b.disabled = true;
      try {
        const r = await validate();
        $("#validation-result").innerHTML = r.valid
          ? `<div class="result-banner good">✓ Configuration accepted by the runtime schema</div><ul class="checks"><li><span>✓</span><div>Strict configuration fields<small>Unknown fields rejected, safe paths enforced.</small></div></li><li><span>✓</span><div>Connector compatibility<small>${esc(r.config.input.connector)} → ${esc(r.config.output.connector)}</small></div></li><li><span>✓</span><div>Schedule and resource limits<small>${esc(r.config.schedule)} · ${r.config.resources.cpu_millis}m CPU · ${r.config.resources.memory_mib} MiB</small></div></li></ul><div class="panel-body"><p class="mono wrap">SHA-256 ${esc(r.sha256)}</p><a class="button primary" href="/workbench/manifests">Inspect rendered manifest →</a></div>`
          : `<div class="result-banner bad">${r.errors.length} validation issue(s)</div><ul class="checks">${r.errors.map((e) => `<li><span class="bad">×</span><div>${esc(e.message)}<small>${esc(e.type)}</small></div></li>`).join("")}</ul>`;
      } catch (e) {
        notice(e.message, true);
      } finally {
        b.disabled = false;
      }
    };
  }, 0);
  return `<div class="split">${panel(
    "Runtime validation",
    `<div class="panel-body">${facts([
      ["Pipeline", d.name],
      ["Schedule", d.schedule],
      ["Execution", "Not requested"],
    ])}<p class="muted">Validation checks the saved draft against the server's Pipeline model and renders a manifest in memory. It does not write metadata or launch a workload.</p><div class="toolbar"><button class="primary" id="validate-button">Run validation</button><a class="button" href="/workbench/editor">Edit draft</a></div></div>`,
    "Real schema checks. No synthetic validation results.",
  )}${panel("Validation results", '<div id="validation-result">' + empty("Ready to validate", "Run the server checks to see your configuration results.") + "</div>")}</div>`;
}
async function manifests() {
  const r = await validate();
  if (!r.valid)
    return panel(
      "Manifest unavailable",
      empty(
        "Resolve validation issues first",
        "Your saved configuration was rejected by the runtime schema.",
        "/workbench/validation",
        "Review validation",
      ),
    );
  setTimeout(() => {
    $("#download-manifest").onclick = () =>
      download(`${r.config.name}-bundle.yaml`, r.manifest, "application/yaml");
  }, 0);
  return panel(
    "Kubernetes bundle",
    `<div class="panel-body"><div class="toolbar"><button id="download-manifest" class="primary">↓ Download YAML</button><a class="button" href="/workbench/plans">Preview deployment →</a><span class="muted mono">Draft revision 1 · not deployed</span></div><pre class="terminal">${esc(r.manifest)}</pre><p class="mono muted wrap">Configuration SHA-256 ${esc(r.sha256)}</p></div>`,
    "Generated by the same object renderer used by the control plane",
  );
}
function plans() {
  setTimeout(() => {
    $("#preview-plan").onclick = async () => {
      const b = $("#preview-plan");
      b.disabled = true;
      try {
        const r = await request("/deployments/preview", {
          method: "POST",
          headers: tokenHeaders(),
          body: JSON.stringify({
            config: getDraft(),
            executor: $("#executor").value,
          }),
        });
        audit("Deployment preview", `${r.name} · ${r.action}`);
        $("#plan-result").innerHTML =
          `<div class="result-banner good">Preview generated · ${esc(r.action)}</div><div class="panel-body">${facts(
            [
              ["Pipeline", r.name],
              ["Action", r.action],
              ["Current revision", r.current?.revision || "None"],
              ["Operation in progress", r.operation_in_progress ? "Yes" : "No"],
            ],
          )}<p class="muted">${esc(r.comparison)}</p><pre class="terminal">${esc(JSON.stringify(r.changes, null, 2))}</pre><p class="mono wrap">Desired SHA-256 ${esc(r.desired_fingerprint)}</p></div>`;
      } catch (e) {
        notice(e.message, true);
      } finally {
        b.disabled = false;
        $("#access-token").value = "";
      }
    };
  }, 0);
  return `<div class="split">${panel("Compare desired state", `<div class="panel-body">${authField()}<div class="form-field"><label for="executor">Target executor</label><select id="executor"><option value="local">Local worker</option><option value="kubernetes">Kubernetes</option></select></div><p class="muted">Uses the authenticated deployment preview endpoint to compare your saved draft with recorded state. This comparison does not reserve a release or deploy a workload.</p><button class="primary" id="preview-plan">Generate preview</button></div>`, "Authenticated · metadata-only comparison")}${panel("Deployment preview", '<div id="plan-result">' + empty("No preview generated", "Provide your API token to compare the draft against your control plane.") + "</div>")}</div>`;
}
async function policy() {
  const result = await validate();
  if (!result.valid)
    return panel(
      "Policy inspection",
      empty(
        "Configuration must pass validation",
        "Resolve the schema errors before inspecting generated workload controls.",
        "/workbench/validation",
        "Review validation",
      ),
    );
  const rules = [
    ["Non-root worker", "runAsUser: 10001; runAsNonRoot: true"],
    ["No service account token", "automountServiceAccountToken: false"],
    ["Read-only root filesystem", "readOnlyRootFilesystem: true"],
    [
      "No privilege escalation",
      "allowPrivilegeEscalation: false; capabilities: drop ALL",
    ],
    [
      "Bounded resources",
      `${result.config.resources.cpu_millis}m CPU; ${result.config.resources.memory_mib} MiB memory`,
    ],
    ["Bounded execution", "activeDeadlineSeconds: 300; backoffLimit: 2"],
    ["No overlapping schedules", "concurrencyPolicy: Forbid; UTC timezone"],
    [
      "Config is data",
      "Closed connector and transform choices; safe relative paths",
    ],
  ];
  return (
    panel(
      "Generated workload controls",
      `<div class="result-banner good">✓ Inspected the rendered manifest for ${esc(result.config.name)}</div><ul class="checks">${rules.map(([a, b]) => `<li><span>✓</span><div>${esc(a)}<small class="mono">${esc(b)}</small></div></li>`).join("")}</ul>`,
      "These controls describe the generated configuration, not a live cluster audit.",
    ) +
    panel(
      "Access boundary",
      `<div class="panel-body"><p class="muted">Public pages can inspect public GitHub data and validate configuration. Deployments, release apply, rollback, backfill, logs, private audit metadata and AI provider calls require your control plane API token. The agent can only read GitHub evidence within a three-step / four-tool-call budget.</p><a class="button" href="/workbench/manifests">Review the manifest →</a></div>`,
    )
  );
}
function auditPage() {
  let events = [];
  try {
    events = JSON.parse(readStore("pf.audit") || "[]");
  } catch {}
  setTimeout(() => {
    $("#export-audit").onclick = () =>
      download(
        "pipefoundry-session-audit.json",
        JSON.stringify(events, null, 2),
        "application/json",
      );
    $("#clear-audit").onclick = () => {
      writeStore("pf.audit", "[]");
      load();
      notice("Session audit cleared.");
    };
  }, 0);
  return panel(
    "Browser session activity",
    `<div class="panel-body"><div class="toolbar"><button id="export-audit">↓ Export JSON</button><button id="clear-audit">Clear session history</button></div><p class="muted">This is a client-side activity record, retained for this tab session. It is not the authenticated server execution audit log.</p></div>${
      events.length
        ? table(
            ["Observed at", "Action", "Context"],
            events.map(
              (e) =>
                `<tr><td class="audit-time">${esc(fmt(e.time))}</td><td>${esc(e.action)}</td><td>${esc(e.detail)}</td></tr>`,
            ),
          )
        : empty(
            "No session actions yet",
            "Repository inspections, saved drafts and validations will appear here.",
          )
    }`,
    "Up to 100 real actions from this browser session",
  );
}
async function integrations() {
  const d = await request("/workbench/api/integrations");
  return (
    panel(
      "Connected capabilities",
      `<div class="integration-row"><div class="integration-symbol">⑂</div><div class="integration-name"><h3>GitHub</h3><p>Anonymous public repository, workflows, runs, releases and commits.</p></div>${status("configured")}<a class="button" href="/workbench/repository">Inspect →</a></div><div class="integration-row"><div class="integration-symbol">{ }</div><div class="integration-name"><h3>Pipeline runtime</h3><p>Live server validation and deterministic Kubernetes manifest rendering.</p></div>${status("configured")}<a class="button" href="/workbench/validation">Validate →</a></div><div class="integration-row"><div class="integration-symbol">✧</div><div class="integration-name"><h3>${esc(d.ai_provider === "gemini" ? "Gemini API" : "OpenAI Responses API")}</h3><p>${d.ai_configured ? `Connected: ${esc(d.ai_model)}. An authorized control plane token is required.` : "Server provider key is missing. No AI output is generated without credentials."}</p></div>${status(d.ai_configured ? "configured" : "unavailable")}<a class="button" href="/workbench/agent">Open agent →</a></div><div class="integration-row"><div class="integration-symbol">▧</div><div class="integration-name"><h3>Execution control plane</h3><p>Local and Kubernetes executors. Authenticated API access required.</p></div><span class="pill">Protected</span><a class="button" href="/workbench/plans">Preview →</a></div>`,
      "Live configuration presence; credentials are never disclosed.",
    ) +
    panel(
      "Integration boundaries",
      `<div class="panel-body"><p class="muted">Public GitHub reads never attach a server token, so private repository data stays outside this public surface. GitHub's anonymous rate limit applies. Provider keys belong in server environment configuration; API tokens entered for plans or the agent stay in memory for a single request.</p></div>`,
    )
  );
}
async function agent() {
  const d = await request("/workbench/api/integrations");
  setTimeout(() => {
    $("#agent-submit").onclick = async () => {
      const b = $("#agent-submit");
      b.disabled = true;
      try {
        const headers = tokenHeaders();
        const question = $("#agent-question").value.trim();
        if (question.length < 5)
          throw new Error(
            "Write a specific question of at least five characters.",
          );
        $("#agent-output").innerHTML =
          '<div class="loading">Inspecting repository evidence…</div>';
        const r = await request("/workbench/api/agent", {
          method: "POST",
          headers,
          body: JSON.stringify({ repo, question }),
        });
        audit(
          "Agent analysis completed",
          `${repo} · ${r.trace.length} tool reads`,
        );
        $("#agent-output").innerHTML =
          `<div class="panel-body"><div class="agent-response">${esc(r.answer)}</div><p class="mono muted">Provider: ${esc(r.provider || d.ai_provider)} · ${esc(r.model)}</p><h3>Tool evidence</h3>${r.trace.map((t) => `<div class="activity-item"><span class="activity-icon">↳</span><div><p>${esc(t.tool)} · ${esc(t.view)}</p><small>${link(t.source, "Source")} · ${esc(fmt(t.observed_at))}</small></div></div>`).join("")}</div>`;
      } catch (e) {
        notice(e.message, true);
        $("#agent-output").innerHTML = empty(
          "Analysis not completed",
          e.message,
        );
      } finally {
        b.disabled = false;
        $("#access-token").value = "";
      }
    };
  }, 0);
  return `<div class="split">${panel("Ask Foundry", `<div class="panel-body">${!d.ai_configured ? '<div class="notice">AI provider credentials are not configured on this server. Agent execution is unavailable.</div>' : ""}${d.ai_configured ? `<div class="result-banner good">Connected: ${esc(d.ai_provider)} · ${esc(d.ai_model)}</div>` : ""}${authField()}<div class="form-field"><label for="agent-question">What should the agent investigate?</label><textarea id="agent-question" rows="5" maxlength="1500" placeholder="Inspect recent workflow failures and summarize evidence for release readiness."></textarea><small>Repository: ${esc(repo)}. Public GitHub evidence is sent to the configured provider.</small></div><button class="primary" id="agent-submit" ${!d.ai_configured ? "disabled" : ""}>✧ Investigate repository</button><p class="note">Read-only tools · max 3 model steps · max 4 tool calls · no shell, deploy or workflow dispatch. Gemini free-tier quotas apply; quota errors are explicit and no paid fallback is used.</p></div>`, "Grounded analysis with inspectable tool evidence")}${panel("Analysis & evidence", '<div id="agent-output">' + empty("Ready for an investigation", "Findings appear only after a real provider request and GitHub inspection.") + "</div>")}</div>`;
}
const controllers = {
  overview,
  repository,
  workflows,
  runs,
  run,
  releases,
  commits,
  editor,
  validation,
  manifests,
  plans,
  policy,
  audit: auditPage,
  integrations,
  agent,
};
async function load() {
  notice("");
  $("#content").innerHTML = '<div class="loading">Loading workspace…</div>';
  try {
    $("#content").innerHTML = await (controllers[page] || overview)();
  } catch (e) {
    $("#content").innerHTML = panel(
      "Workspace unavailable",
      empty(
        "Inspection could not be completed",
        e.message,
        "/workbench/integrations",
        "Check integrations",
      ),
    );
    notice(e.message, true);
  }
}
$("#repository-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const candidate = $("#repository").value.trim();
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(candidate)) {
    notice("Use a GitHub owner/repository name.", true);
    return;
  }
  repo = candidate;
  writeStore("pf.repo", repo);
  load();
});
load();
