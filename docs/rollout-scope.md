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
| **What** | `/chats/list/user/{id}`, `/chats/{id}` admin fallback, `/chats/all/db`, and the three content-bearing analytics endpoints |
| **Class** | Removed / gated |
| **Mechanism** | `ENABLE_ADMIN_CHAT_ACCESS` and `ENABLE_ADMIN_EXPORT`, both **plain env**, both defaulting `False` |

**Justification.** Upstream allows any admin to read any user's chats. Under multi-tenancy that
means every BU admin, for every user in their tenant, through the browser.

The analytics endpoints were the subtle case: `/analytics/messages` returns full message text,
`/models/{id}/chats` returns the first 200 characters of every chat's opening message, and
`/models/{id}/overview` returns conversation tags. All three were gated on `get_admin_user`
alone, so disabling admin chat access closed the obvious paths while these stayed open — and
the second was reachable through the UI, two clicks from the Analytics dashboard.

**Update — the three analytics endpoints are now deleted, not gated.** They were flag-gated
first, to keep an admin support path reversible. That reversibility only had value while a UI
existed to reverse to; the drill-down modal is gone, so the endpoints guarded nothing any caller
used. `ENABLE_ADMIN_CHAT_ACCESS` still governs `/api/v1/chats/*`, where the genuine
privacy-versus-support policy question lives.

**Residual risk.** The five surviving analytics endpoints return counts and totals only. But an
admin still sees *metadata* — per-user message counts, token counts, activity. That is a
deliberate retention for capacity and cost management, and should be confirmed as intended
rather than assumed.

**⚠ Not addressed by this row.** These controls stop *future* reads. Message content already
stored — including any personal data — is untouched, as are database backups. See §4.

### 3.3 Removed — Channels, and the only unauthenticated write endpoint

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

### 3.4 Removed — Evaluations, and with it Good/Bad message ratings

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

### 3.5 Deferred — features hidden for phase 1

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

### 3.6 Retained, gated — terminals

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
