# Item 7 — Configuration becomes code: the seed inventory

**What this is.** Phase A of hardening-plan Item 7. Item 7's endgame is that configuration lives
in the chart rather than in each tenant's database, which is what finally makes ~44 admin config
routes deletable and closes the `PersistentConfig` trap for good. This document is the
prerequisite: what has to be seeded, what can safely take its code default, and the order the
steps must happen in.

It absorbs **Item 9** (model definitions become code), because they are the same problem — model
presets are among the settings the seed must carry, and the per-tenant drift Item 9 describes is
the same drift.

---

## 1. The problem, measured

`ENABLE_PERSISTENT_CONFIG=false` inverts precedence: environment becomes authoritative and the
stored `config` row is ignored. That is the goal. The hazard is what happens to settings the
chart does not mention.

|                                     | Count   |
| ----------------------------------- | ------- |
| `ConfigVar` settings in `config.py` | **360** |
| Mentioned anywhere in the chart     | **23**  |
| **Not in the chart at all**         | **337** |

Flip the flag today and those 337 fall back to their **code default**, silently discarding
whatever each tenant configured. Most are harmless — upstream defaults for features schat does
not use. The dangerous ones are those where a stored value differs from the code default, i.e.
anything ever set through Admin Settings.

**Only 15 of the 360 have no environment variable at all.** The security review estimated 23; the
real list is shorter and mostly irrelevant here:

| Setting                                                     | Matters to schat?                                   |
| ----------------------------------------------------------- | --------------------------------------------------- |
| `openai.api_configs`                                        | **Yes** — the MLIS/LiteLLM connection               |
| `ui.model_order_list`                                       | **Yes** — tier ordering (Flash / Deepthink / Coder) |
| `ui.prompt_suggestions`                                     | **Yes**                                             |
| `user.permissions`                                          | **Yes** — the whole permission matrix               |
| `image_generation.openai.params`                            | **Yes** — image generation is in scope              |
| `auth.api_key.endpoint_restrictions`                        | Yes, minor                                          |
| `audio.stt.allowed_extensions`                              | No — Voice deferred and now gated                   |
| `code_interpreter.jupyter.*` (4)                            | No — deferred, no external Jupyter                  |
| `evaluation.arena.models`                                   | No — Evaluations deleted                            |
| `ollama.api_configs`, `rag.web.search.ollama_cloud_api_key` | No — Ollama removed                                 |
| `oauth.microsoft.picture_url`                               | No — IAM owns identity                              |

So the no-env-var problem is **six settings**, not twenty-three. Each needs either a value written
into the seed or a new environment variable added in `config.py`.

---

## 2. Scope triage

Restricting to subsystems schat actually uses:

| Subsystem                     | Settings | In chart | Note                                                                      |
| ----------------------------- | -------- | -------- | ------------------------------------------------------------------------- |
| `rag`                         | 137      | 6        | **the bulk** — bge-m3 embeddings, reranker, Docling, chunking, web search |
| `image_generation` + `images` | 33       | 0        | in scope                                                                  |
| `task`                        | 18       | 0        | title / tag / query generation                                            |
| `ui`                          | 17       | 3        | includes model order list                                                 |
| `auth`                        | 6        | 2        |                                                                           |
| `openai`                      | 4        | 1        | **the MLIS connection**                                                   |
| `models`                      | 3        | 0        | presets — this is Item 9                                                  |
| `user`                        | 1        | 0        | the permission matrix                                                     |
| `tool_server`                 | 1        | 0        | **Sdeck MCP**                                                             |
| **in-scope total**            | **224**  | **13**   | **211 to seed or verify**                                                 |

Out of scope and safe on code defaults: `oauth` (52) and `ldap` (17) — IAM owns identity;
`audio` (29) — deferred and now server-gated; `code_interpreter` + `code_execution` (15) —
deferred; `evaluation`, `channels`, `notes`, `calendar`, `automations`, `memories`, `folders` —
deleted or flag-disabled.

---

## 3. ⚠️ The one that breaks Sdeck

`TOOL_SERVER_CONNECTIONS` is **`ConfigVar`-backed, configured through Admin Settings, and appears
nowhere in the chart.** Sdeck's MCP connection lives in the database today.

Flipping `ENABLE_PERSISTENT_CONFIG` without seeding it first **stops slide generation**. It does
have an environment variable, so it is seedable — but it has to be in the seed _before_ the flip,
not after. Capture the live value first:

```sql
SELECT data->'tool_server'->'connections' FROM config ORDER BY id DESC LIMIT 1;
```

The same applies per tenant, since each tenant has its own `config` row.

---

## 4. Capturing current state

`GET /api/v1/configs/export` would have dumped this in one call. It is **deleted** — it returned
every stored credential unmasked (see `rollout-scope.md` §3.1). Use SQL instead, which is what
the security review recommended:

```sql
-- whole config row, newest first
SELECT data FROM config ORDER BY id DESC LIMIT 1;
```

Diff that against the code defaults in `config.py`. Anything that differs is a candidate for the
seed. Anything identical can be dropped — seeding a value that already matches its default adds
maintenance for nothing.

**Do this per tenant.** Under multi-tenancy each tenant has its own `config` row, and drift
between them is precisely the problem Item 9 was raised to fix.

---

## 5. Order of operations

The sequence is not arbitrary. Each step assumes the previous one.

```
A. Seed inventory        this repo      ← this document
B. Write the ConfigMap   manifest repo  seed everything from §2 that differs from its default
C. Delete config routes  this repo      ~44 admin routes
D. Flip the flag         manifest repo  ENABLE_PERSISTENT_CONFIG=false
```

**C before B leaves no way back.** Admin Settings is the only UI that can edit a stored config
value; delete the routes while the seed is wrong or incomplete and there is no in-app path to
correct it — only SQL.

**D before B silently reverts 337 settings** to code defaults, including the MLIS connection and
Sdeck.

**B before D is what makes D safe**, and B is the step that needs the SQL capture from §4.

---

## 6. What this unlocks

Route counts against the deletion manifest's targets:

|              | Now | After Item 7 | Manifest target |
| ------------ | --- | ------------ | --------------- |
| Total routes | 342 | ~300         | ~330            |
| Admin-gated  | 80  | **~36**      | ~36             |

Item 7 is the single largest remaining reduction, and it is what lets `JWT_EXPIRES_IN` and
`USER_PERMISSIONS_WORKSPACE_TOOLS_ACCESS` become genuinely authoritative rather than
defence-in-depth — both are currently writable at runtime through the very endpoints Item 7
deletes.

---

## 7. Verification

None of B, C or D is provable in the dev loop. Boot-and-build says nothing about config
precedence. Each needs a staging deploy, and with `Recreate` + `replicaCount: 1` each is an
outage window — so batch them rather than deploying three times.

After D, confirm on staging:

- the model selector still lists Flash / Deepthink / Coder in order
- Sdeck slide generation still works (the `TOOL_SERVER_CONNECTIONS` check)
- retrieval still reranks (`ENABLE_RAG_HYBRID_SEARCH` — a silent failure mode; the reranker stays
  configured but is never called if it reverts)
- **web search still returns results** (`ENABLE_WEB_SEARCH` / `SEARXNG_QUERY_URL` — the same silent
  shape; the model just stops searching, and `DEFAULT_MODEL_METADATA` keeps claiming it can)
- image generation still works
- a non-admin user still has the permissions they had before (`user.permissions`)

---

## 8. Phase D is parked — VAPT

**Status: A, B and C are done. D is blocked, and not on a technical dependency.**

D requires the four API keys to be written into `schat-staging-secret` first. That cannot happen
while the VAPT engagement is running: rotating or re-placing credentials mid-assessment changes
the target underneath the tester and invalidates whatever they have already probed.

So Phase D waits for VAPT to close. This is the same reason several other items are parked, and
recording it here means the block is attributable rather than looking like an oversight — the
sequencing constraint is the engagement, not the code.

**What is safe to do in the meantime:** everything in B, because seeding a ConfigMap value while
`ENABLE_PERSISTENT_CONFIG` is still `true` changes nothing at runtime — the stored DB value keeps
winning. The chart can be made completely correct and deployed with zero behavioural change, which
means the only step left after VAPT is placing four secrets and flipping one flag.

**What must not be forgotten:** the flip is only safe _because_ B is complete. If the seed is
still missing an entry when someone flips the flag months from now, that setting reverts silently.
The web-search miss recorded in `item7-seed-block.md` §2 is the proof that this is a live risk, not
a hypothetical one.

---

## 9. `values.production.yaml` — what actually has to differ

Production merges on top of `values.yaml`, so the 45 keys in the base file are already inherited;
the real gap is **44 keys that staging sets and production does not**. Sorting them by _why_ they
differ, rather than by subsystem, gives a much shorter list of decisions than the raw count
suggests.

### Copy verbatim — 35 keys

These are **shared cluster services and platform policy**, and the operator's read is correct:
there is one Infinity, one Docling, one SearXNG and one LiteLLM in the AI server, addressed by
in-cluster DNS (`prod-infinity.embedding.svc`, `docling-service.docling.svc`,
`searxng-http.searxng.svc`) or by a single external hostname. A namespace change does not change
any of them.

| Group                                                         | Keys |
| ------------------------------------------------------------- | ---- |
| Embeddings + reranking                                        | 6    |
| Web search (SearXNG)                                          | 7    |
| Document extraction (Docling)                                 | 3    |
| Chunking + retrieval tuning                                   | 7    |
| File caps                                                     | 3    |
| Image-vision LLM (same LiteLLM)                               | 2    |
| Image generation — enable + model                             | 2    |
| Provider config, model order, defaults, metadata, permissions | 5    |

The last group is policy, not infrastructure: `USER_PERMISSIONS`, `DEFAULT_MODEL_METADATA`,
`MODEL_ORDER_LIST` and `DEFAULT_MODELS` **should** be identical, because a permission matrix or a
capability advertisement that differs between staging and production means staging stops being a
test of production.

### Must differ — 5 keys

| Key                          | Why                                                                                          |
| ---------------------------- | -------------------------------------------------------------------------------------------- |
| `LANDING_PAGE_URL`           | contains `-staging`                                                                          |
| `WORKOS_ORGANIZATION_ID`     | staging WorkOS org                                                                           |
| `WORKOS_ORGANIZATION_ID_EDU` | staging WorkOS org                                                                           |
| `TOOL_SERVER_CONNECTIONS`    | Sdeck — see below                                                                            |
| `CONTENT_SECURITY_POLICY`    | staging pins `""`; production is where the report-only → enforced promotion eventually lands |

**Sdeck is not just a hostname swap.** The value is a JSON blob, and three things inside it are
environment-bound: the cluster URL
(`staging-presenton-app.presenton-staging.svc.cluster.local`), the **namespace** segment, and
`info.id`, which reads `"SDeck Staging"` — a label that would show up in the production UI if
copied. Dropping `-staging` from the hostname is the operator's expectation and is plausible, but
the production service and namespace names must be **read off the Sdeck production deployment**,
not inferred. A wrong URL here fails the way §3 describes: slide generation stops.

### Needs a decision — 4 keys

**`IMAGES_OPENAI_API_BASE_URL` points at a personal MLIS project namespace**
(`qwen-image.project-user-ivanbek.serving...`). It is the same cluster, so it _works_, but a
user-scoped serving endpoint can be paused or deleted by its owner — which is exactly what
happened to `BAAI/bge-m3` on 2026-08-16. Fine for staging; production image generation should hang
off a shared or team-owned endpoint before go-live. This is a conversation with the model's owner,
not a config edit.

**The four tenant-pool keys** (`TENANT_DB_POOL_SIZE`, `TENANT_DB_MAX_OVERFLOW`,
`TENANT_ENGINE_IDLE_TIMEOUT`, plus `TENANT_ENGINE_CACHE_SIZE` where staging overrides the base
`10` with `50`) are safe to copy but are **capacity settings, not correctness settings** — they
size a connection pool per active tenant. Copying staging's numbers into a 10K-user production is
a guess. Note these are _not_ the tenant groups themselves, which live in IAM and are created by
the MT/RBAC owner; nothing about tenant membership belongs in this chart.

### Two corrections to the production file as it stands

1. **`ENABLE_ADMIN_FUNCTIONS_UI: "false"` is now a dead line.** The flag was retired on 2026-08-14
   when Item 2 deleted the Functions router — `env.py:854` records this and nothing reads it any
   more. It should be removed, not left looking like an active control.

2. **`ENABLE_ADMIN_SETTINGS_UI: "false"` has a consequence it did not have when it was written.**
   Admin Settings is now a **single tab, Models**, and that tab is the only UI path to
   `POST /api/v1/models/import` — the only way to seed model presets into a new tenant until Item 9
   makes model definitions code. With the flag off, production has no such path, so onboarding a
   tenant means either an outage window to flip it on and off again, or an API call with an admin
   token. Leaving it off is defensible; doing so **unknowingly** is not, which is why it is
   recorded here.
