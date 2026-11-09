(function (root) {
  "use strict";
  const escape = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  function safeURL(value) {
    try {
      const url = new URL(value);
      return url.protocol === "https:" &&
        !url.username &&
        !url.password &&
        !url.port &&
        ["github.com", "api.github.com", "kubernetes.io"].includes(url.hostname)
        ? url.href
        : null;
    } catch {
      return null;
    }
  }
  function retryAfterSeconds(header, now = Date.now()) {
    const value = String(header ?? "").trim();
    const seconds = Number(value);
    if (/^\d+$/.test(value) && Number.isFinite(seconds) && seconds > 0)
      return seconds;
    if (/^[A-Za-z]{3}, \d{2} [A-Za-z]{3} \d{4} \d{2}:\d{2}:\d{2} GMT$/.test(value)) {
      const deadline = Date.parse(value);
      if (Number.isFinite(deadline))
        return Math.max(1, Math.ceil((deadline - now) / 1000));
    }
    return 60;
  }
  function inline(value) {
    const expression =
      /`([^`\n]+)`|\*\*([^*\n]+)\*\*|\[([^\]\n]+)\]\(([^)\s]+)\)|(https:\/\/[^\s<>]+)/g;
    let result = "",
      end = 0;
    for (const match of value.matchAll(expression)) {
      result += escape(value.slice(end, match.index));
      if (match[1]) result += "<code>" + escape(match[1]) + "</code>";
      else if (match[2]) result += "<strong>" + escape(match[2]) + "</strong>";
      else {
        const destination = safeURL(match[4] || match[5]);
        const label = match[3] || match[5];
        result += destination
          ? '<a target="_blank" rel="noopener noreferrer" href="' +
            escape(destination) +
            '">' +
            escape(label) +
            "</a>"
          : escape(label);
      }
      end = match.index + match[0].length;
    }
    return result + escape(value.slice(end));
  }
  function markdown(value) {
    const lines = String(value ?? "")
      .slice(0, 24000)
      .split("\n");
    let output = "",
      list = false,
      paragraph = [],
      fenced = false,
      code = [];
    const flush = () => {
      if (paragraph.length)
        output += "<p>" + inline(paragraph.join(" ")) + "</p>";
      paragraph = [];
    };
    const closeList = () => {
      if (list) output += "</ul>";
      list = false;
    };
    for (const line of lines) {
      if (line.trim().startsWith("```")) {
        flush();
        closeList();
        if (fenced) {
          output += "<pre><code>" + escape(code.join("\n")) + "</code></pre>";
          code = [];
        }
        fenced = !fenced;
        continue;
      }
      if (fenced) {
        code.push(line);
        continue;
      }
      const heading = line.match(/^#{1,3}\s+(.+)$/);
      const item = line.match(/^\s*(?:[-*]|\d+\.)\s+(.+)$/);
      if (heading) {
        flush();
        closeList();
        output += "<h3>" + inline(heading[1]) + "</h3>";
      } else if (item) {
        flush();
        if (!list) output += "<ul>";
        list = true;
        output += "<li>" + inline(item[1]) + "</li>";
      } else if (!line.trim()) {
        flush();
        closeList();
      } else {
        closeList();
        paragraph.push(line);
      }
    }
    flush();
    closeList();
    if (code.length)
      output += "<pre><code>" + escape(code.join("\n")) + "</code></pre>";
    return output;
  }
  function highlightJSON(value) {
    const expression =
      /"(?:\\.|[^"\\])*"(?=\s*:)|"(?:\\.|[^"\\])*"|\b(?:true|false|null)\b|-?\b\d+(?:\.\d+)?\b/g;
    let result = "",
      end = 0;
    for (const match of value.matchAll(expression)) {
      result += escape(value.slice(end, match.index));
      const kind = value.slice(match.index + match[0].length).match(/^\s*:/)
        ? "key"
        : match[0].startsWith('"')
          ? "string"
          : "value";
      result +=
        '<span class="syntax-' + kind + '">' + escape(match[0]) + "</span>";
      end = match.index + match[0].length;
    }
    return result + escape(value.slice(end));
  }
  function filterCommands(commands, query) {
    const words = query.toLowerCase().trim().split(/\s+/).filter(Boolean);
    return commands.filter((command) =>
      words.every((word) =>
        (command.label + " " + command.detail).toLowerCase().includes(word),
      ),
    );
  }
  function parseDraft(raw) {
    const value = JSON.parse(raw);
    if (!value || Array.isArray(value) || typeof value !== "object") {
      throw new TypeError("Pipeline configuration must be a JSON object.");
    }
    return value;
  }
  function reviewChecks(checks, filter = "all") {
    const selected = checks.filter((check) => filter === "all" ||
      (filter === "findings" ? ["warn", "fail"].includes(check.status) : check.status === filter));
    if (!selected.length) return '<div class="review-empty">No matching checks. Choose another filter to see the complete review.</div>';
    return selected.map((check) => {
      const state = ["pass", "warn", "fail", "na"].includes(check.status) ? check.status : "fail";
      const source = safeURL(check.source);
      return `<article class="review-check ${state}"><div class="review-check-heading"><span class="review-state ${state}">${state === "na" ? "N/A" : state.toUpperCase()}</span><h3>${escape(check.title)}</h3></div><p>${escape(check.explanation)}</p>${state === "warn" || state === "fail" ? `<div class="review-remedy">${escape(check.remediation)}</div>` : ""}<details><summary>Inspect ${check.evidence.length} field observation${check.evidence.length === 1 ? "" : "s"}</summary>${check.evidence.map((entry) => `<div class="review-observation"><code>${escape(entry.path)}</code><span class="review-state ${entry.passed ? "pass" : "warn"}">${entry.passed ? "MATCH" : "REVIEW"}</span><pre>${escape(JSON.stringify(entry.value, null, 2))}</pre></div>`).join("")}${!check.evidence.length ? '<p>No applicable resource in this bundle.</p>' : ""}</details>${source ? `<a class="review-source" href="${escape(source)}" target="_blank" rel="noopener noreferrer">Kubernetes documentation ↗</a>` : ""}</article>`;
    }).join("");
  }
  function rehearsalReport(result) {
    const e = result.evidence;
    const grid = (headers, rows) => `<div class="table-wrap"><table><thead><tr>${headers.map((h) => `<th scope="col">${escape(h)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((value) => `<td>${escape(value)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
    const metrics = [["Input rows", e.summary.input_rows], ["Output rows", e.summary.output_rows], ["Replaced rows", e.summary.replaced_rows], ["Currency normalizations", e.summary.currency_normalizations]];
    return `<div class="result-banner ${e.accepted ? "good" : ""}"><strong>${e.accepted ? "Sample accepted" : "Batch rejected"}</strong> · ${e.accepted ? "Runtime normalization completed in memory" : `${escape(e.invalid_rows)} invalid rows; no partial output`}</div><p class="note">${escape(e.scope)}</p><dl class="review-metrics">${metrics.map(([label, count]) => `<div class="metric"><dt>${escape(label)}</dt><dd>${escape(count)}</dd></div>`).join("")}</dl>${e.issues.length ? `<h3>Repair these sample fields</h3>${grid(["Input row", "Field", "Required value"], e.issues.map((issue) => [issue.row, issue.field, issue.rule]))}${e.issues_truncated ? "<p>Showing the first 100 issues. Repair these fields and rerun for remaining diagnostics.</p>" : ""}` : ""}${e.duplicates.length ? `<h3>Last observation wins</h3><p>IDs are unique within a partition. Later observations replace earlier amounts and currencies.</p>${grid(["ID", "Input rows", "Winning row"], e.duplicates.map((d) => [d.id, d.source_rows.join(", "), d.winner_row]))}` : ""}${e.currency_totals.length ? `<h3>Totals by currency</h3><p>Integer cents after duplicate replacement. Different currencies are never added together.</p>${grid(["Currency", "Rows", "Amount (cents)"], e.currency_totals.map((t) => [t.currency, t.rows, t.amount_cents]))}` : ""}<h3>Normalized output preview</h3>${e.normalized_rows.length ? grid(["Partition (UTC date)", "ID", "Amount (cents)", "Currency"], e.normalized_rows.map((row) => [row.partition_date, row.id, row.amount_cents, row.currency])) : "<p>No output rows. The worker rejects the whole batch if any record fails validation.</p>"}<details><summary>Evidence fingerprint (SHA-256)</summary><p class="mono wrap">${escape(result.evidence_sha256)}</p><p>The export contains validated configuration, rendered YAML and the sample fingerprint. Rejected input values are excluded. This is content evidence, not an execution receipt.</p></details>`;
  }
  const paths = {
    inspect:
      "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
    home: "M3 10 12 3l9 7v11h-6v-7H9v7H3z",
    repo: "M3 6h7l2 2h9v12H3z M3 6V4h7l2 2",
    workflow: "M12 8v4M5 16v-4h14v4M9 3h6v5H9zM2 16h6v5H2zM16 16h6v5h-6z",
    play: "M9 7l8 5-8 5z M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
    tag: "M3 3h8l10 10-8 8L3 11zM7 7h.01",
    history: "M3 4v5h5M3 9a9 9 0 1 1 0 6M12 7v5l3 2",
    code: "m8 6-6 6 6 6m8-12 6 6-6 6m-3-15-2 18",
    check: "m7 12 3 3 7-7M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
    file: "M5 2h9l5 5v15H5zM14 2v6h5M8 13h8M8 17h6",
    box: "m3 7 9-5 9 5v10l-9 5-9-5zM3 7l9 5 9-5M12 12v10",
    agent: "M4 6h16v14H4zM12 2v4M8 11h.01M16 11h.01M8 16h8M1 10v6M23 10v6",
    shield: "M12 2 3 6v6c0 5 9 10 9 10s9-5 9-10V6zM8 12l3 3 5-6",
    list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
    link: "m10 13 4-4M8 16l-2 2a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0M16 8l2-2a4 4 0 0 1 6 6l-5 5a4 4 0 0 1-6 0",
    search: "M20 20l-5-5M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0",
    external: "M14 3h7v7M21 3 10 14M10 3H3v18h18v-7",
    arrow: "M4 12h16m-6-6 6 6-6 6",
    download: "M12 2v13m-5-5 5 5 5-5M3 16v6h18v-6",
    copy: "M9 9h13v13H9zM15 5V2H2v13h3",
    save: "M3 3h15l3 3v15H3zM7 3v6h10V3M7 21v-8h10v8",
    menu: "M3 5h18M3 12h18M3 19h18",
    close: "m5 5 14 14M19 5 5 19",
    info: "M12 11v6M12 7h.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
    terminal: "m4 6 6 6-6 6M13 18h7",
    pipe: "M3 14h5v7H3zM15 2h6v9h-6zM8 17h4V6h3",
    plus: "M12 4v16M4 12h16",
  };
  function icon(name) {
    return (
      '<svg class="icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="' +
      (paths[name] || paths.file) +
      '"/></svg>'
    );
  }
  const api = {
    parseDraft,
    reviewChecks,
    rehearsalReport,
    escape,
    safeURL,
    retryAfterSeconds,
    markdown,
    highlightJSON,
    filterCommands,
    icon,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.FoundryUI = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
