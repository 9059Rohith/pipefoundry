# Public GitHub capture provenance

`src/pipefoundry/github_repository_cache.json` contains official anonymous responses
from `https://api.github.com/repos/9059Rohith/pipefoundry`, captured serially on
2026-11-05 from **07:09:04.669772 to 07:09:27.303880 UTC**. No credentials, private
resources, inferred records, or replacement execution outcomes were used.

The 31 successful HTTP 200 responses contain:

| View | Captured records |
| --- | ---: |
| Repository metadata | 1 |
| Workflow definitions | 2 |
| Workflow runs | 26 of 26 reported total |
| Releases | 0 |
| Commits | First 30 returned |
| Run-job responses | All 26 returned run IDs, 52 jobs total |

All 26 runs reported `failure`; these outcomes are preserved as returned. An empty
release list is the actual API response. No additional pages were requested. Each
job endpoint requested up to 50 jobs and its returned counts are retained.

The top level is repository evidence; `related` maps lowercased repository plus
the exact fixed request suffix to each other response. Each evidence object has
`data`, `source`, `observed_at`, `cache_seconds: 600`, the provider `etag`, and
`content_sha256`. The content digest covers UTF-8 bytes from Python
`json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`.
These capture times establish provenance; application freshness/stale policy
determines whether an observation may still be served.

The 645,902-byte bundle SHA-256 is
`1cc4964b9591fb4125b9cc9def5369e78e961442ce0ff83c7a9ffdd9d13e52db`.
The top-level repository content SHA-256 is
`60590996d552b4f03919b0559c5cdf83cf15bae57c0f81a6e6b8fc29d131a505`.
The capture receipt records every response time, status, and provider quota header:
[`github-source-capture.json`](../evidence/github-source-capture.json).

## Reproduce or verify

```sh
python scripts/capture_github_evidence.py
python scripts/capture_github_evidence.py --verify
```

The script uses the fixed public HTTPS origin, serial anonymous requests, at most
30 run-job requests, and a 4 MiB output limit. It stops on HTTP 403/429, zero
remaining quota, or transport errors without retrying around provider limits.
Successful observations remain distinct from errors recorded in the capture
receipt. `--verify` is offline and checks all 31 sources, hashes, observation times,
and cache durations without consuming quota. The actual capture began with 44
remaining requests after its first response and ended with 14; reported reset
was Unix time `1793864686`. Follow GitHub's [rate-limit guidance](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)
and [request best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api)
before refreshing another capture.
