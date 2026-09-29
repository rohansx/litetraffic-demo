# LiteTraffic demo: catching a tenant leak in CI

A tiny multi-tenant records API, a [LiteTraffic](https://litetraffic.com) scenario that checks tenant isolation, and a GitHub Actions job that runs it on every push and pull request.

The story is [PR #1](https://github.com/rohansx/litetraffic-demo/pull/1): it "adds record sharing", and in doing so lets tenant A read tenant B's records. Every response is a `200`, the unit of work looks fine, and the only trace in the server is a swallowed exception:

```
ERROR permission check failed open: KeyError('shared_with')
```

LiteTraffic fails the check on `cross_tenant_blocked`, writes the table and journey funnel into the job summary, and keeps the whole run (evidence, server logs, resource use) as a build artifact. A follow-up commit on the same PR fixes the check and the build goes green.

## What is here

| Path | What it is |
|---|---|
| `app.py` | The API (Python stdlib only). Records belong to a tenant; `can_read` decides who may read them. |
| `Dockerfile`, `docker-compose.yml` | Runs the API as `litetraffic-demo-api` on port 8080 and logs every request. |
| `scenarios/tenant-isolation/` | The LiteTraffic scenario: each journey reads its own record (`read_own`), then probes the other tenant's (`probed_other_tenant`). |
| `.github/workflows/litetraffic.yml` | The CI job, following LiteTraffic's [CI recipe](https://github.com/rohansx/litetraffic/blob/main/docs/ci.md). |

The scenario creates its own records through `POST /fixtures` (scoped to the run by the `X-LiteTraffic-Run` header) and deletes them afterwards, so it never touches real data.

## Assertions

| Check | Holds when |
|---|---|
| `tenant_a_reads_own` | tenant A reads its own record: `200` with the right value |
| `tenant_b_reads_own` | same for tenant B |
| `cross_tenant_blocked` | tenant A asking for tenant B's record gets `403` |
| `tenant_fixture_intact` | both tenants' records still exist after the run |

## Run it locally

Needs Docker, Python 3.11+ and [k6 v2.2.0](https://github.com/grafana/k6/releases/tag/v2.2.0).

```sh
python -m pip install "litetraffic @ git+https://github.com/rohansx/litetraffic@eb86c43fe9c66162235238ed149e26cbd9626926"
docker compose up -d --wait
litetraffic verify scenarios/tenant-isolation --target http://127.0.0.1:8080 \
  --seed 1 --capture docker:litetraffic-demo-api
litetraffic dashboard
```

To open a CI run instead, download its evidence and point the dashboard at it:

```sh
gh run download <run-id> -n litetraffic-runs -D runs
litetraffic dashboard --runs-dir runs
```

Check out `feat/record-sharing` at its first commit to reproduce the failure.
