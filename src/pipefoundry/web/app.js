"use strict";
const page = document.body.dataset.page;
const icon = FoundryUI.icon;
const $ = (s) => document.querySelector(s);
const esc = (v) =>
  String(v ?? "—").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const safeURL = (value) => FoundryUI.safeURL(value) || "#";
const link = (url, label) =>
  FoundryUI.safeURL(url)
    ? `<a href="${esc(safeURL(url))}" target="_blank" rel="noopener noreferrer">${esc(label)} ${icon("external")}</a>`
    : `<span>${esc(label)}</span>`;
const fmt = (v) =>
  v
    ? new Date(v).toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      })
    : "—";
const status = (s) =>
  `<span class="status ${["success", "completed", "active", "configured"].includes(s) ? "good" : ["failure", "timed_out", "cancelled", "unavailable"].includes(s) ? "bad" : "muted"}">${esc(s || "unknown")}</span>`;
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
    if (!r.ok) {
      const failure = new Error(
        typeof data.detail === "string"
          ? data.detail
          : `Request failed (${r.status}). Try again later.`,
      );
      failure.status = r.status;
      failure.retryAfter = FoundryUI.retryAfterSeconds(r.headers.get("Retry-After"));
      throw failure;
    }
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
  const observed = new Date(result.observed_at).toLocaleString();
  const validated = result.validated_at ? new Date(result.validated_at).toLocaleString() : observed;
  $("#source-status").textContent = `${view} · captured ${observed} · checked ${validated} · ${result.stale ? "dated cache" : result.cache_status === "live" ? "live response" : "validated cache"}`;
  if (result.stale)
    notice(
      result.warning ||
        "Historical cached evidence is shown at its original observation time.",
    );
  audit("Repository inspected", `${repo} · ${view}`);
  return result;
}
function sectionArt(name) {
  return `<div class="section-plate"><img src="/workbench/art/${name}.svg" alt="" width="760" height="340" loading="lazy" decoding="async"></div>`;
}
function panel(title, body, subtitle = "", action = "") {
  return `<section class="panel"><div class="panel-head"><div><h2>${esc(title)}</h2>${subtitle ? `<p>${esc(subtitle)}</p>` : ""}</div>${action}</div>${body}</section>`;
}
function empty(title, text, href = "", cta = "") {
  return `<div class="empty"><span class="empty-icon">${icon("file")}</span><strong>${esc(title)}</strong>${esc(text)}${href ? `<br><a class="button" href="${href}">${esc(cta)}</a>` : ""}</div>`;
}
function table(headers, rows) {
  const searchable =
    rows.length > 3 && !headers[0].startsWith("Workflow / execution");
  const tools = searchable
    ? `<div class="table-tools"><input type="search" data-table-filter aria-label="Filter table records" placeholder="Filter these records…"><span data-table-count>${rows.length} records</span></div>`
    : "";
  const contents = rows.map((row) =>
    row
      .replace("<tr>", "<tr data-inspect-row>")
      .replace(
        "</tr>",
        `<td class="row-inspect"><button class="icon-button" data-inspect-record aria-label="Inspect record">${icon("inspect")}</button></td></tr>`,
      ),
  );
  return `<div class="data-table">${tools}<div class="table-wrap"><table><thead><tr>${headers.map((x) => `<th scope="col">${esc(x)}</th>`).join("")}<th scope="col"><span class="sr-only">Details</span></th></tr></thead><tbody>${contents.join("")}</tbody></table></div><p class="table-empty" data-table-empty hidden>No matching records. Change the filter to see more results.</p></div>`;
}
function metric(label, value, sub = "", small = false) {
  const note = sub ? `<small>${esc(sub)}</small>` : "";
  return `<div class="metric"><dt>${esc(label)}</dt><dd${small ? ' class="small"' : ""}>${esc(value)}${note}</dd></div>`;
}
function facts(items) {
  return `<dl class="facts">${items.map(([a, b]) => `<div><dt>${esc(a)}</dt><dd>${esc(b)}</dd></div>`).join("")}</dl>`;
}
function getDraft() {
  const raw = readStore("pf.draft");
  if (!raw) return defaultConfig;
  try {
    return FoundryUI.parseDraft(raw);
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
  const data = repository.status === "fulfilled" ? repository.value.data : null;
  const metadataUnavailable = () => empty(
    "Repository unavailable",
    repository.reason.message,
    "/workbench/repository",
    "Retry repository inspection",
  );
  const executions =
    runs.status === "fulfilled" ? runs.value.data.workflow_runs || [] : [];
  const definitions =
    workflows.status === "fulfilled"
      ? workflows.value.data.workflows || []
      : [];
  const summary = data
    ? `<section class="repository-summary"><div><div class="summary-identity">${icon("repo")}<h2>${esc(data.full_name)}</h2></div><p>${esc(data.description || "Explore the repository and the evidence behind its workflows.")}</p></div><div class="summary-context"><span>${icon("workflow")} ${esc(data.default_branch)}</span><span>${esc(data.language || "Language not specified")}</span>${link(data.html_url, "Open source")}</div></section>`
    : panel("Repository inspection", metadataUnavailable());
  return `${summary}<div class="split">${panel("Recent executions", runs.status === "rejected" ? empty("Executions unavailable", runs.reason.message) : executions.length ? table(["Workflow / execution", "Outcome", "Branch", "Started", "Trigger"], runRows(executions.slice(0, 6))) : empty("No workflow executions", "GitHub returned no runs for the selected repository."), "Observed GitHub Actions history · outcomes are not simulated", '<a href="/workbench/runs">All executions ' + icon("arrow") + "</a>")}${panel("Build a pipeline", `<div class="panel-body steps"><a class="step" href="/workbench/editor"><div><h3>Configure</h3><p>Compose a typed source, transform and destination.</p></div></a><a class="step" href="/workbench/validation"><div><h3>Validate</h3><p>Check schedule, resources and connector compatibility.</p></div></a><a class="step" href="/workbench/manifests"><div><h3>Inspect the artifact</h3><p>Copy or download the rendered Kubernetes bundle.</p></div></a><a class="step" href="/workbench/plans"><div><h3>Preview a plan</h3><p>Compare recorded state through the protected control plane.</p></div></a></div>`, "Configuration is a draft until the runtime validates it.")}</div><dl class="metrics">${metric("Workflow definitions", workflows.status === "fulfilled" ? definitions.length : "Unavailable", "Up to 50 definitions")}${metric("Recent executions", runs.status === "fulfilled" ? executions.length : "Unavailable", "Latest 30 returned runs")}${metric("Open issues", data ? data.open_issues_count : "Unavailable", "Repository observation")}${metric("Last push", data ? new Date(data.pushed_at).toLocaleDateString() : "Unavailable", "See the source observation time", true)}</dl><div class="split equal">${panel(
    "Repository details",
    data ? `<div class="panel-body">${facts([
      ["Default branch", data.default_branch],
      ["Primary language", data.language],
      ["License", data.license?.name || "Not specified"],
      ["Last updated", fmt(data.updated_at)],
    ])}</div>` : metadataUnavailable(),
    "Public metadata, with dated cache fallback when needed.",
    '<a href="/workbench/repository">Inspect repository ' +
      icon("arrow") +
      "</a>",
  )}${panel("Ask about the evidence", `<div class="panel-body"><p class="muted">The public Foundry agent inspects this project's GitHub repository before answering. Every answer includes the tool records and their observation times.</p><div class="toolbar"><a class="button" href="/workbench/agent">${icon("agent")} Open Foundry agent</a><a class="button" href="/workbench/policy">${icon("shield")} Review boundaries</a></div><p class="note">No sign-in. Read-only tools. Shared demo allowances apply.</p></div>`)}</div>`;
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
        `<div class="panel-body"><div class="toolbar"><span class="pill">${esc(r.tag_name)}</span><span class="muted mono">${esc(fmt(r.published_at))}</span>${r.prerelease ? '<span class="pill">Prerelease</span>' : ""}</div><div class="release-notes agent-response">${FoundryUI.markdown(r.body || "No release notes provided.")}</div><h3>Release assets</h3>${
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
function validationResult(result) {
  if (!result.valid)
    return `<div class="result-banner bad">${icon("info")} ${result.errors.length} validation issue${result.errors.length === 1 ? "" : "s"}</div><ul class="checks">${result.errors.map((error) => `<li><span>${icon("close")}</span><div>${esc(error.message)}<small>${esc(error.type)}</small></div></li>`).join("")}</ul><div class="panel-body"><a class="button" href="/workbench/editor">Return to editor ${icon("arrow")}</a></div>`;
  return `<div class="result-banner good">${icon("check")} Configuration accepted by the runtime schema</div><ul class="checks"><li><span>${icon("check")}</span><div>Strict fields and safe paths<small>Unknown fields and paths outside the data root are rejected.</small></div></li><li><span>${icon("check")}</span><div>Compatible connectors<small>${esc(result.config.input.connector)} → ${esc(result.config.output.connector)}</small></div></li><li><span>${icon("check")}</span><div>Schedule and resources<small>${esc(result.config.schedule)} UTC · ${result.config.resources.cpu_millis}m CPU · ${result.config.resources.memory_mib} MiB</small></div></li></ul><div class="panel-body"><p class="mono wrap">Configuration SHA-256<br>${esc(result.sha256)}</p><a class="button primary" href="/workbench/review">Review release ${icon("arrow")}</a> <a class="button" href="/workbench/manifests">Inspect manifest ${icon("file")}</a></div>`;
}
async function copyText(value, label = "Text") {
  try {
    await navigator.clipboard.writeText(value);
    notice(label + " copied to the clipboard.");
  } catch {
    notice(
      "Clipboard access is unavailable. Use the download action to save this artifact.",
      true,
    );
  }
}
function editor() {
  const raw =
    readStore("pf.pending-draft") ||
    readStore("pf.draft") ||
    JSON.stringify(defaultConfig, null, 2);
  setTimeout(() => {
    const input = $("#config-editor"),
      highlighted = $("#syntax-view"),
      lines = $("#line-numbers");
    input.value = raw;
    function paint(invalidate = true) {
      highlighted.innerHTML = FoundryUI.highlightJSON(input.value) + "\n";
      lines.textContent = input.value
        .split("\n")
        .map((_, index) => index + 1)
        .join("\n");
      highlighted.scrollTop = input.scrollTop;
      highlighted.scrollLeft = input.scrollLeft;
      lines.scrollTop = input.scrollTop;
      try {
        const config = FoundryUI.parseDraft(input.value);
        $("#draft-summary").innerHTML = facts([
          ["Pipeline", config.name || "Not specified"],
          ["Schedule", (config.schedule || "Not specified") + " UTC"],
          ["CPU", (config.resources?.cpu_millis ?? 250) + " millicores"],
          ["Memory", (config.resources?.memory_mib ?? 256) + " MiB"],
        ]);
        const connectors = {
          fixture: "Fixture",
          orders_api: "Orders API",
          spark_json: "Spark JSON",
          sqlite: "SQLite",
          postgres: "PostgreSQL",
          parquet: "Parquet",
        };
        $("#pipeline-flow").innerHTML =
          `<div class="flow-node">${esc(connectors[config.input?.connector || "fixture"] || config.input?.connector)}<small>Source</small></div>${icon("arrow")}<div class="flow-node">${esc(!config.transform || config.transform === "normalize_orders" ? "Normalize orders" : config.transform)}<small>Transform</small></div>${icon("arrow")}<div class="flow-node">${esc(connectors[config.output?.connector || "sqlite"] || config.output?.connector)}<small>Sink</small></div>`;
      } catch {
        $("#draft-summary").innerHTML =
          '<p class="note">Complete valid JSON to preview the configuration fields.</p>';
        $("#pipeline-flow").innerHTML =
          '<p class="note">A JSON object is required to preview connectors.</p>';
      }
      if (invalidate) {
        $("#editor-state").textContent = "Unsaved changes";
        $("#inspector-validation").innerHTML = empty(
          "Validate this draft",
          "Configuration changed. Run validation to inspect it.",
        );
        $("#inline-results").innerHTML = empty(
          "Draft changed",
          "Validate the current configuration to update its results.",
        );
        writeStore("pf.pending-draft", input.value);
      }
    }
    function save() {
      try {
        const config = FoundryUI.parseDraft(input.value);
        writeStore("pf.draft", JSON.stringify(config, null, 2));
        try {
          sessionStorage.removeItem("pf.pending-draft");
        } catch {}
        $("#editor-state").textContent = "Session draft saved";
        audit("Draft saved", config.name || "unnamed");
        return config;
      } catch (error) {
        notice(
          error instanceof TypeError
            ? "Pipeline configuration must be a JSON object."
            : "JSON syntax is invalid. Check quotes, commas and closing braces before continuing.",
          true,
        );
        return null;
      }
    }
    input.addEventListener("input", () => paint());
    input.addEventListener("scroll", () => {
      highlighted.scrollTop = input.scrollTop;
      highlighted.scrollLeft = input.scrollLeft;
      lines.scrollTop = input.scrollTop;
    });
    $("#save-draft").onclick = () => {
      if (save()) notice("Draft saved for this browser session.");
    };
    $("#format-json").onclick = () => {
      try {
        input.value = JSON.stringify(
          FoundryUI.parseDraft(input.value),
          null,
          2,
        );
        paint();
      } catch {
        notice(
          "JSON syntax is invalid. Format is available after the syntax is corrected.",
          true,
        );
      }
    };
    $("#reset-draft").onclick = () => {
      input.value = JSON.stringify(defaultConfig, null, 2);
      paint();
      notice("Starter loaded into the editor. It has not been executed.");
    };
    $("#download-draft").onclick = () => {
      const config = save();
      if (config)
        download(
          "pipeline.json",
          JSON.stringify(config, null, 2),
          "application/json",
        );
    };
    $("#editor-validate").onclick = async () => {
      const config = save();
      if (!config) return;
      const button = $("#editor-validate");
      button.disabled = true;
      button.textContent = "Validating…";
      notice("");
      try {
        const result = await validate();
        $("#inline-results").innerHTML = validationResult(result);
        $("#inspector-validation").innerHTML =
          `<div class="result-banner ${result.valid ? "good" : "bad"}">${icon(result.valid ? "check" : "info")}${result.valid ? "Configuration accepted" : "Changes required"}</div><p class="note">${result.valid ? "Manifest rendering is ready. No workload has been executed." : "Review the runtime validation issues below."}</p>`;
        $("#editor-state").textContent = result.valid
          ? "Validated session draft"
          : "Validation issues";
      } catch (error) {
        notice(error.message, true);
      } finally {
        button.disabled = false;
        button.innerHTML = "Validate configuration";
      }
    };
    paint(false);
  }, 0);
  return `<div class="editor-layout"><section class="panel"><div class="editor-toolbar"><div class="editor-file">${icon("file")}pipeline.json <span class="draft-label">Draft</span></div><button id="format-json">Format JSON</button><button id="save-draft">Save draft</button><button id="editor-validate" class="primary">Validate configuration</button></div><div class="code-editor"><div id="line-numbers" class="line-numbers" aria-hidden="true"></div><div class="code-area"><pre id="syntax-view" class="syntax-view" aria-hidden="true"></pre><textarea id="config-editor" class="code-input" aria-label="Pipeline configuration JSON" spellcheck="false" wrap="off" autocomplete="off" autocapitalize="off"></textarea></div></div><div class="editor-status"><span>JSON · UTF-8</span><span id="editor-state">Session draft</span><span>Not executed</span></div></section><section class="panel inspector"><h2>Configuration</h2><div id="pipeline-flow" class="flow"></div><div id="draft-summary"></div>${sectionArt("transform-cutaway")}<div class="inspector-result"><h3>Validation</h3><div id="inspector-validation">${empty("Not validated yet", "Run validation to inspect this draft.")}</div></div><div class="inspector-actions"><button id="download-draft">${icon("download")} Export JSON</button><button id="reset-draft">${icon("file")} Load starter</button></div></section></div><section class="panel editor-results"><div class="panel-head"><h2>Validation results</h2><a href="/workbench/validation">Open validation ${icon("arrow")}</a></div><div id="inline-results">${empty("Ready when you are", "Results appear after a real server validation.")}</div></section>`;
}
async function validation() {
  const draft = getDraft();
  setTimeout(() => {
    $("#validate-button").onclick = async () => {
      const button = $("#validate-button");
      button.disabled = true;
      button.textContent = "Validating…";
      try {
        $("#validation-result").innerHTML = validationResult(await validate());
      } catch (error) {
        notice(error.message, true);
      } finally {
        button.disabled = false;
        button.textContent = "Run validation";
      }
    };
  }, 0);
  return `<div class="split equal">${panel(
    "Runtime validation",
    `<div class="panel-body">${facts([
      ["Pipeline", draft.name],
      ["Schedule", draft.schedule],
      ["Execution", "Not requested"],
    ])}<p class="muted">Check the saved draft against the same strict schema used by the pipeline runtime. Validation creates no revisions and launches no workload.</p><div class="toolbar"><button class="primary" id="validate-button">${icon("check")} Run validation</button><a class="button" href="/workbench/editor">Edit configuration</a></div></div>`,
    "A real schema check before an artifact is generated.",
  )}${panel("Validation results", `<div id="validation-result">${empty("Ready to validate", "Run the server checks to see the saved draft's results.")}</div>`)}</div>`;
}
async function manifests() {
  const result = await validate();
  if (!result.valid)
    return panel(
      "Manifest unavailable",
      validationResult(result),
      "Resolve the runtime schema issues before rendering a bundle.",
    );
  setTimeout(() => {
    $("#download-manifest").onclick = () =>
      download(
        `${result.config.name}-bundle.yaml`,
        result.manifest,
        "application/yaml",
      );
    $("#copy-manifest").onclick = () =>
      copyText(result.manifest, "Kubernetes bundle");
  }, 0);
  return panel(
    "Kubernetes bundle",
    `<div class="panel-body"><div class="toolbar"><span class="editor-file">${icon("file")}${esc(result.config.name)}-bundle.yaml</span><button id="copy-manifest">${icon("copy")} Copy YAML</button><button id="download-manifest" class="primary">${icon("download")} Download YAML</button><a class="button" href="/workbench/plans">Preview plan ${icon("arrow")}</a></div>${sectionArt("bundle-seal")}<div class="result-banner good">${icon("check")} Rendered from validated configuration · not deployed</div><pre class="terminal">${esc(result.manifest)}</pre><p class="mono wrap muted">Configuration SHA-256<br>${esc(result.sha256)}</p><details><summary>Validated configuration</summary><pre class="terminal">${esc(JSON.stringify(result.config, null, 2))}</pre></details></div>`,
    "The same object renderer used by the control plane. Copy or download the real artifact.",
  );
}
function review() {
  $("#page-actions").innerHTML = '<a class="button" href="/workbench/editor">Edit candidate ' + icon("code") + '</a>';
  setTimeout(() => {
    let latest = null;
    const baselineInput = $("#review-baseline-json");
    baselineInput.value = readStore("pf.review-baseline") || "";
    function showComparison(comparison) {
      if (!comparison) return `<div class="review-empty"><strong>Give this change a reference point.</strong><p>Capture the validated candidate as your baseline, edit it in the pipeline editor, then return to compare both rendered bundles.</p></div>`;
      const rows = comparison.config_changes.map((change) => `<tr><td><code>${esc(change.path)}</code><span class="secondary">${esc(change.reason)}</span></td><td class="mono">${esc(JSON.stringify(change.before))}</td><td class="mono">${esc(JSON.stringify(change.after))}</td><td><span class="review-state ${change.risk === "escalation" ? "warn" : "na"}">${esc(change.risk)}</span></td></tr>`);
      return `<div class="review-diff-summary"><strong>${comparison.changed ? `${comparison.config_changes.length} configuration changes · ${comparison.escalations} risk escalations` : "No configuration or manifest changes"}</strong><p>${esc(comparison.scope)}</p></div>${rows.length ? table(["Configuration field", "Baseline", "Candidate", "Review signal"], rows) : ""}${comparison.new_findings.length ? `<div class="notice error">New policy findings: ${esc(comparison.new_findings.join(", "))}</div>` : '<p class="review-diff-note">No newly failing or warning policy checks compared with this baseline.</p>'}<details class="review-manifest-diff"><summary>${comparison.manifest_changes.length} rendered manifest field changes</summary><pre class="terminal">${esc(JSON.stringify(comparison.manifest_changes, null, 2))}</pre></details>`;
    }
    async function runReview() {
      latest = null;
      $("#review-export").disabled = true;
      $("#review-yaml").disabled = true;
      $("#review-pin").disabled = true;
      $("#review-run").disabled = true;
      baselineInput.disabled = true;
      $("#review-clear").disabled = true;
      $("#review-run").textContent = "Inspecting bundle…";
      $("#review-results").innerHTML = '<div class="loading">Validating configuration and inspecting rendered objects…</div>';
      notice("");
      try {
        const body = { config: getDraft() };
        if (baselineInput.value.trim()) body.baseline = FoundryUI.parseDraft(baselineInput.value);
        const result = await request("/workbench/api/review", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
        });
        latest = result;
        const current = result.evidence.current, summary = current.summary;
        if (body.baseline) writeStore("pf.review-baseline", JSON.stringify(result.evidence.baseline.config, null, 2));
        const verdict = summary.fail ? "Changes required" : summary.warn ? "Review the warning" : "Selected controls pass";
        $("#review-results").innerHTML = `<div class="review-verdict"><div><span class="review-eyebrow">STATIC POLICY RESULT</span><h2>${esc(verdict)}</h2><p>${esc(current.config.name)} · ${current.objects.length} rendered objects · policy ${esc(result.evidence.policy_version)}</p></div><span class="review-verdict-mark">${icon(summary.fail ? "close" : summary.warn ? "info" : "check")}</span></div><dl class="review-metrics">${metric("Passing", summary.pass, "Explicit field matches")}${metric("Warnings", summary.warn, "Operator review needed")}${metric("Failures", summary.fail, "Controls requiring changes")}${metric("Not applicable", summary.na, "Different workload kind")}</dl><div class="review-filter"><h3>Manifest controls</h3><label for="review-filter">Show<select id="review-filter"><option value="all">All 12 checks</option><option value="findings">Warnings & failures</option><option value="pass">Passing checks</option><option value="na">Not applicable</option></select></label></div><div id="review-checks" class="review-check-grid">${FoundryUI.reviewChecks(current.checks)}</div><section class="panel review-comparison"><div class="panel-head"><div><span class="review-eyebrow">BEFORE → AFTER</span><h2>Release comparison</h2></div><span class="pill">${result.evidence.baseline ? "Baseline captured" : "No baseline"}</span></div>${showComparison(result.evidence.comparison)}</section><section class="panel"><div class="panel-head"><h2>Evidence fingerprint</h2><span class="pill">SHA-256</span></div><div class="panel-body"><code class="review-hash">${esc(result.evidence_sha256)}</code><p class="muted">The export includes both configurations, structured objects, YAML, policy observations, source links and comparison. The hash covers the complete evidence object using sorted, compact UTF-8 JSON.</p><details><summary>Candidate bundle fingerprints</summary>${facts([["Configuration", current.config_sha256], ["Structured manifest", current.manifest_sha256], ["YAML bytes", current.yaml_sha256]])}</details></div></section>`;
        $("#review-filter").onchange = (event) => { $("#review-checks").innerHTML = FoundryUI.reviewChecks(current.checks, event.target.value); };
        $("#review-baseline-state").textContent = result.evidence.baseline ? `${result.evidence.baseline.config.name} · ${result.evidence.baseline.config_sha256.slice(0, 12)}` : "No baseline selected";
        $("#review-export").disabled = false;
        $("#review-yaml").disabled = false;
        $("#review-pin").disabled = false;
        audit("Manifest reviewed", `${current.config.name} · ${summary.warn} warnings · ${summary.fail} failures`);
      } catch (error) {
        $("#review-results").innerHTML = empty("Review could not complete", error instanceof SyntaxError ? "Baseline must be a typed pipeline JSON object. Correct its JSON syntax and retry." : error.message, "/workbench/editor", "Repair candidate");
        notice("No review artifact was produced. Check the candidate and baseline configuration.", true);
      } finally {
        $("#review-run").disabled = false;
        baselineInput.disabled = false;
        $("#review-clear").disabled = false;
        $("#review-run").textContent = "Run release review";
      }
    }
    $("#review-run").onclick = runReview;
    $("#review-pin").onclick = () => {
      if (!latest) return;
      baselineInput.value = JSON.stringify(latest.evidence.current.config, null, 2);
      writeStore("pf.review-baseline", baselineInput.value);
      runReview();
    };
    $("#review-clear").onclick = () => {
      baselineInput.value = "";
      writeStore("pf.review-baseline", "");
      runReview();
    };
    $("#review-export").onclick = () => {
      if (latest) download(`${latest.evidence.current.config.name}-release-review.json`, JSON.stringify(latest, null, 2), "application/json");
    };
    $("#review-yaml").onclick = () => {
      if (latest) download(`${latest.evidence.current.config.name}-reviewed-bundle.yaml`, latest.evidence.current.manifest, "application/yaml");
    };
    baselineInput.addEventListener("input", () => {
      latest = null;
      for (const id of ["#review-export", "#review-yaml", "#review-pin"]) $(id).disabled = true;
      $("#review-baseline-state").textContent = "Baseline edited · rerun to validate";
      $("#review-results").innerHTML = empty("Baseline changed", "Run release review to validate this baseline and rebuild the evidence.");
    });
    runReview();
  }, 0);
  return `<section class="review-hero"><div><span class="review-eyebrow">MANIFEST SECURITY AUDITOR / 01</span><h2>A release deserves<br><em>a closer look.</em></h2><p>Follow the actual fields from your typed draft to the Kubernetes bundle. Catch risky changes before handing the artifact to your operator.</p><div class="review-scope"><span>${icon("shield")} 12 selected controls</span><span>${icon("code")} Structured inspection</span><span>${icon("file")} Verifiable export</span></div></div><div class="review-pipeline"><span>01 <strong>Typed configuration</strong><small>Strict fields · safe paths</small></span><i></i><span>02 <strong>Rendered workload</strong><small>ConfigMap + CronJob</small></span><i></i><span>03 <strong>Release evidence</strong><small>Checks · diff · SHA-256</small></span></div></section><div class="review-boundary">${icon("info")}<span><strong>Static review. Cluster validation not performed.</strong> Selected project controls only. Admission policies, RBAC, quota and runtime still need your cluster’s validation. <a href="https://kubernetes.io/docs/reference/using-api/api-concepts/#dry-run" target="_blank" rel="noopener noreferrer">About server dry run ${icon("external")}</a></span></div><aside id="local-kubernetes-proof" class="review-boundary" aria-label="Local Kubernetes execution proof">${icon("check")}<span><strong>Local Kubernetes execution proof · November 4, 2026.</strong> Guarded create and update ran Jobs at revisions 1 and 2. Revision 3 restored the original configuration and ran a third Job. Each wrote 12 verified NYC taxi fares to SQLite. ${link("https://github.com/9059Rohith/pipefoundry/blob/576db9714cf252999af269b197768b9054ac461a/docs/kubernetes-release-proof.md", "View run evidence")}</span>${sectionArt("rollback-rail")}</aside><div class="review-workspace"><aside class="panel review-controls"><div class="panel-head"><div><span class="review-eyebrow">COMPARE & EXPORT</span><h2>Your review desk</h2></div></div><div class="panel-body"><h3>Candidate</h3><p>The saved draft from your pipeline editor.</p><a class="review-edit" href="/workbench/editor">Open pipeline editor ${icon("arrow")}</a><hr><h3>Baseline</h3><p id="review-baseline-state">No baseline selected</p><button id="review-pin" disabled>${icon("save")} Capture candidate as baseline</button><p class="muted">Capture first, edit your candidate, then return here to compare. Both versions are validated on the server.</p><details><summary>Paste baseline configuration</summary><label class="sr-only" for="review-baseline-json">Baseline pipeline JSON</label><textarea id="review-baseline-json" rows="10" spellcheck="false" placeholder='{"name":"orders-hourly","schedule":"0 * * * *"}'></textarea><small>Typed JSON only · no arbitrary YAML</small><button id="review-clear">Clear baseline</button></details><button class="primary" id="review-run">Run release review</button><hr><h3>Keep the evidence</h3><button id="review-export" disabled>${icon("download")} Export review JSON</button><button id="review-yaml" disabled>${icon("file")} Download reviewed YAML</button><p class="muted">A fingerprint proves content consistency. It is not a signature or a deployment approval.</p></div></aside><div id="review-results" aria-live="polite"></div></div>`;
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
      `${sectionArt("perimeter-mesh")}<div class="result-banner good">✓ Inspected the rendered manifest for ${esc(result.config.name)}</div><ul class="checks">${rules.map(([a, b]) => `<li><span>✓</span><div>${esc(a)}<small class="mono">${esc(b)}</small></div></li>`).join("")}</ul>`,
      "These controls describe the generated configuration, not a live cluster audit.",
    ) +
    panel(
      "Access boundary",
      `<div class="panel-body"><p class="muted">Public pages can inspect public GitHub data and validate configuration. Deployments, release apply, rollback, backfill, private logs and private audit metadata require an operator token. The public agent has a fixed read-only repository scope and persistent allowances. The agent can only read GitHub evidence within a three-step / four-tool-call budget.</p><a class="button" href="/workbench/manifests">Review the manifest →</a></div>`,
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
      `<div class="integration-row"><div class="integration-symbol">⑂</div><div class="integration-name"><h3>GitHub</h3><p>Anonymous public repository, workflows, runs, releases and commits.</p></div>${status("configured")}<a class="button" href="/workbench/repository">Inspect →</a></div><div class="integration-row"><div class="integration-symbol">{ }</div><div class="integration-name"><h3>Pipeline runtime</h3><p>Live server validation and deterministic Kubernetes manifest rendering.</p></div>${status("configured")}<a class="button" href="/workbench/validation">Validate →</a></div><div class="integration-row"><div class="integration-symbol">✧</div><div class="integration-name"><h3>${esc(d.ai_provider === "gemini" ? "Gemini API" : "OpenAI Responses API")}</h3><p>${d.ai_configured ? `Connected: ${esc(d.ai_model)}. A limited public repository demo is available without a token.` : "Server provider key is missing. No AI output is generated without credentials."}</p></div>${status(d.ai_configured ? "configured" : "unavailable")}<a class="button" href="/workbench/agent">Open agent →</a></div><div class="integration-row"><div class="integration-symbol">▧</div><div class="integration-name"><h3>Execution control plane</h3><p>Local and Kubernetes executors. Authenticated API access required.</p></div><span class="pill">Protected</span><a class="button" href="/workbench/plans">Preview →</a></div>`,
      "Live configuration presence; credentials are never disclosed.",
    ) +
    panel(
      "Integration boundaries",
      `<div class="panel-body"><p class="muted">Public GitHub reads never attach a server token, so private repository data stays outside this public surface. GitHub's anonymous rate limit applies. Provider keys belong in server environment configuration; API tokens entered for plans or the agent stay in memory for a single request.</p></div>`,
    )
  );
}
function agentResult(result) {
  const rows = result.trace.map(
    (item) =>
      `<tr><td class="mono">${esc(item.tool)}</td><td>${esc(item.view)}</td><td><time>${esc(fmt(item.observed_at))}</time><span class="secondary">${item.stale ? "Stale cached evidence" : item.cache_status === "live" ? "Live response" : "Validated cache"}</span></td><td>${link(item.source, "GitHub API")}</td></tr>`,
  );
  return `<div class="panel-body">${result.trace.some((item) => item.stale) ? '<div class="notice">GitHub rate limiting prevented a fresh check. This answer uses dated public evidence at the observation times below.</div>' : ""}<div class="agent-response">${FoundryUI.markdown(result.answer)}</div><p class="mono muted">Provider: ${esc(result.provider)} · ${esc(result.model)}</p><div class="evidence-section"><h3>Sources and tool evidence</h3>${table(["Tool", "Action", "Observed", "Source"], rows)}</div><p class="agent-warning">${icon("info")}A repository observation is not a deployment or live cluster check.</p></div>`;
}
async function agent() {
  const state = await request("/workbench/api/integrations");
  setTimeout(() => {
    $("#agent-question").addEventListener("input", () => {
      $("#agent-count").textContent =
        `${$("#agent-question").value.length} / 600`;
    });
    $("#agent-submit").onclick = async () => {
      const button = $("#agent-submit"),
        question = $("#agent-question").value.trim();
      if (question.length < 5 || question.length > 600) {
        notice("Write a question of 5–600 characters.", true);
        return;
      }
      button.disabled = true;
      button.textContent = "Inspecting evidence…";
      let cooling = false;
      notice("");
      $("#agent-output").innerHTML =
        '<div class="loading">Reading public repository evidence…</div>';
      try {
        const result = await request("/workbench/api/demo-agent", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question }),
        });
        audit(
          "Public agent analysis completed",
          `${result.trace.length} read-only tool calls`,
        );
        $("#agent-output").innerHTML = agentResult(result);
      } catch (error) {
        notice(error.message, true);
        $("#agent-output").innerHTML = empty(
          "Analysis not completed",
          error.message,
        );
        if (error.status === 429 || error.status === 503) {
          cooling = true;
          const until = Date.now() + error.retryAfter * 1000;
          const tick = () => {
            const remaining = Math.max(
              0,
              Math.ceil((until - Date.now()) / 1000),
            );
            button.textContent = remaining
              ? `Try again in ${remaining}s`
              : "Ask Foundry";
            button.disabled = remaining > 0;
            if (!remaining) clearInterval(timer);
          };
          const timer = setInterval(tick, 1000);
          tick();
        }
      } finally {
        if (!cooling) {
          button.disabled = false;
          button.innerHTML = `Ask Foundry ${icon("arrow")}`;
        }
      }
    };
  }, 0);
  return `<div class="agent-layout">${panel(
    "Ask Foundry",
    `<div class="panel-body"><p class="agent-meta">${esc(state.public_ai.preferred_model)} / Public demo</p>${!state.public_ai.configured ? '<div class="notice">The provider is not configured. No generated answer is available.</div>' : ""}<div class="form-field"><label for="agent-question">What should the agent investigate?</label><textarea id="agent-question" rows="6" maxlength="600" placeholder="Inspect this repository's default branch and primary language. Include the source and observation time."></textarea><small id="agent-count">0 / 600</small></div><div class="form-field"><label for="agent-repository">Repository (read-only)</label><input id="agent-repository" value="9059Rohith/pipefoundry" readonly></div><button class="primary agent-submit" id="agent-submit" ${!state.public_ai.configured ? "disabled" : ""}>Ask Foundry ${icon("arrow")}</button><div class="inspector-result">${facts(
      [
        ["Your allowance", "3 requests / 10 minutes"],
        ["Shared allowance", "2 / minute · 30 / day"],
        ["Permissions", "Read-only public evidence"],
      ],
    )}<p class="note">No sign-in required. Every accepted attempt uses an allowance. Dated cached evidence may be used. No deployment permissions or paid fallback.</p></div></div>`,
    "Real Gemini analysis, with an inspectable source trail.",
  )}${panel("Analysis", `${sectionArt("citation-lattice")}<div id="agent-output">${empty("Evidence comes first", "Ask a question to see a real model answer and the source records it inspected.")}</div>`, "Answers appear only after an actual provider request.")}</div><p class="agent-warning">${icon("shield")}Read-only tools. Fixed repository scope. Free-tier and shared demo limits apply.</p>`;
}
function renderIcons(root) {
  root.querySelectorAll("[data-icon]").forEach((element) => {
    if (!element.dataset.iconRendered) {
      element.innerHTML = icon(element.dataset.icon);
      element.dataset.iconRendered = "true";
    }
  });
}
function decorateSymbols(root) {
  const symbols = {
    "↗": "external",
    "→": "arrow",
    "↓": "download",
    "✓": "check",
    "×": "close",
    "＋": "plus",
    "✧": "agent",
    "⑂": "workflow",
    "▧": "box",
    "⌘": "terminal",
  };
  root
    .querySelectorAll(
      "button,a,.flow-arrow,.activity-icon,.integration-symbol,.checks li>span",
    )
    .forEach((element) => {
      [...element.childNodes]
        .filter(
          (node) =>
            node.nodeType === Node.TEXT_NODE &&
            /[↗→↓✓×＋✧⑂▧⌘]/.test(node.textContent),
        )
        .forEach((node) => {
          const fragment = document.createDocumentFragment();
          for (const piece of node.textContent.split(/([↗→↓✓×＋✧⑂▧⌘])/)) {
            if (symbols[piece]) {
              const holder = document.createElement("span");
              holder.innerHTML = icon(symbols[piece]);
              fragment.append(holder.firstElementChild);
            } else fragment.append(document.createTextNode(piece));
          }
          node.replaceWith(fragment);
        });
    });
}
function initializeWorkbench() {
  renderIcons(document);
  const current = document.querySelector(
    `[data-nav="${page === "run" ? "runs" : page}"]`,
  );
  current?.setAttribute("aria-current", "page");
  const steps = [
    ["editor", "Configure"],
    ["validation", "Validate"],
    ["review", "Review"],
    ["manifests", "Manifests"],
    ["plans", "Plan"],
  ];
  if (steps.some(([name]) => name === page))
    $("#journey").innerHTML =
      `<nav class="journey" aria-label="Pipeline build journey">${steps.map(([name, label], index) => `<a href="/workbench/${name}" class="${name === page ? "current" : ""}" ${name === page ? 'aria-current="step"' : ""}><span class="step-number">0${index + 1}</span>${label}</a>`).join("")}</nav>`;
  const menu = $("#menu-toggle"),
    sidebar = $("#sidebar"),
    backdrop = $("#nav-backdrop");
  function closeMenu() {
    sidebar.classList.remove("is-open");
    backdrop.hidden = true;
    menu.setAttribute("aria-expanded", "false");
    document.querySelector(".app").inert = false;
    document.body.classList.remove("nav-open");
  }
  menu.onclick = () => {
    const open = !sidebar.classList.contains("is-open");
    if (!open) closeMenu();
    else {
      sidebar.classList.add("is-open");
      backdrop.hidden = false;
      menu.setAttribute("aria-expanded", "true");
      document.querySelector(".app").inert = true;
      document.body.classList.add("nav-open");
      current?.focus();
    }
  };
  backdrop.onclick = () => {
    closeMenu();
    menu.focus();
  };
  $("#nav-close").onclick = () => {
    closeMenu();
    menu.focus();
  };
  window
    .matchMedia("(min-width: 761px)")
    .addEventListener("change", (event) => {
      if (event.matches) closeMenu();
    });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && sidebar.classList.contains("is-open")) {
      closeMenu();
      menu.focus();
    }
    if (event.key === "Tab" && sidebar.classList.contains("is-open")) {
      const targets = [...sidebar.querySelectorAll("a,button")];
      if (event.shiftKey && document.activeElement === targets[0]) {
        event.preventDefault();
        targets.at(-1).focus();
      } else if (!event.shiftKey && document.activeElement === targets.at(-1)) {
        event.preventDefault();
        targets[0].focus();
      }
    }
  });
  document.querySelectorAll("[data-close-dialog]").forEach((button) => {
    button.onclick = () => button.closest("dialog").close();
  });
  document.querySelectorAll("dialog").forEach((dialog) => {
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) {
        const rect = dialog.getBoundingClientRect();
        if (
          event.clientX < rect.left ||
          event.clientX > rect.right ||
          event.clientY < rect.top ||
          event.clientY > rect.bottom
        )
          dialog.close();
      }
    });
  });
  const palette = $("#command-palette"),
    search = $("#command-search");
  let filtered = [],
    selected = 0;
  function commands() {
    const values = [...document.querySelectorAll("[data-nav]")].map(
      (anchor) => ({
        label: anchor.textContent.trim(),
        detail: descriptions[anchor.dataset.nav] || "Open workspace page",
        href: anchor.getAttribute("href"),
        icon: anchor.querySelector("[data-icon]")?.dataset.icon || "file",
      }),
    );
    if (page === "editor")
      for (const [selector, label, detail] of [
        ["#format-json", "Format JSON", "Format the current editor text"],
        ["#save-draft", "Save draft", "Save configuration for this session"],
        [
          "#editor-validate",
          "Validate configuration",
          "Save and run the real runtime schema",
        ],
      ])
        if ($(selector))
          values.unshift({ label, detail, selector, icon: "code" });
    return values;
  }
  function drawCommands() {
    filtered = FoundryUI.filterCommands(commands(), search.value);
    selected = 0;
    $("#command-results").innerHTML = filtered.length
      ? filtered
          .map(
            (command, index) =>
              `<button class="command-option ${index === 0 ? "active" : ""}" role="option" aria-selected="${index === 0}" id="command-option-${index}" data-command="${index}" tabindex="-1">${icon(command.icon)}<span>${esc(command.label)}<small>${esc(command.detail)}</small></span></button>`,
          )
          .join("")
      : empty(
          "No matching command",
          "Try a page name such as editor, executions or manifests.",
        );
    search.setAttribute(
      "aria-activedescendant",
      filtered.length ? "command-option-0" : "",
    );
  }
  function executeCommand(index) {
    const command = filtered[index];
    if (!command) return;
    palette.close();
    if (command.selector) $(command.selector)?.click();
    else if (
      command.href !== location.pathname &&
      preserveJourneyDraft(command.href)
    )
      location.href = command.href;
  }
  $("#command-trigger").onclick = () => {
    closeMenu();
    search.value = "";
    drawCommands();
    palette.showModal();
    search.focus();
  };
  search.addEventListener("input", drawCommands);
  search.addEventListener("keydown", (event) => {
    if (["ArrowDown", "ArrowUp"].includes(event.key) && filtered.length) {
      event.preventDefault();
      selected =
        (selected + (event.key === "ArrowDown" ? 1 : -1) + filtered.length) %
        filtered.length;
      document.querySelectorAll("[data-command]").forEach((button, index) => {
        button.classList.toggle("active", index === selected);
        button.setAttribute("aria-selected", String(index === selected));
      });
      search.setAttribute(
        "aria-activedescendant",
        `command-option-${selected}`,
      );
      $("#command-option-" + selected)?.scrollIntoView({ block: "nearest" });
    } else if (event.key === "Enter") {
      event.preventDefault();
      executeCommand(selected);
    }
  });
  $("#command-results").addEventListener("click", (event) => {
    const button = event.target.closest("[data-command]");
    if (button) executeCommand(Number(button.dataset.command));
  });
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      if (palette.open) palette.close();
      else $("#command-trigger").click();
    }
    if (
      (event.ctrlKey || event.metaKey) &&
      event.key.toLowerCase() === "s" &&
      page === "editor"
    ) {
      event.preventDefault();
      $("#save-draft")?.click();
    }
    if (
      (event.ctrlKey || event.metaKey) &&
      event.shiftKey &&
      event.key === "Enter" &&
      page === "editor"
    ) {
      event.preventDefault();
      $("#editor-validate")?.click();
    }
  });
  document.addEventListener("input", (event) => {
    if (!event.target.matches("[data-table-filter]")) return;
    const container = event.target.closest(".data-table"),
      query = event.target.value.toLowerCase();
    let visible = 0;
    const rows = [...container.querySelectorAll("tbody tr")];
    rows.forEach((row) => {
      const show = row.textContent.toLowerCase().includes(query);
      row.hidden = !show;
      if (show) visible++;
    });
    container.querySelector("[data-table-count]").textContent =
      `${visible} of ${rows.length} records`;
    container.querySelector("[data-table-empty]").hidden = visible > 0;
  });
  document.addEventListener("click", (event) => {
    const journeyLink = event.target.closest("a[href]");
    if (
      journeyLink &&
      !preserveJourneyDraft(journeyLink.getAttribute("href"))
    ) {
      event.preventDefault();
      return;
    }
    const row = event.target.closest("tr[data-inspect-row]");
    if (
      !row ||
      event.target.closest("a") ||
      (event.target.closest("button") &&
        !event.target.closest("[data-inspect-record]")) ||
      (!event.target.closest("[data-inspect-record]") &&
        window.getSelection()?.toString())
    )
      return;
    const tableElement = row.closest("table"),
      headers = [...tableElement.querySelectorAll("thead th")]
        .slice(0, -1)
        .map((cell) => cell.textContent.trim());
    const cells = [...row.cells]
      .slice(0, -1)
      .map((cell) => cell.textContent.trim());
    const source = row.querySelector("a");
    let target = null;
    if (source) {
      try {
        const url = new URL(source.href);
        if (
          url.origin === location.origin &&
          url.pathname.startsWith("/workbench/")
        )
          target = url.pathname + url.search;
        else target = FoundryUI.safeURL(url.href);
      } catch {}
    }
    $("#record-title").textContent = cells[0].slice(0, 90) || "Record details";
    $("#record-content").innerHTML =
      facts(headers.map((header, index) => [header, cells[index]])) +
      (target
        ? `<p><a class="button" href="${esc(target)}" ${target.startsWith("https:") ? 'target="_blank" rel="noopener noreferrer"' : ""}>Open record ${icon("external")}</a></p>`
        : "");
    $("#record-dialog").showModal();
  });
}
function preserveJourneyDraft(href) {
  if (
    page !== "editor" ||
    ![
      "/workbench/validation",
      "/workbench/manifests",
      "/workbench/review",
      "/workbench/plans",
    ].includes(href)
  )
    return true;
  try {
    const config = FoundryUI.parseDraft($("#config-editor").value);
    writeStore("pf.draft", JSON.stringify(config, null, 2));
    try {
      sessionStorage.removeItem("pf.pending-draft");
    } catch {}
    return true;
  } catch {
    notice(
      "Correct the JSON syntax before continuing the build journey.",
      true,
    );
    return false;
  }
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
  review,
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
    renderIcons($("#content"));
    decorateSymbols($("#content"));
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
initializeWorkbench();
load();
