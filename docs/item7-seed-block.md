# Item 7 — the seed block

**Phase B input.** Derived from the eight endpoint captures of schat **staging**, compared against
what `values.yaml` + `values.staging.yaml` + `templates/configmap.yaml` already declare. Method
and ordering are in `item7-config-seed.md`; this file is the payload.

**Correction on method.** An earlier pass compared staging against "code defaults" computed by
importing `config.py` — which silently loaded the repo's dev `.env`, so it was really comparing
staging against a developer laptop. The comparison below is staging against **the chart**, which
is the one that determines what has to be written.

---

## 1. Numbers

|                                      |                           |
| ------------------------------------ | ------------------------- |
| Captured settings (flat, non-secret) | 110                       |
| Already declared in the chart        | 6                         |
| **Not in the chart**                 | **104**                   |
| Secret-named                         | 15 (only **4** non-empty) |
| Nested objects with no flat env var  | 10                        |

Most of the 104 are upstream defaults for engines schat does not use. The list below is what
actually needs writing.

---

## 2. Seed these — `values.staging.yaml` → `env:`

**26 settings.** Every one verified to differ from its code default, with code defaults computed
_outside_ the repo so the dev `.env` could not contaminate them.

```yaml
# ── Providers ───────────────────────────────────────────────────────────────
OPENAI_API_CONFIGS: '{"0":{"enable":true,"tags":[],"prefix_id":"","model_ids":[],"connection_type":"external","auth_type":"bearer"}}'

# ── Sdeck MCP  ⚠️ WITHOUT THIS, SLIDE GENERATION STOPS ──────────────────────
TOOL_SERVER_CONNECTIONS: '[{"url":"http://staging-presenton-app.presenton-staging.svc.cluster.local/mcp","path":"openapi.json","type":"mcp","auth_type":"none","headers":{"x-user-email":"{{USER_EMAIL}}"},"key":"","config":{"enable":true,"function_name_filter_list":"","access_grants":[{"principal_type":"user","principal_id":"*","permission":"read"}]},"info":{"id":"SDeck Staging","name":"Slide Deck","description":""},"spec_type":"url","spec":""}]'

# ── Document extraction ─────────────────────────────────────────────────────
CONTENT_EXTRACTION_ENGINE: 'docling'
DOCLING_SERVER_URL: 'http://docling-service.docling.svc.cluster.local:5001'
DOCLING_PARAMS: '{"do_ocr":true,"ocr_engine":"easyocr","ocr_lang":"en","images_scale":2,"table_mode":"accurate"}'

# ── Chunking + retrieval ────────────────────────────────────────────────────
CHUNK_SIZE: '1024'
CHUNK_OVERLAP: '200'
CHUNK_MIN_SIZE_TARGET: '256'
RAG_TEXT_SPLITTER: 'token'
RAG_TOP_K: '20'
RAG_TOP_K_RERANKER: '10'
RAG_EMBEDDING_BATCH_SIZE: '32'

# ── Web search (shared SearXNG) ─────────────────────────────────────────────
ENABLE_WEB_SEARCH: 'true'
WEB_SEARCH_ENGINE: 'searxng'
SEARXNG_QUERY_URL: 'http://searxng-http.searxng.svc.cluster.local:8080'
WEB_SEARCH_RESULT_COUNT: '5'
WEB_SEARCH_CONCURRENT_REQUESTS: '10'
WEB_LOADER_CONCURRENT_REQUESTS: '20'
BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL: 'true'

# ── Files ───────────────────────────────────────────────────────────────────
RAG_ALLOWED_FILE_EXTENSIONS: '["pdf","docx","xlsx","pptx","csv","txt","md","png","jpg","jpeg"]'
RAG_FILE_MAX_COUNT: '10'
RAG_FILE_MAX_SIZE: '30'

# ── Image generation ────────────────────────────────────────────────────────
ENABLE_IMAGE_GENERATION: 'true'
IMAGE_GENERATION_MODEL: 'Qwen/Qwen-Image'
IMAGES_OPENAI_API_BASE_URL: 'https://qwen-image.project-user-ivanbek.serving.mymswgl-ai-application.sunway.com/v1'

# ── Models / presets (Item 9) ───────────────────────────────────────────────
DEFAULT_MODELS: 'schat-quick'
MODEL_ORDER_LIST: '["deepseek-ai/DeepSeek-V4-Flash-0731","google/gemma-4-E4B-it","Qwen/Qwen-Image","Qwen/Qwen3.6-35B-A3B","schat-coding","schat-deepthink","schat-quick"]'
```

Plus the curated `DEFAULT_MODEL_METADATA` (§5) and `USER_PERMISSIONS` (§6).

### ⚠️ The API renames settings in its response — do not copy names from the capture

`GET /retrieval/config` returns `TOP_K`, `FILE_MAX_SIZE`, `TEXT_SPLITTER`. The **environment
variables are prefixed**: `RAG_TOP_K`, `RAG_FILE_MAX_SIZE`, `RAG_TEXT_SPLITTER`. Writing the short
name into the chart sets nothing and fails silently — the value simply stays at its default. Six
of the twenty-six above are affected.

### The web-search block was missed on the first pass — and how

The seven web-search settings were **absent from the first version of this list**. They were found
only when the production-alignment question forced a second look. The cause is worth recording,
because it is a flaw in the _method_, not a typo: the first pass walked the capture
subsystem-by-subsystem, and web search lives under `rag.web.*` — inside the retrieval subtree,
several levels below where the embedding and chunking settings sit — so scanning "retrieval" by
eye skipped it.

The second pass replaced the eye with a script: parse every `ConfigVar(...)` in `config.py` with
`ast`, extract the third positional argument as the code default, then compare it against every
`ALL_CAPS` key in the capture files. That matched **148** settings and returned **20** that
differ — the 19 already listed plus the web-search group. Any future capture should be diffed the
same way rather than read.

Had this shipped, `ENABLE_PERSISTENT_CONFIG=false` would have reverted `ENABLE_WEB_SEARCH` to
`False` and `WEB_SEARCH_ENGINE` to `''`. **Nothing would have errored.** The model would simply
have stopped searching the web, while `DEFAULT_MODEL_METADATA` continued to advertise
`web_search: true` — the same silent-failure shape as the `ENABLE_RAG_HYBRID_SEARCH` reranking
case, which is why web search is now on the post-deploy check list in `item7-config-seed.md` §7.

### Dropped after verification — already the code default

`RAG_TEMPLATE` (byte-identical to upstream, 1,445 chars), `ENABLE_OPENAI_API`, `PDF_LOADER_MODE`,
`ENABLE_MARKDOWN_HEADER_TEXT_SPLITTER`, `ENABLE_RAG_HYBRID_SEARCH`,
`ENABLE_RAG_HYBRID_SEARCH_ENRICHED_TEXTS`, `RAG_HYBRID_BM25_WEIGHT`,
`RAG_EMBEDDING_CONCURRENT_REQUESTS`, `ENABLE_ASYNC_EMBEDDING`, `RAG_RERANKING_BATCH_SIZE`,
`ENABLE_IMAGE_PROMPT_GENERATION`, `IMAGE_GENERATION_ENGINE`, `IMAGE_SIZE`, `IMAGE_STEPS`, and the
five task-generation flags.

Pinning a value that already equals the default adds a line someone must maintain and creates a
second place for the two to disagree. `ENABLE_RAG_HYBRID_SEARCH` is deliberately among these — the
chart omits it on purpose so the code default stays the single source of truth.

**`BAAI/bge-m3` is dropped from `MODEL_ORDER_LIST`** — that MLIS deployment was paused
2026-08-16. Embeddings and reranking were never served from it; they use the shared
`prod-infinity`.

---

## 3. Do **not** seed — upstream defaults for engines schat does not use

`MINERU_*`, `PADDLEOCR_VL_*`, `TIKA_SERVER_URL`, `MISTRAL_OCR_*`, `DATALAB_MARKER_*`,
`DOCUMENT_INTELLIGENCE_*`, `COMFYUI_*`, `AUTOMATIC1111_*`, `IMAGES_EDIT_*`, `IMAGE_EDIT_ENGINE`.

They appear in the capture only because the config row stores every key whether or not the engine
is selected. Extraction is `docling`; image generation is `openai`; image editing is off. Seeding
them would pin defaults for code paths that never run, and each one becomes a value someone has
to maintain.

Two are actively misleading if seeded: `MINERU_API_URL: "http://localhost:8000"` and
`PADDLEOCR_VL_BASE_URL: "http://localhost:8080"` — localhost inside a pod.

---

## 4. Secrets → `existingSecret`, never the ConfigMap

Four of the fifteen secret-named fields are non-empty:

| Key                             | What it is                                                                                    |
| ------------------------------- | --------------------------------------------------------------------------------------------- |
| `OPENAI_API_KEYS`               | LiteLLM                                                                                       |
| `RAG_OPENAI_API_KEY`            | embeddings (Infinity)                                                                         |
| `RAG_EXTERNAL_RERANKER_API_KEY` | reranker                                                                                      |
| `IMAGES_OPENAI_API_KEY`         | **a Kubernetes ServiceAccount token**, not a vendor key — expires 2027-06-25 (finding **C4**) |

`values.yaml:53-55` already documents the first two as belonging to the secret. The chart mounts
`existingSecret` wholesale through `envFrom.secretRef`, so these need no `secretKeyRef` stanza —
they only have to exist in that Secret under these exact names.

**Rotation, in context.** C4's remediation is _"rotate the four secrets, then delete the rows"_ —
and the reason is not public exposure. It is that the secrets sit at rest in the `config` table
and in every backup. **Completing Item 7 is the remediation**: once these live in the Secret and
the config rows are deleted, they stop being at rest in the database. Rotation then becomes
optional cleanup. Separately, and still open: confirming the RBAC bound to that ServiceAccount,
and whether holding it permits direct invocation of the Qwen-Image endpoint. That belongs to the
MLIS/platform owner.

---

## 5. ⚠️ `DEFAULT_MODEL_METADATA` — do not seed as captured

Staging holds:

```json
{
	"capabilities": {
		"file_context": true,
		"vision": true,
		"file_upload": true,
		"web_search": true,
		"image_generation": true,
		"code_interpreter": true,
		"terminal": true,
		"citations": true,
		"status_updates": true,
		"builtin_tools": true
	}
}
```

This is the **global default applied to every model**, and it is an upstream default nobody chose.
`terminal: true` for a feature pinned to `[]`; `code_interpreter: true` for a deferred one with
`ENABLE_CODE_EXECUTION=false`; `builtin_tools: true` turning on all twelve per model.

Nothing breaks today because the global flags override. But this is the "absent means enabled"
trap from `CLAUDE.md` in its widest form — flip one global flag later and this silently grants the
capability to every model at once. Seed a curated version instead:

```yaml
DEFAULT_MODEL_METADATA: '{"capabilities":{"file_context":true,"vision":true,"file_upload":true,"web_search":true,"image_generation":true,"citations":true,"status_updates":true,"builtin_tools":true,"code_interpreter":false,"terminal":false}}'
```

---

## 6. Curated `USER_PERMISSIONS` — and the blocker

Agreed to curate. Changes from what staging holds:

| Permission                                                        | Staging | Curated   | Why                              |
| ----------------------------------------------------------------- | ------- | --------- | -------------------------------- |
| `features.channels`                                               | true    | **false** | feature deleted                  |
| `features.notes`                                                  | true    | **false** | deferred; now server-gated       |
| `features.folders` · `memories` · `calendar` · `code_interpreter` | true    | **false** | deferred, globally off           |
| `chat.stt` · `tts` · `call`                                       | true    | **false** | Voice deferred; now server-gated |
| `chat.valves`                                                     | true    | **false** | Valves UI deleted                |
| `chat.rate_response`                                              | true    | **false** | ratings deleted with Evaluations |
| `chat.temporary`                                                  | true    | **false** | Temporary Chat deferred          |
| everything else                                                   | —       | unchanged |                                  |

**No behaviour changes today** — every one is already neutralised by a global flag. What changes
is the failure mode: right now, re-enabling `ENABLE_NOTES` would instantly grant Notes to every
user, because the per-user permission is already `true`.

**✅ Blocker resolved.** `USER_PERMISSIONS` now has an environment variable (`config.py`), so it
can be pinned like anything else. Two design points worth knowing before you write the value:

- **It merges over the defaults, it does not replace them.** State only the keys you want to
  change. A full replacement would silently drop any permission key a later upstream version
  adds — and an absent key reads as _permitted_ in several frontend gates (`?? true`).
- **Malformed JSON logs and falls back to the defaults** rather than raising. A typo in a
  permissions string should not stop the pod booting, because fixing it would then need a
  deploy to recover from a deploy.

So the curated block above can be written as just the differences:

```yaml
USER_PERMISSIONS: '{"features":{"channels":false,"notes":false,"folders":false,"memories":false,"calendar":false,"code_interpreter":false},"chat":{"stt":false,"tts":false,"call":false,"valves":false,"rate_response":false,"temporary":false}}'
```

Verified: with no env var the defaults are unchanged; with the block above only those twelve keys
flip and every sibling and group is preserved; with malformed JSON the app starts on defaults.

**Historic note — what the blocker was.** `USER_PERMISSIONS` had no environment variable. It is one of six settings that
cannot be pinned through the ConfigMap as things stand. It was one of six settings that could not be pinned; with the flag on, the permission matrix
would have reset to the code defaults on every boot. Of the remaining five,
`openai.api_configs` and `ui.model_order_list` are covered by the block in §2, leaving
`ui.prompt_suggestions`, `image_generation.openai.params` and
`auth.api_key.endpoint_restrictions` — all currently empty, so none blocks Phase D.

---

## 7. Before Phase D

- Seed everything in §2, plus the curated §5 and §6.
- Confirm the four secrets are in `existingSecret` under the exact names in §4.
- Then flip `ENABLE_PERSISTENT_CONFIG: "false"`, then delete the config routes.
- Post-deploy checks are listed in `item7-config-seed.md` §7 — the model selector order, Sdeck
  slide generation, reranking still firing, image generation, and a non-admin's permissions.

**One capture-wide caveat.** These values came from **one tenant**. The operator believes all
tenants share the same configuration; worth spot-checking a second tenant before seeding, since
per-tenant drift is the exact problem Item 9 exists to solve — and `ollama_config.url` in the
capture is `http://host.docker.internal:11434`, a Docker Desktop hostname that reached a deployed
database from somebody's laptop. Inert, but it is proof that drift happens.
