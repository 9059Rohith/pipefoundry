# Shared GitHub cache: native PostgreSQL proof

The [reproducible harness](../scripts/verify_github_shared_cache.py) passed on native PostgreSQL 18.2 with an isolated, disposable SCRAM-authenticated cluster. It uses the actual 31-response [captured bundle](../src/pipefoundry/github_repository_cache.json) through `read_cached_evidence`; it makes **zero network GitHub requests**. Every persisted response is checked independently against its original public source URL and canonical content SHA-256. The bundle SHA-256 for this run is `1cc4964b9591fb4125b9cc9def5369e78e961442ce0ff83c7a9ffdd9d13e52db`.

The [result artifact](../evidence/github-shared-cache.json) records exact native SQL observations and all 31 provenance pairs:

| Check | Observed result |
| --- | --- |
| Seed through separate cache/store instances | 31 rows, 31 unique request keys, no upstream calls |
| Eight identical concurrent reads through eight separate instances | One recorded-response adapter call, one active refresh owner, seven remaining budget tokens; seven other reads served retained evidence |
| Controlled HTTP 429 with `Retry-After: 120` | Shared cooldown; all 31 other reads served retained evidence with zero extra upstream calls |
| Actual PostgreSQL stop/start, then new instances | All 31 retained responses and the cooldown survived |
| Lease expiry after a virtual 31-second advance | New owner acquired; old owner could not write evidence or release the new owner's lease |
| Late controlled quota result from expired owner | Shared cooldown extended without releasing the active owner's lease; successful new owner retained that cooldown |
| Independent persisted payload audit | 31 original source URLs and content hashes matched |

The 31 responses comprise repository metadata, four portfolio collections and 26 workflow-job collections. They remain source observations from the original capture, including real empty collections and real workflow failures. The controlled HTTP 200 adapter replays one unchanged recorded body; it is not a fresh provider observation. The 429 is a deliberately controlled failure response. Freshness and lease expiry use a virtual clock anchored to the latest capture plus ten seconds, then advanced by 601, 601, 121 and 31 seconds. Database transactions, concurrent execution and the PostgreSQL restart are real. This verifies distinct clients sharing a native database, not distributed multi-host throughput or a live GitHub outage.

Reproduce from the repository root with its existing environment and native PostgreSQL binaries:

```powershell
.venv/Scripts/python.exe scripts/verify_github_shared_cache.py --postgres-bin 'C:/Program Files/PostgreSQL/18/bin'
.venv/Scripts/python.exe -m ruff check scripts/verify_github_shared_cache.py
```

The harness chooses an unused loopback port and creates its own cluster beneath `.runtime`. It stops only that cluster and removes the temporary directory, including credentials and database logs. DSNs and passwords are absent from the published evidence. It neither uses nor alters hosted databases, production cooldowns or provider quota.
