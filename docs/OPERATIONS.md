# schat.ai — Operations

Runbook for whoever deploys and looks after schat. It covers what the code and the manifest comments do not say in one place: how a change reaches the cluster, where config lives, what fails silently, and what to check afterwards.

It does not repeat other docs. For what was removed or hidden and why, see [`rollout-scope.md`](rollout-scope.md). For how config was moved into the chart, see [`item7-config-seed.md`](item7-config-seed.md) and [`item7-seed-block.md`](item7-seed-block.md). For security notes, see [`SECURITY.md`](SECURITY.md). For product scope, see the SCore.ai PRS and SChat FRS in Confluence (space SASAT).

**No secret values belong in this file, in Confluence or in chat.** Key names only.

---

## 1. Where things live

| What | Where |
| --- | --- |
| App code, image build | this repo (`SunwayDevelopers`), workflow `.github/workflows/build-deploy.yml` |
| Deployment config (Helm chart, values, image tag) | `SunwayDevelopers/ai-tools-openwebui-manifest`, branch `main`, `helm-chart/values.{staging,production}.yaml` |
| Images | ACR, repository `schat`, tagged with the commit SHA |
| Secrets | Kubernetes Secrets `schat-staging-secret`, `schat-prod-secret`. They are created outside git. |
| Tenant identity, DB and storage routing | the IAM service (`IAM_BASE_URL` in the values files) |

What actually runs is whatever `image.tag` the manifest pins. Check it there, not in this repo's branches.

---

## 2. Deploying

1. Push your code. A push does **not** deploy anything.
2. GitHub → Actions → **Build and Deploy** → *Run workflow*. Choose `staging` or `production`. Leave `image_tag` blank to build from the selected ref.
3. The workflow builds the image (linux/amd64), pushes it to ACR tagged with the SHA, then commits `ci: deploy <sha> to <env>` to the manifest repo, changing only `image.tag` in that environment's values file.
4. The cluster picks up the new tag (either ArgoCD sync or manual `helm upgrade`).

Things to know:

- **Rollback**: run the workflow again with `image_tag` set to the previous SHA. That skips the build and only re-points the manifest. The previous SHA is in the manifest repo history (`git log -p helm-chart/values.production.yaml`).
- **Runs are serialised** per environment, so two deploys cannot overwrite each other's tag.
- **No tests run in CI.** Nothing blocks a bad deploy. Run `ruff format .`, `npm run format` and `npm run i18n:parse` yourself first.
- The chart-render step is **advisory**. A warning there does not stop the commit, but `helm upgrade` will still be rejected by the chart's own guards (`templates/validate.yaml`). Read the warning.
- **One replica, `Recreate` strategy**: every deploy and every restart is a short full outage. Batch config changes into one deploy.
- Deploy to staging first and run the checks in §5.

---

## 3. Configuration

### Where a setting is decided

schat is deployed with `ENABLE_PERSISTENT_CONFIG: "false"` in both values files, as of the manifest checked on 2026-11-22. The environment is therefore authoritative, and a value stored in the database `config` row is ignored.

```
kubectl exec -n <ns> deploy/<name> -- printenv ENABLE_PERSISTENT_CONFIG
```

Consequences:

- **To change a setting, edit the values file in the manifest repo and deploy.** The Admin Settings tabs have been deleted, so there is no UI to change it at runtime.
- A setting that is not in the values file falls back to its **code default**, not to whatever an old DB row held. If you add config by any other route, compare it with the live DB first.
- Some paths always take the environment and never read the DB, even with the flag on (`_NEVER_PERSIST_PATHS` in `backend/open_webui/internal/config.py`): JWT expiry, the upload extension allowlist and four API keys.
- **History:** the flag was flipped on 2026-08-21 and reverted the same day. `IMAGES_OPENAI_API_KEY` had lived only in the DB, so image generation failed with `400: [ERROR: Forbidden]`. If you ever flip this flag again, do it as its own change and run the full checklist in `item7-config-seed.md` §7.

### Plain env vs PersistentConfig (still matters for local dev)

Plain env vars are read on every restart. PersistentConfig vars take the DB value over the env once a DB row exists. In local dev (`dev.ps1`) the persistent flag is on, so a PersistentConfig value changed in the database wins over `.env`. `dev.ps1` documents which is which.

### Secrets

- Names: `schat-staging-secret`, `schat-prod-secret`. The full key checklist and the two gotchas (omit-vs-empty, and pods do not restart on a Secret change) are in `values.yaml` in the manifest repo.
- Keys that must exist, or a capability breaks silently on the next restart: `OPENAI_API_KEYS` (LiteLLM, chat), `RAG_OPENAI_API_KEY` (embeddings), `RAG_EXTERNAL_RERANKER_API_KEY` (reranking fails silently without it), `RAG_IMAGE_VISION_LLM_API_KEY`, `IMAGES_OPENAI_API_KEY`.
- List key names only: `kubectl get secret <name> -n <ns> -o go-template='{{range $k,$v := .data}}{{$k}}{{"\n"}}{{end}}'`
- After changing a Secret, restart the deployment (`kubectl rollout restart deploy/<name> -n <ns>`) and expect an outage window.
- Secrets that were committed earlier remain in git history. This is accepted ⟦approver, date⟧.

### Env files for local dev

`.env.example` is the baseline for anything that is not `dev.ps1`. It marks each variable `[dev.ps1 wins]` or `[PersistentConfig]`. Real values come from ⟦secrets manager⟧, never from Confluence. Local infrastructure comes from `docker-compose.dev.yml` (Postgres, Qdrant, Docling, SearXNG, MinIO, Redis).

---

## 4. Multi-tenancy

- schat runs multi-tenant only (`ENABLE_MULTI_TENANCY` is pinned in `templates/configmap.yaml`). Every request resolves its tenant through IAM, and each tenant has its own database, Qdrant and storage connection.
- **Schema changes are not applied by deploying.** Alembic migrations run per tenant database, and tenant databases are migrated manually. A new migration that nobody applies to a tenant breaks only that tenant.
- Known case: `guardrail_event` (migration `b7f4a1c2d3e8`) must exist in each tenant DB. Guardrails still run without it, but the audit rows are not written.
- A new tenant starts with no Groups or AccessGrants, so non-admin users see no models until access is granted.
- The chart refuses to deploy if trusted-header auth or `WEBUI_ADMIN_PASSWORD` is set (`templates/validate.yaml`). That is deliberate.

---

## 5. After every deploy — the failures are silent

Do these on staging, then on production:

1. Pod is `Running` and ready (`kubectl get pods -n <ns>`), logs show a clean start.
2. The model selector shows **Flash** and **Deepthink**, in that order, with Deepthink as the default. The Coder tier is hidden.
3. Upload one **scanned** PDF and check the log for a Docling call. A blank `DOCLING_SERVER_URL` does not error; extraction silently falls back to weaker local loaders.
4. Ask a question over a knowledge base. Reranking should run. A missing reranker key or URL leaves it configured but never called.
5. Web search returns results (SearXNG).
6. Generate an image.
7. From schat, generate a slide deck through SDeck.
8. Send a message containing a made-up NRIC such as `900101-14-5678` and confirm it is redacted. Then look for a row in `guardrail_event`.
9. Check `GET /api/v1/retrieval/embedding` as an admin if you touched embedding settings.

---

## 6. Troubleshooting

Use `<ns>` for the schat namespace ⟦fill⟧.

| Need | Command |
| --- | --- |
| Pods and state | `kubectl get pods -n <ns>` |
| Why a pod will not start | `kubectl describe pod <pod> -n <ns>` |
| App logs | `kubectl logs <pod> -n <ns> --tail=200 --timestamps` |
| Restart | `kubectl rollout restart deploy/<name> -n <ns>` then `kubectl rollout status deploy/<name> -n <ns>` |

Known traps:

- **`exec format error` / CrashLoopBackOff** after a deploy: the image was built for the wrong architecture. CI builds linux/amd64; do not build and push by hand from an ARM machine.
- **Pod not ready after the first mount of a PVC**: recursive `fsGroup` on an old root-owned volume can be slow enough to fail the readiness probe. Do not bundle that kind of change with anything else.
- **Embedding or reranker changes**: only the **Reindex** action is safe. *Reset Vector Storage* deletes every knowledge base record, and *Reset Upload Directory* is irrelevant when storage is S3. Reindex returns success regardless of per-file errors, so grep the log for `Failed to process`. After a model or dimension change also run `POST /api/v1/knowledge/metadata/reindex`. Chat-attachment collections are not reindexed and age out under the retention rules.
- **Upload failures after a config change**: check `rag.file.allowed_extensions`. A stale value once rejected every PDF.
- **`/static` shows upstream branding**: `STATIC_DIR` is unset.
- **Security headers**: `PERMISSIONS_POLICY` must have no spaces after commas, or it is silently ignored.
- **Retention**: chats are capped at 30 per user and expire after 30 days (`utils/retention.py`). `scripts/reap_orphan_files.py` removes files left behind by old deletions (dry-run by default, `--purge` to delete).
- **Load**: production saturates at about five chat completions per second on one replica (see the production load test page in Confluence). There is no admission control on `main` or `staging`: it exists only on the `feat/uiux-polish` branch (commit `c43943183`, with a frontend "taking longer than usual" message in `33f3559`) and was reverted from `main` on 2026-09-28 ⟦confirm why⟧. Under overload requests queue and then fail with a generic connection error.

---

## 7. Dependencies and who owns them

| Service | Used for | Owner |
| --- | --- | --- |
| LiteLLM gateway | all model calls | AI Team |
| IAM service | tenant resolution, per-tenant DB and storage | Shao Wei |
| Docling, Infinity (bge-m3 + reranker) | extraction, embeddings, reranking | platform side |
| SearXNG | web search | packaged chart handed over separately; may be replaced |
| SDeck | slide generation through MCP | see the SDeck repo docs |
| WorkOS | sign-in (OIDC) | Shao Wei/Joshua from Digital Development team |

Model hosting is moving to the shared namespace `project-llm-deployment`. When a model moves, update the image-generation endpoint and the LiteLLM route in the values files, redeploy, and re-run §5.

---

## 8. Open items (verify, then delete from this list)

- Branches: `main` is production, `staging` is the experiment line. As of 2026-11-22 the two have identical code, but the **staging deployment** still runs image `33f3559`, built from `feat/uiux-polish`, which has admission control and the high-usage message that neither branch contains. Redeploying staging from `staging` drops them unless they are ported first. ⟦decide: port or retire⟧
- ⟦ArgoCD or manual sync⟧
- ⟦tenant migration procedure, owner, and which tenants have `guardrail_event`⟧
- ⟦live check that `ENABLE_PERSISTENT_CONFIG` is `false` in both environments⟧
- ⟦a stale comment in the values files still says "Flash / Coder / Deepthink"⟧
