# schat.ai — Rollout Scope Record

**What this is.** The record of what schat deliberately does *not* expose, why, and what
remains true after each decision. It exists so that a capability removed or hidden for the
phase 1 rollout is a **decision on file** rather than something a future reader discovers by
accident — and so the reasoning survives a fresh clone, which a local file does not.

**Audience.** Reviewers, CAB, ISMS. Engineers working in the code should read `CLAUDE.md`
for the per-file mechanics; this document answers *why*, not *where*.

**Scope classes.** Every row below is one of three, and the class determines the mechanism:

| Class | Meaning | Mechanism |
|---|---|---|
| **Removed** | out of scope; not coming back in a foreseeable phase | code deleted — git history is the archive |
| **Deferred** | under review for a later phase | hidden behind a guard or flag; code retained |
| **Retained, gated** | in scope, but reachable only under a stated condition | interlock or config gate |

Recovering removed code: `git log --oneline --diff-filter=D -- <path>` finds the deleting
commit, `git show <sha>^:<path>` prints the file. Rows below name the commit *subject* rather
than a SHA, so the reference survives rebases and amends.

---

## 1. The access model everything else depends on

Read this first; several rows below are only defensible in light of it.

schat has **two** role values in code — `user` and `admin` (`utils/auth.py`). The intended
three-tier model (super admin / BU admin / user) is implemented in the **multi-tenancy layer**,
not in schat's role column: membership and role are resolved per tenant from IAM and synced
onto `user.role` on every request.

**Consequence: `role === 'admin'` does not distinguish a super admin from a BU admin.**
`get_admin_user` checks nothing but `role != 'admin'`, so a departmental admin passes every
admin check in the codebase, in their own tenant.

Two things follow, and they shape most of this document:

- **A UI gate on `role === 'admin'` is not a super-admin gate.** Where a surface must be kept
  from BU admins, it is hidden from everyone — including the AI team — rather than gated on a
  role that cannot express the distinction.
- **Anything an admin can reach, a BU admin can reach.** "Admin-only" is a much wider group
  than it sounds, which is why several capabilities were removed outright rather than
  restricted.

When the tier becomes expressible in code, the re-enable steps below should gate on *that*
signal, never on `role === 'admin'`.

---

## 2. Why a disabled flag may not be disabled

Configuration comes in two kinds and the difference has repeatedly caused surprises:

- **`PersistentConfig`** — the environment variable seeds the database on **first boot only**.
  After that the stored value wins and the env var is ignored. Changing one on an existing
  deployment requires changing it where it is stored, not in the chart.
- **Plain env** — re-read at import on every restart. Setting the variable always takes effect.

A row below that says "flag" states which kind it is. Two live consequences worth carrying
into any review:

- A chart value can be **inert** — present, correct, and doing nothing — because a stored value
  outranks it.
- Conversely, several protections currently rest on a **code default with nothing in the chart**.
  That is sufficient today but has no second line of defence: a rollback to an older image
  silently restores the old default, with no error and no log line.

---

## 3. Scope decisions

### 3.1 Removed — server-side code execution

| | |
|---|---|
| **What** | Tools authoring, Functions authoring, Pipelines |
| **Class** | Removed |
| **Mechanism** | authoring endpoints deleted; `utils/plugin.py`, the `exec()` loader, deleted with them |
| **Commit** | `git log --grep='delete tool authoring'` (and the functions / pipelines commits alongside it) |

**Justification.** A "Tool" was Python source stored in a database row and executed by `exec()`
on the server when a model invoked it — no sandbox, with the pod's filesystem, network,
database credentials and environment, as root. Functions and Pipelines were the same pattern in
two further copies. Authoring was **not** admin-gated: `POST /api/v1/tools/create` required only
a logged-in user holding the `workspace.tools` permission, which reads like a feature toggle and
is not one.

The capability was never used: the `tool` table is empty, and the `function` table held exactly
one row — the guardrails filter — which now lives in code (§4). Pipelines was confirmed unused
by the operator.

**What "deleted" means precisely, because it differs by feature.** Functions was self-contained
and its router is gone entirely. Tools and Pipelines are not: each keeps a runtime path that the
chat request still traverses, so in both the *authoring surface* was removed and the *execution
path* left in place —

- **Tools** keeps the tool-server listing, which executes nothing inside schat and is how the
  Sdeck MCP server reaches a model. What went is the 13 authoring routes, including
  `POST /create`, and the local-tool listing that could only ever return `exec()`-backed rows.
- **Pipelines** keeps three filter helpers imported by `utils/chat.py`, `utils/middleware.py` and
  `routers/tasks.py`; removing the module outright would break the chat pipeline for no security
  gain. What went is all 8 endpoints — upload, add, delete, and valve editing. The helpers are
  inert with no pipeline configured, and with no route left to register one, none can be.

The distinction matters to a reviewer: neither is "the feature is still there but hidden". In
both cases the route by which code entered the system is gone, and what remains cannot admit
new code.

**A second execution path went with it, which is worth stating separately.** Besides the two
`exec()` calls, `utils/plugin.py` provided a startup routine that read a `requirements:` field
from each stored tool and function and **pip-installed the named packages into the running pod
on every boot**. So database content could introduce not just code but arbitrary *dependencies*,
fetched from the public index at start-up. That routine is deleted along with the module.

**Verification that the tables are now inert.** After the deletions, the only remaining writers
to `function.content` and `tool.content` in the entire backend were inside `plugin.py` itself —
self-updates it performed after loading a row. No router, no service, and no migration can
create a row. With `plugin.py` gone there is no writer and no reader left.

**The frontend followed.** The user interface for these capabilities was deleted in a second
pass: the Functions API client and admin pages, the Workspace → Tools pages, the tool-authoring
clients (15 reduced to 2), both valve editors, and the custom-action buttons with the endpoint
behind them. `getTools()` and `getToolList()` survive because tool **servers** are a different
thing — they execute nothing inside schat and are how the Sdeck MCP server reaches a model.

`ENABLE_ADMIN_FUNCTIONS_UI` was **retired** with those pages. A flag that hides a route which no
longer exists is worse than no flag: it reads as though the capability is merely switched off,
inviting someone to switch it back on. Any manifest still setting it is inert and the line can be
dropped. `ENABLE_ADMIN_SETTINGS_UI` is unaffected and still governs Admin → Settings.

**Verified against the plan's own check:** no Python `exec()` remains anywhere in the backend.
The only surviving matches are Sunway comments recording what was removed, plus a Redis
pipeline's unrelated `Batch.exec()`.

**Residual risk after removal.** None from this path; the code no longer exists rather than
being unreachable. Two adjacent things remain by design and are *not* the same class: the code
interpreter runs in browser Pyodide or an external Jupyter, outside the schat process, with its
own gates; and `kb_exec` is a *simulated* shell that parses read-only commands against knowledge
documents and executes nothing.

**What would reverse it.** A reviewed, code-only tool mechanism — tools as modules in the
repository, added by pull request rather than HTTP POST. That is the parked proposal in the
security review's `to-be-reviewed-later.md` §1, and roughly 4,700 lines of tools already work
that way. Restoring database-backed authoring is not the path back.

### 3.2 Removed — administrative access to other users' chat content

| | |
|---|---|
| **What** | `/chats/list/user/{id}`, `/chats/all/db`, `/utils/db/download`, the three content-bearing analytics endpoints — all **deleted**; the `/chats/{id}` admin fallback — **gated** |
| **Class** | Removed / gated |
| **Mechanism** | code deleted, plus `ENABLE_ADMIN_CHAT_ACCESS` and `ENABLE_ADMIN_EXPORT` for what remains — both **plain env**, both defaulting `False` |

**Justification.** Upstream allows any admin to read any user's chats. Under multi-tenancy that
means every BU admin, for every user in their tenant, through the browser.

The analytics endpoints were the subtle case: `/analytics/messages` returns full message text,
`/models/{id}/chats` returns the first 200 characters of every chat's opening message, and
`/models/{id}/overview` returns conversation tags. All three were gated on `get_admin_user`
alone, so disabling admin chat access closed the obvious paths while these stayed open — and
the second was reachable through the UI, two clicks from the Analytics dashboard.

**Update — most of this row is now deleted code rather than gated code.** The three analytics
endpoints were flag-gated first, to keep an admin support path reversible. That reversibility
only had value while a UI existed to reverse to; the drill-down modal is gone, so the endpoints
guarded nothing any caller used. Three more followed for the same reason:

| Endpoint | What it returned |
|---|---|
| `GET /chats/list/user/{id}` | another user's chat list, to any admin — with `UserChatsModal`, the admin UI that browsed it |
| `GET /chats/all/db` | every chat message belonging to every user, in one response |
| `GET /utils/db/download` | the raw SQLite database file |

The last two were already double-locked behind `ENABLE_ADMIN_EXPORT`, and the third only ever
worked on SQLite, so both were inert on a Postgres deployment with the flag unset. They were
deleted anyway, on the principle that **a capability which only works once someone sets an
environment variable is a capability waiting to be switched on by accident** — and a
whole-database download reachable from a browser is an ops action at the cluster layer, not a UI
button.

**A side effect worth recording:** with these gone, `routers/chats.py` has **no admin-gated
endpoint left at all** — `get_admin_user` is no longer imported there. The entire chats router is
now user-scoped.

**What `ENABLE_ADMIN_CHAT_ACCESS` still governs**, and why it was kept: four live gates inside
*user-facing* endpoints (`chats.py:886, 893, 952, 1271`) — the admin fallback in `GET /chats/{id}`,
the share lookup, and `clone/shared`. Those are where the genuine privacy-versus-support policy
question lives, and it is a policy call rather than a technical one.

**Residual risk.** The five surviving analytics endpoints return counts and totals only. But an
admin still sees *metadata* — per-user message counts, token counts, activity. That is a
deliberate retention for capacity and cost management, and should be confirmed as intended
rather than assumed.

**The admin read paths are now deleted, not gated.** This row previously rested on
`ENABLE_ADMIN_CHAT_ACCESS` being `False`. The plan's target was stricter — *"endpoints returning
other users' messages: 4 → 0"* and *"Admin reading user messages: Closed"* — and off-by-default
is not closed: it is one environment variable from open, and `admin` does not distinguish a super
admin from a BU admin. Four code paths were therefore removed outright:

| Endpoint | What the admin branch did |
|---|---|
| `GET /chats/share/{share_id}` | re-read the id as a **chat** id, returning an **unshared** chat |
| `GET /chats/share/{share_id}` | skipped the access-grant check entirely for an admin |
| `GET /chats/{id}` | returned **any** user's chat by id |
| `POST /chats/{id}/clone/shared` | cloned an **unshared** chat by id |

Access is now by ownership or an explicit grant, for every role. `ENABLE_ADMIN_CHAT_ACCESS` is no
longer imported by `routers/chats.py` at all; it still gates the analytics guard.

**One of these was not behind the flag.** The grant check in `clone/shared` was bypassed on
`user.role != 'admin'` alone, so it was live even with the flag off — an admin could clone any
*shared* chat without holding a grant. Narrower than the others (shared content only), but it
means the pre-existing posture was never quite "off".

**Two admin WRITE paths were closed on the same pass**, and they were arguably worse than the
reads. `POST /chats/{id}/messages/{message_id}` let an admin rewrite a stored message in another
user's chat, and `POST /chats/{id}/messages/{message_id}/event` let them emit an event into
someone else's conversation. Neither was gated on `ENABLE_ADMIN_CHAT_ACCESS` — both were live
with the flag off. The reason to rank them above the reads: **an edited message is
indistinguishable from one the model actually produced**, so the chat record stops being evidence
of what happened. Both are now owner-only.

**The cost, stated plainly:** nobody — including a super admin — can now open a user's chat to
investigate a complaint or a misuse report, or correct a message in one. Restoring that requires
a reviewed commit and a deploy, which is the intent.

**Four further admin bypasses were closed once their justification was actually checked.** They
had been left on the reasoning that each served an operational need. None did:

| Endpoint | Claimed need | What the code showed |
|---|---|---|
| `DELETE /chats/{id}` | user-deletion cascade, retention sweep | **Neither.** Retention calls `Chats.delete_chat_by_id()`; user deletion calls `Chats.delete_chats_by_user_id()`. Both at the model layer, never over HTTP. The branch also skipped the `chat.delete` permission check. |
| `GET /chats/stats/export/{chat_id}` | admin metadata view | Sole caller is `SyncStatsModal` — a **user** feature. Returns per-message role, model, timestamp, content length, rating and **tags** for any chat. No text, but we deleted the analytics `/overview` endpoint partly *because* it returned conversation tags. |
| `GET`/`POST /chats/shared/{id}/access` | grant management | Sole caller is `ShareChatModal` — **the user's own share button**. An admin could read and rewrite anyone's sharing. |

The general point, worth carrying to the next router: these were **upstream defaults nobody chose**,
not decisions. Users own their sharing through the share button, and the 30-chat cap and retention
sweep handle lifecycle automatically, so no support workflow depended on any of them.

**What remains admin-differentiated in this router, deliberately:** the `ENABLE_COMMUNITY_SHARING`
gate and the `chat.share` permission check both let an admin act without the corresponding user
permission — but every one of those paths looks the chat up with
`get_chat_by_id_and_user_id(id, user.id)`, so an admin can only ever act on **their own** chat.
Feature gates, not cross-user access.

**⚠ Not addressed by this row.** These controls stop *future* reads. Message content already
stored — including any personal data — is untouched, as are database backups. See §4.

### 3.3 Removed — administrative access to other users' files

| | |
|---|---|
| **What** | Nine admin bypasses in `routers/files.py`, one in `routers/retrieval.py`, and `DELETE /api/v1/files/all` |
| **Class** | Removed |
| **Mechanism** | code deleted; access is ownership or an explicit grant, for every role |

**Justification.** The same pattern as §3.2, on data that is arguably more sensitive — a document
a user uploaded, rather than the conversation about it. Every file endpoint carried
`or user.role == 'admin'` in its access check, covering metadata, extracted text, the file bytes,
the HTML rendering, renaming and deletion.

**The listing endpoints were the worst of it.** `GET /files/` and `GET /files/search` passed
`user_id=None` for an admin when `BYPASS_ADMIN_ACCESS_CONTROL` was set — which **defaults true** —
so an admin was handed *every user's file list*. No id-guessing was needed; the ids were simply
provided, and each could then be read.

That flag is **left untouched elsewhere**, and the distinction is the point: for knowledge bases,
models, prompts and skills it gates curated **workspace content**, where admin visibility is
intended. An uploaded document is **user data**. Only the `files.py` uses were removed.

**One reached through a different router.** `POST /api/v1/retrieval/process/file` had the same
admin lookup. Because the caller chooses `collection_name`, that allowed embedding another user's
document into a collection they control and then querying it — a read path via RAG rather than
via the file API.

**`DELETE /api/v1/files/all` deleted.** It called `Files.delete_all_files()`,
`Storage.delete_all_files()` **and** `ASYNC_VECTOR_DB_CLIENT.reset()` — every user's uploads plus
the entire vector database, from one admin request, with nothing scoped to a tenant. Its "Reset
Upload Directory" button in Admin → Settings → Documents went with it. "Reset Vector
Storage/Knowledge" is untouched.

**What deliberately stays.** `GET /files/{id}/content/html` checks the **file owner's** role and
serves inline only when an admin uploaded it. That is an XSS guard against user-supplied HTML,
not an access bypass, and removing it would be a regression.

**This is the route behind the VAPT tester's image finding.** During the August 2026 test, an
account holding the admin role in its own tenant retrieved **other users' generated images**. The
path was almost certainly this one: `routers/images.py` calls `upload_file_handler(..., user=user)`,
so a generated image is a **File row owned by the generating user** and is served by
`GET /api/v1/files/{id}/content` — which carried the admin bypass. **Uploaded documents were
reachable the same way**, through the identical check; the tester was unsure whether they were,
and they were.

This was initially attributed to the `/cache/{path}` route (3.4). That was wrong, and the
distinction matters for anyone re-testing: `/cache` needs no admin role and crosses tenants, while
this needed the admin role and stopped at the tenant boundary. Both are closed, but they are
different findings with different blast radii.

**Provenance, because it affects who should review this.** The deletion manifest flagged
`DELETE /files/all` and a separate config-write defect at `files.py:380-382`. The nine admin
bypasses and the `retrieval.py` one were **not** in any report — they were found while closing the
equivalent paths in `chats.py`. So the tester demonstrated the *symptom* in August; the
*mechanism* was not written down anywhere until now.

### 3.4 Removed — the unauthenticated-by-tenant cache route

| | |
|---|---|
| **What** | `GET /cache/{path}` |
| **Class** | Removed |
| **Mechanism** | route deleted; nothing migrated, because nothing referenced it |

**Justification.** Security review finding **H5b**, rated High. The route required only
`get_verified_user` and performed **no ownership check and no tenant check**, so any logged-in
user who learned or guessed a path read that artifact — generated images, TTS audio, tool
output — **across users and across tenants**.

The cross-tenant part had two independent causes, and both are worth recording: `CACHE_DIR` is a
single filesystem path shared by every tenant on the pod, and `/cache` was on the tenant
middleware's `_SYSTEM_PATH_PREFIXES` bypass list, so tenant resolution never ran for it. That
entry has been removed too.

**Not the route behind the VAPT tester's image finding**, despite the obvious similarity — that
was the `files.py` admin bypass in 3.3, corrected below. This route is a *separate* and in one
respect broader exposure: it needed **no admin role at all** and reached **across tenants**.
Nobody is known to have exercised it; it was found by review, not by test.

**Why deletion needed no migration.** The review offered two fixes and preferred re-serving
artifacts through `/api/v1/files/{id}`. On inspection the route was already **unreferenced**:
generated images go through `upload_file_handler()` and become File rows with ownership; TTS
audio is returned directly by `/api/v1/audio/speech` via its own `FileResponse`; and nothing in
the backend or the frontend constructs a `/cache/` URL. `IMAGE_CACHE_DIR` was declared and its
directory created on every import but never written to. Deleting the mount removed the exposure
without moving anything.

**Sequencing note.** The review's preferred fix routed cache artifacts through `files.py` — which
at the time had nine admin bypasses of its own (§3.3). Doing that first would have moved the
problem rather than fixed it. §3.3 landed first for that reason.

**Residual.** A chat predating the current image pipeline could in principle hold a `/cache/...`
URL that now 404s. `CHAT_RETENTION_DAYS` is 30, so such history has long since been purged.

### 3.5 Removed — Channels, and the only unauthenticated write endpoint

| | |
|---|---|
| **What** | Slack-style Channels — 28 endpoints, the frontend, and four model-callable tools |
| **Class** | Removed |
| **Mechanism** | `routers/channels.py` deleted; the `channel` tables and `models/channels.py` retained |

**Justification.** Channels is a feature schat does not offer. It also contained
`POST /api/v1/channels/webhooks/{id}/{token}` — documented in its own docstring as requiring no
authentication, and **the only unauthenticated write endpoint in the application**. Its bearer
token travelled in the URL path, where proxy and service-mesh access logs record it.

That endpoint was gated only by `ENABLE_CHANNELS`, which is `PersistentConfig` — so its default
of `False` protected a fresh database only, a stored value outranked it, and the process-global
admin config endpoint could set it with any admin token, which under multi-tenancy means any
departmental admin. **Deleting the router removes that possibility rather than resting on a
flag** (§2 explains why that distinction keeps recurring).

Four **model-callable** tools went with it — `search_channels`, `search_channel_messages`,
`view_channel_message`, `view_channel_thread`. All were read-only and already gated on
`ENABLE_CHANNELS`, so removing them changes nothing in a deployment with channels off, but they
were live surface a model could invoke.

**What was deliberately kept.** `models/channels.py` and its tables: `routers/files.py`,
`socket/main.py` and `utils/access_control/files.py` import it for **file access-control
checks**, so deleting it would alter an authorisation path for no security gain. Six shared UI
components also had to be relocated rather than deleted — a profile hovercard and a rich message
input that Notes, the workspace member selector and the admin user list all depend on. They now
live under `components/common/`.

### 3.6 Removed — Evaluations, and with it Good/Bad message ratings

| | |
|---|---|
| **What** | Arena leaderboard, feedback store, and the thumbs up/down rating UI — 15 endpoints |
| **Class** | Removed |
| **Mechanism** | `routers/evaluations.py` deleted, with its admin pages and API client |

**Justification.** There is no evaluation programme, ratings were already disabled
(`ENABLE_MESSAGE_RATING=false`) and arena models switched off, so the leaderboard and feedback
screens were permanently dataless. The router also carried a bulk feedback export and a
delete-all.

**⚠ Note the reclassification.** Good/Bad ratings were previously recorded as *deferred* —
hidden by a flag, restorable by flipping it. The three endpoints the thumbs called
(`POST /evaluations/feedback` and the two `feedback/{id}` routes) lived in this router, so
deleting it **moves message rating from deferred to removed**. Restoring ratings now means
restoring code, not changing configuration. That is a deliberate consequence, not an oversight.

### 3.7 Removed — one admin editing another admin

| | |
|---|---|
| **What** | `POST /api/v1/users/{user_id}/update` and the user-edit UI; admin-on-admin deletion |
| **Class** | Removed / gated |
| **Mechanism** | endpoint deleted; a 403 added to `DELETE /{user_id}` when the target is an admin |

**Justification.** Both actions protected only the **first account ever created**. Any admin could
therefore edit or delete any *other* admin, including changing their role — and under
multi-tenancy `admin` is a per-tenant IAM role, so that meant every departmental admin.

**Why the edit endpoint was deleted rather than restricted.** Every field on that form belonged
to IAM, so none of the edits actually held:

- **`role`** is re-read from IAM on every request, so a local change is silently overwritten the
  moment that user next does anything. It appears to work, then reverts.
- **`email`** is the IAM entitlement key. Changing it locally breaks the mapping between the
  schat row and the IAM membership, so the user is **re-provisioned as a new account** on their
  next request, orphaning the original row.
- **`name`** is synced from the IAM identity at provisioning.

**This matters for how the finding is described.** The instinct is to call it privilege
escalation, but the role field is self-healing — that is the *weakest* part of it. The real damage
is **account integrity**: the email change is persistent, destructive and not self-healing, and
admin-on-admin deletion is permanent. Framing it as escalation invites the (correct, and
irrelevant) rebuttal that IAM overwrites the role anyway.

With the endpoint gone, "an admin cannot promote another admin" holds **by construction** — no
code path, no rule to enforce, nothing for a future change to get wrong — and three controls that
never worked are removed with it.

**Residual.** The user list stays visible and admins may still delete a non-admin. The delete
button was already hidden for admin targets in the UI; the 403 makes that a real check rather
than an assumption, since UI hiding is not a boundary (§3.6).

### 3.8 Deferred — features hidden for phase 1

Hidden rather than removed because each is a candidate for a later phase. Code is retained
behind a guard or flag; nothing is deleted.

Notes, Memory/Personalisation, Chat Folders, Code Interpreter, Chat Archive, Temporary Chat,
Voice (STT/TTS/Call), Calendar, Automations, Playground, Workspace → Models / Tools / Skills /
Prompts, Evaluations, and the composer integrations toolbar.

**Justification varies by feature** — data sovereignty (Memory), no evaluation programme
(Evaluations), arbitrary-code class (Workspace Tools/Skills), redundancy with retention limits
(Archive), or simply not in phase 1 scope. The per-feature reasoning and the exact hide site are
recorded in `CLAUDE.md`.

**Residual risk — the important qualification.** Hiding user interface is **not a security
boundary**. Where a hidden feature still has a live endpoint, that endpoint remains callable by
anyone who knows the URL. Hiding is adequate only where either the backend is genuinely disabled
(the `PersistentConfig` flags do disable server-side) or there is no backend capability at all
(purely visual surfaces). It is *not* adequate as a control against a determined caller, and is
not claimed as one.

**Reversal.** Each is re-enabled by its flag or by unwrapping its guard; `CLAUDE.md` records the
specific lever per feature.

### 3.9 Hidden but still reachable — the honest inventory

3.8 states that hiding user interface is not a security boundary. This section is the evidence
for that claim, because "not a boundary" is easy to write and easy to skim past. It answers one
question per feature: **with the UI hidden, can the endpoint still be called?**

Each row below was checked against the code, not against the hide-site list.

| Hidden feature | Flag enforced server-side? | Endpoint reachable |
|---|---|---|
| Memory / Personalisation | ✅ `memories.py` — 7 gates | no |
| Chat Folders | ✅ `folders.py` | no |
| Calendar | ✅ `calendar.py`, `automations.py` | no |
| Automations | ✅ `automations.py` | no |
| Chat Archive | ✅ `chats.py` | no |
| Notes | ✅ **fixed** — router-level gate added | no |
| Voice (STT/TTS) | ✅ **fixed** — router-level gate added | no |
| Code Interpreter | ❌ `ENABLE_CODE_INTERPRETER` not enforced… | …but `/utils/code/execute` is gated by `ENABLE_CODE_EXECUTION`, which **is** enforced and defaults off |
| Temporary Chat | ❌ not enforced | n/a — a temporary chat is simply one never persisted; there is no endpoint |
| Attach Webpage | n/a | **endpoint deleted** — see below |
| Import Chats | n/a | **endpoint deleted** — see below |

**Three findings worth stating plainly.**

**1. `ENABLE_NOTES` does not disable Notes.** `CLAUDE.md` groups it with the `PersistentConfig`
flags and says those "disable the feature server-side". For Notes that is **not true** — the
router is mounted and none of its nine routes consult the flag. Anyone with a session can create,
read and update notes today. This is the single largest gap between what the hide-ledger claims
and what the code does.

**2. `ENABLE_VOICE` hides the UI only.** The audio routes stay mounted and callable, and they
**write into the cache directory** — which is how a deferred feature came to populate the
artifacts that 3.4 exposed cross-tenant. A hidden feature is not an inert one.

Note the classification: Voice is **deferred, not out of scope**. A speech and translation vendor
was seen at a workshop and remains under consideration, so this may return in a later phase. That
makes a server-side gate the right fix rather than deletion — the code should stay, but the
endpoints should refuse while the feature is off.

**3. Attach Webpage is the SSRF surface.** Its button is hidden, but
`POST /api/v1/retrieval/process/web` is live and takes a user-supplied URL. Any answer given to a
questionnaire about server-side URL fetching must account for it, regardless of the UI state. The
controls on that path are documented in §4.

**All four gaps this inventory found are now closed**, by the cheapest mechanism that fits each:

- **Notes** and **Voice** received router-level dependencies returning 404 while their flag is
  off. Gated rather than deleted because both are deferred: Notes may yet find a use, and Voice is
  under active vendor evaluation. Router-level so a route added later inherits the gate instead of
  being forgotten. Verified: `GET /api/v1/notes/` and `GET /api/v1/audio/config` both return 404.
- **Attach Webpage** — `POST /process/web` and `/process/youtube` deleted (one handler served
  both). Both entry points were hidden, and URL reading in chat is unaffected: the model's
  built-in `fetch_url` tool calls `get_content_from_url()` directly and never used the endpoint.
  `/process/web/search` is a different thing and remains.
- **Import Chats** — `POST /chats/import` deleted. It bypassed `MAX_CHATS_PER_USER`, which is
  enforced only at `/chats/new` and on the completion path. Deleted rather than cap-enforced
  because nothing imports *from* schat now that bulk export is hidden. Exporting your **own**
  chats is untouched — that is the part with a data-portability dimension under PDPA.

**Why this section still matters after the fixes.** It is the difference between "we hid it" and
"it cannot be reached", and reviewers are entitled to ask which applies to each feature. The
answer is now "cannot be reached" for every row — but the section stays, because the next feature
hidden behind an `{#if false}` will need the same question asked of it.

**The general lesson, recorded because it recurred three times.** A `PersistentConfig` flag does
not disable a feature by existing; a router has to consult it. `ENABLE_NOTES` and `ENABLE_VOICE`
both reached the browser and hid the UI while every endpoint answered normally. Voice compounded
it: `AUDIO_STT_ENGINE` defaults to `''`, and the empty case is the **local faster-whisper** path,
so an unconfigured deferred feature was downloading a model and running inference in the pod —
and writing artifacts into the directory §3.4 exposed cross-tenant. Unconfigured is not the same
as inert.

### 3.10 Removed — the runtime configuration surface

| | |
|---|---|
| **What** | 35 admin endpoints that read or wrote process-global configuration, plus four destructive maintenance routes |
| **Class** | Removed |
| **Mechanism** | routes deleted; configuration seeded in the chart |

**Justification.** Two reasons, and the second is the stronger one.

Configuration now comes from the chart — the values are pinned in `values.staging.yaml`, derived
from a capture of the running system and verified against real code defaults
(`docs/item7-seed-block.md`). So these endpoints have nothing left to own.

More importantly, **`app.state.config` is a single process-global instance** with no tenant
component and no TTL. A write by one tenant's admin changed behaviour for **every tenant on that
pod**. Under multi-tenancy `admin` is a per-tenant IAM role, so that was reachable by any
departmental admin. Deleting the write path is a cross-tenant integrity fix, not tidiness.

Note that `ENABLE_PERSISTENT_CONFIG=false` alone would **not** have been enough: it stops a stored
value being read at boot, but a write still mutates `app.state.config` in memory for the rest of
the process lifetime. Only removing the route stops that.

**What went:** the whole admin surface of `configs.py` (connections, tool servers, terminal
servers and policy, code execution, models, suggestions, banners POST, OAuth client
registration); the config endpoints of `openai.py`, `retrieval.py`, `images.py`, `audio.py` and
`tasks.py`; and four destructive routes — `retrieval/delete`, `retrieval/reset/db`,
`retrieval/reset/uploads`, `models/delete/all` — each of which wiped a collection, the vector
database, or every uploaded file from one request, unscoped to a tenant.

**What stayed:** `GET /configs/banners` and `GET /configs/models/defaults` (both
`get_verified_user`, read-only, used by the app itself), `GET /models/base`, `POST /models/sync`,
`GET /tasks/config`, and the retrieval processing endpoints.

**A side effect worth recording: this made the H4 masking fix redundant.**
`utils/secret_masking.py` was written so admin config endpoints would stop returning stored
credentials in cleartext. With those endpoints deleted, it has **no callers left**. It is kept —
along with its 17 unit tests — because it is the right tool the moment any endpoint returns stored
config again, and because those tests document a subtle contract. But the finding it addressed is
now closed by construction rather than by masking.

**Terminals, completed.** 3.11 noted that pinning `TERMINAL_SERVER_CONNECTIONS` closed only the
chart-level path, because the value is `PersistentConfig` and the endpoint that writes it still
existed. That endpoint is now deleted, so the pin is a complete control.

**The frontend went with it** (deletion manifest, Part 3). Eleven Admin Settings tab components
were deleted — General, Connections, Documents, Images, Integrations, Web Search, Code Execution,
Audio, Database, Interface, and the model-config modal — along with `utils/connections.ts` and 17
of the 20 clients in `src/lib/apis/configs/index.ts`. `HIDDEN_ADMIN_SETTINGS_TAB_IDS` is now
**empty**, because there is nothing left to hide: every tab it listed configured settings at
runtime, and those endpoints are gone. Three clients stayed — `getBanners` and
`getModelsDefaults`, which back the two surviving read-only routes, and
`getOAuthClientAuthorizationUrl`, which only builds a URL and is used by the live composer.

**Admin Settings is now a single tab: Models.** It survives because `POST /api/v1/models/import`
is still the only way to seed presets into a tenant, and stays so until Item 9 makes model
definitions code. Its **Settings** button is gone with the rest; Import/Export remain.

Two components needed surgery rather than deletion — `AddToolServerModal.svelte` and
`AddTerminalServerModal.svelte` are shared with the **user-facing** Settings → Integrations tab,
which is in scope.

Result: **301 routes** (from 482 at the start of the review), against the deletion manifest's
target of ~330.

### 3.11 Retained, gated — terminals

| | |
|---|---|
| **Class** | Retained, gated |
| **Mechanism** | `TERMINAL_SERVER_CONNECTIONS` pinned to `[]` in the chart template |

**Justification.** The feature has real intended use for developers and general staff, so it is
kept. It is currently unused in every environment, and three findings sit in its code paths —
an iframe sandbox escape, a WebSocket that skipped the sign-out revocation check, and a proxy
that forwarded the user's session cookies upstream. All three are now fixed, and the pin means
enabling the feature requires a template change a reviewer sees rather than a values edit.

**Residual risk.** The pin closes the chart-level path only. `TERMINAL_SERVER_CONNECTIONS` is
`PersistentConfig`, so a stored value outranks the environment, and the configuration endpoint
that writes it still exists. It becomes a complete control once that endpoint is deleted.

### 3.12 Fixed — every feature gate now fails closed

| | |
|---|---|
| **What** | Eight frontend gates that read a **missing** feature flag as permission |
| **Class** | Fixed |
| **Mechanism** | `?? true` → `?? false`, `!== false` → `=== true` |

**Justification.** This is the standing principle of the whole review — a hidden button is not a
security boundary — applied to its own enforcement layer. A gate written `?? true` renders the
feature whenever the flag is *absent*, which is exactly what happens when a flag is not emitted at
all. Two independent bugs had to line up for this to matter, and they did: the backend stopped
sending the flags, and the frontend read their absence as a yes.

The backend half is already fixed — `/api/config` no longer resolves a user, and the authenticated
flags moved to `GET /api/v1/auths/` (`utils/app_config.py`), which runs in tenant context. So for
a signed-in user these gates now receive real values and the `??` never fires. Flipping them is
defence for the window before the session resolves, and against the same class recurring.

**Sites:** `Settings/Account.svelte` ×3 (`enable_api_keys`), `Messages/CodeBlock.svelte`
(`enable_code_execution`), `layout/Sidebar.svelte` ×2 (`enable_user_status`),
`chat/FileNav.svelte` ×2 (`terminal`).

**One of the eight was not cosmetic.** `CodeBlock.svelte` gates the **Run** button on Python code
blocks, and that button executes in a browser Pyodide worker — no backend call, therefore no
backend gate. The UI check was the *only* check. So code execution was live for every user while
`ENABLE_CODE_EXECUTION` was `False`. The other seven were UI-truthfulness: the API-key form
rendered but the backend refused the key (`utils/auth.py:485`), and terminals is unconfigured.

**Deliberately not flipped:** `routes/auth/+page.svelte` reads `features.auth !== false`. Here
fail-open *is* fail-secure — absence means "assume authentication is on", which shows the login
form. Rewriting it to `=== true` would make a missing flag skip authentication, and would lock
every user out if the flag were ever dropped. Fail-closed is a direction, not a syntax rule.

### 3.13 Removed — the SQLCipher keying path

| | |
|---|---|
| **What** | The `sqlite+sqlcipher://` branch in `internal/db.py` and `migrations/env.py` |
| **Class** | Removed |
| **Mechanism** | branch deleted; the URL scheme is now rejected with a clear error |

**Justification.** Both sites formatted `DATABASE_PASSWORD` directly into a SQLite keying
statement with an f-string. Neither was reachable — the branch is gated on a `sqlite+sqlcipher://`
URL and schat runs Postgres for the control plane and every tenant — and the interpolated value is
operator-supplied, never user-supplied, so it was not injection in the attacker sense even when
reached.

It was deleted rather than documented for a reason worth stating: **a static scanner flags the
pattern regardless of reachability**, so leaving it in means re-arguing "yes, we know, it is dead"
at every assessment. Removal costs nothing — SQLCipher was never a schat feature and `sqlcipher3`
is not in `pyproject.toml`. For the same reason the explanatory comments avoid quoting the literal
statement, or they would match the same scanner rule.

**The URL is rejected, not ignored.** `'sqlite' in URL` also matches `sqlite+sqlcipher://`, so
without an explicit guard an encrypted database would fall through to the plain-SQLite branch —
failing confusingly, or silently creating a new **unencrypted** file at a path that looks correct.
The async engine already rejected the scheme (`_make_async_url`); the sync path now matches it.

---

## 4. Guardrails — state the limits plainly

The guardrails filter redacts structured identifiers (Malaysian NRIC, email, phone,
Luhn-validated card numbers, credential patterns) from user messages before they reach the
external model provider, and scrubs credentials from replies. It now lives in code rather than
a database row, so it cannot be disabled or re-configured through the API — a change requires a
reviewed commit and a deployment.

**What it is not.** This is a **structured-identifier masker, not a PII detector.** It cannot
see names, addresses, or a description of a person. Anything beyond fixed formats would require
a model-based classifier, with its own latency, cost and governance.

Three limits that must be stated rather than implied:

1. **It fails open.** On an internal error the message passes through unredacted. This is a
   deliberate trade — a guardrail that fails closed becomes an outage, and an outage gets the
   guardrail switched off — but it makes redaction **best-effort, not a guarantee**.
2. **It protects the provider hop, not storage.** The chat record is written by a separate
   request carrying the browser's own unredacted copy, so personal data typed by a user is
   retained in the database even when the provider received a redacted version.
3. **Coverage is incomplete and measured.** The NRIC pattern matches one of four common written
   forms; the phone pattern matches mobiles but no landlines. Both are being extended.

**The stated limits are now tested, and the tests are the record.** Until recently nothing
exercised this filter, in a repository whose CI runs no tests at all — so the control was
asserted rather than demonstrated. `backend/open_webui/test/test_guardrails.py` now pins its
behaviour: each redaction class, the multimodal path, the scope rules, both injection tiers,
and the fail-open policy in point 1 above.

It deliberately pins the **limits** as well as the coverage — that the unhyphenated NRIC form is
*not* matched, that landlines are *not* matched, and that the outlet does *not* redact identity
data. Those assertions exist so closing a gap is a deliberate act that updates a test, rather
than a silent change in either direction. The suite was mutation-checked: four independent
defects introduced into the filter (a broken NRIC pattern, a removed Luhn check, an over-broad
outlet, and a fail-*closed* handler) were each caught.

This does not widen what the guardrail covers. It means a future change cannot narrow it
unnoticed.

**Open, and owned by the data-protection function, not engineering:** whether best-effort,
provider-egress-only redaction is acceptable for phase 1; what happens to personal data already
stored and in backups (leave, purge, or retroactively mask); and whether any healthcare business
unit is in scope, which would raise the data class to sensitive personal data and make a
regex-based control inadequate.

---

## 5. Attribution requirement

schat is a fork of Open WebUI. The upstream licence requires the Open WebUI branding to be
retained above a user threshold absent an enterprise licence or written permission. Settings →
About therefore displays **"Powered by Open WebUI v{version}"**, and this line must not be
removed as part of any branding work. Confirming the position for the intended user count is a
legal and procurement question, not an engineering one, and remains open.

---

## 6. Open items with owners

| Item | Owner | Blocking |
|---|---|---|
| Personal data already stored, and in backups — leave, purge, or mask | data protection | the ISMS wording on redaction |
| Best-effort redaction acceptable for phase 1? | data protection | §4 claim |
| Healthcare business unit in scope? | business | whether a regex control suffices at all |
| IAM "BU admin" intended to carry schat administrative rights — confirm in writing | IAM owner | reads as signed-off design rather than a finding |
| Admin visibility of per-user chat *metadata* — intended? | product / data protection | §3.2 residual |
| Enterprise licence position for the intended user count | legal / procurement | §5 |
| **Notes endpoints are live while the feature is "disabled"** — 9 routes, no flag check | engineering | §3.9; decide gate-or-delete |
| Voice/audio endpoints reachable with `ENABLE_VOICE=false` | engineering | §3.9 |
| `POST /retrieval/process/web` live while Attach Webpage is hidden — the SSRF surface | engineering / security | §3.9, §4 |
| `POST /chats/import` live while the button is hidden; bypasses the 30-chat cap | product | §3.9 |
