"""Small server-rendered read-only console; all dynamic fields are escaped."""

from datetime import UTC, datetime
from html import escape

REPOSITORY = "https://github.com/9059Rohith/pipefoundry"
CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; "
    "frame-ancestors 'none'; form-action 'none'"
)
STYLE = """
:root{color-scheme:light;--ink:#152332;--muted:#607187;--line:#dce4eb;--ok:#087f69}
*{box-sizing:border-box}body{margin:0;background:#f3f6fa;color:var(--ink);
font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
.shell{width:min(1346px,calc(100% - 32px));margin:8px auto;background:#fff;
min-height:calc(100vh - 16px);display:flex;flex-direction:column}
header{padding:17px 34px;border-bottom:1px solid var(--line);display:flex;
align-items:center;justify-content:space-between;gap:24px}
.brand{font-size:30px;font-weight:750;letter-spacing:-1px}
nav{display:flex;gap:34px;flex-wrap:wrap}a{color:#286ba2;text-underline-offset:3px}
nav a{font-size:18px;color:var(--muted);text-decoration:none}
a:hover{text-decoration:underline}a:focus-visible{outline:2px solid var(--ok);outline-offset:5px}
main{padding:38px 34px 20px;flex:1}.title{display:flex;align-items:center;
justify-content:space-between;gap:24px}h1{font-size:48px;line-height:1.2;
letter-spacing:-1.5px;margin:0;font-weight:750}.refresh{font-size:18px;white-space:nowrap}
.subtitle{font-size:20px;line-height:1.4;color:var(--muted);margin:12px 0 0}
.state{font-size:30px;font-weight:650;margin:24px 0 0}.divider{color:var(--muted)}
.ok{color:var(--ok)}.bad{color:#a93235}.neutral{color:var(--muted)}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);margin:24px 0 0}
.metrics div{padding:9px 30px;border-right:1px solid var(--line)}
.metrics div:last-child{border:0}.metrics dt{font-size:18px;font-weight:600;color:var(--muted)}
.metrics dd{font-size:28px;font-weight:650;line-height:1.2;margin:10px 0 0}
h2{font-size:32px;line-height:1.2;letter-spacing:-.8px;margin:32px 0 16px}
.scroll{overflow:auto}table{border-collapse:collapse;width:100%;text-align:left;min-width:660px}
th{font-size:18px;font-weight:650;background:#f1f5f9;color:var(--muted);padding:12px 18px}
td{font-size:18px;padding:10px 18px;border-bottom:1px solid var(--line)}
td:nth-child(1){width:21%}td:nth-child(2){width:18%}td:nth-child(3){width:23%}
code,time{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:17px}
.details{margin:40px 0 0}.details div{display:grid;grid-template-columns:236px 1fr;
padding:8px 12px;border-bottom:1px solid var(--line)}
.details div:first-child{border-top:1px solid var(--line)}
.details dt{color:var(--muted);font-size:18px}.details dd{margin:0;min-width:0}
.details code{overflow-wrap:anywhere;line-height:1.45}
footer{border-top:1px solid var(--line);padding:16px 34px;display:flex;
justify-content:space-between;gap:24px;color:var(--muted);font-size:14px;line-height:1.4}
footer time{font-size:13px}.pending{padding:40px 0;max-width:640px;font-size:20px;line-height:1.6}
@media(max-width:700px){.shell{width:100%;margin:0;min-height:100vh}header{display:block;padding:22px}
.brand{font-size:26px}nav{gap:16px;margin-top:14px}nav a{font-size:14px}main{padding:28px 22px}
.title{align-items:flex-start;flex-wrap:wrap;gap:14px}h1{font-size:34px}.refresh{font-size:15px}
.subtitle{font-size:16px}.state{font-size:22px}.metrics{grid-template-columns:repeat(2,1fr)}
.metrics div{padding:16px 10px;border-bottom:1px solid var(--line)}
.metrics div:nth-child(even){border-right:0}
.metrics div:last-child{border-bottom:1px solid var(--line)}
.metrics dt{font-size:14px}.metrics dd{font-size:25px}h2{font-size:26px}
.details div{grid-template-columns:140px 1fr;padding:10px 0}.details dt{font-size:14px}
.details code{font-size:13px}footer{display:block;padding:20px 22px}
footer time{display:block;margin-top:12px}}
"""


def _e(value):
    return escape(str(value), quote=True)


def _when(value):
    try:
        return datetime.fromisoformat(str(value)).astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    except ValueError:
        return _e(value)


def _semantic(value):
    return (
        "ok" if value == "succeeded" else "bad" if value in {"failed", "interrupted"} else "neutral"
    )


def render_console(receipt):
    pending = receipt is None
    head_refresh = '<meta http-equiv="refresh" content="5">' if pending else ""
    if pending:
        content = '<p class="pending" role="status">Waiting for verified PostgreSQL receipts. '
        content += "This page refreshes every five seconds while initialization runs.</p>"
        observed = "Initialization pending"
    else:
        pipeline = receipt["pipeline"]
        metrics = [
            ("Rows per run", receipt["workload"]["rows"]),
            ("Backfill partitions", len(receipt["backfill"])),
            ("Current revision", pipeline["revision"]),
            ("Quality failures", receipt["workload"]["invalid_rows"]),
        ]
        metric_html = "".join(
            f"<div><dt>{_e(label)}</dt><dd>{_e(value)}</dd></div>" for label, value in metrics
        )
        rows = "".join(
            f"<tr><td>{_e(event['action'])}</td><td><code>{_e(event['revision'])}</code></td>"
            f'<td class="{_semantic(event["outcome"])}">{_e(event["outcome"])}</td>'
            f"<td><time>{_when(event['created'])}</time></td></tr>"
            for event in receipt["events"]
        )
        details = [
            ("Declared schedule", pipeline["schedule"]),
            ("Output", "PostgreSQL"),
            ("Artifact storage", receipt["artifact"]["storage"]),
            ("Artifact SHA-256", receipt["artifact"]["sha256"]),
        ]
        detail_html = "".join(
            f"<div><dt>{_e(label)}</dt><dd><code>{_e(value)}</code></dd></div>"
            for label, value in details
        )
        content = (
            f'<p class="state">{_e(pipeline["name"])} <span class="divider">/</span> '
            f'<span class="{_semantic(pipeline["status"])}">{_e(pipeline["status"])}</span></p>'
            f'<dl class="metrics">{metric_html}</dl><h2>Revision history</h2>'
            '<div class="scroll" role="region" aria-label="Execution audit" tabindex="0">'
            "<table><thead><tr><th>Action</th><th>Revision</th><th>Result</th>"
            f"<th>Recorded UTC</th></tr></thead><tbody>{rows}</tbody></table></div>"
            f'<dl class="details">{detail_html}</dl>'
        )
        observed = "Observed " + _when(receipt["observed_at"])
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">{head_refresh}
<title>PipeFoundry — Pipeline execution</title><style>{STYLE}</style></head>
<body><div class="shell"><header><span class="brand">PipeFoundry</span>
<nav aria-label="Resources"><a href="/demo">JSON receipts</a>
<a href="{REPOSITORY}/blob/main/README.md">Docs</a><a href="/health/ready">Health</a>
<a href="{REPOSITORY}">GitHub</a></nav></header><main>
<div class="title"><h1>Pipeline execution</h1><a class="refresh" href="/">Refresh receipts</a></div>
<p class="subtitle">Synthetic fixtures executed by a real Python worker and PostgreSQL.</p>
{content}</main><footer><div>Execution is on demand. Cron schedules are versioned artifacts,
not activated by this host.<br>Operations require private authentication.</div>
<time>{observed}</time></footer></div></body></html>'''
