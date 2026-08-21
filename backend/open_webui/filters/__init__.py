"""Sunway: built-in filter registry (hardening plan Item 8).

Filters used to exist only as rows in the `function` table, loaded by `exec()`-ing
their source out of the database (utils/plugin.py). A built-in filter is an ordinary
Python module in this package instead: it ships with the image, applies to every tenant
without a per-tenant import step, and cannot be toggled off or re-valved through the
admin API — changing it takes a reviewed commit and a deploy.

`utils/filter.py` consults this registry BEFORE it queries the database, so a built-in
id never reaches the DB-backed path. Once the Functions router is deleted (Item 2) this
becomes the only path, and utils/plugin.py — with its two `exec()` calls — goes with it.

Adding one: drop a module here exposing a `Filter` class (optionally with a nested
`Valves` BaseModel, plus `toggle` / `file_handler` attributes, exactly as the DB-backed
contract required), then register it below. Nothing else changes.
"""

import logging

from open_webui.filters import guardrails

log = logging.getLogger(__name__)

# id -> the module's Filter CLASS. Ids must match what the DB rows used, so that model
# rows carrying `meta.filterIds` and any stored `enabled_filter_ids` keep resolving.
BUILTIN_FILTER_CLASSES = {
    'schat_guardrails': guardrails.Filter,
}

# One instance per id, created lazily and reused — mirroring how the plugin loader
# cached `request.app.state.FUNCTIONS[function_id]`. Instances hold compiled regexes,
# so rebuilding one per request would throw away the filter's stated performance
# guarantee ("every pattern is compiled ONCE at module import").
_INSTANCES: dict = {}


def is_builtin_filter(filter_id: str) -> bool:
    return filter_id in BUILTIN_FILTER_CLASSES


def get_builtin_filter_ids() -> list[str]:
    return list(BUILTIN_FILTER_CLASSES.keys())


def get_builtin_filter(filter_id: str):
    """Return the shared instance for *filter_id*, or None if it is not built in.

    Returns an INSTANCE, not the module: utils/plugin.py's loader returned
    `module.Filter()`, and utils/filter.py reads `inlet` / `outlet` / `valves` /
    `Valves` / `toggle` / `file_handler` off that instance. Matching the shape exactly
    is what makes this a drop-in.
    """
    if filter_id not in BUILTIN_FILTER_CLASSES:
        return None
    if filter_id not in _INSTANCES:
        _INSTANCES[filter_id] = BUILTIN_FILTER_CLASSES[filter_id]()
        log.info('Loaded built-in filter: %s', filter_id)
    return _INSTANCES[filter_id]


def get_builtin_filter_valves(filter_id: str) -> dict:
    """Valve overrides for a built-in filter.

    ⚠️ MIGRATION STATE — returns {} today, i.e. the defaults declared on the filter's
    own `Valves` model. That is deliberate for a migration whose contract is "no
    behaviour change", but it is only true if the live DB valves were also defaults.

    THEY HAVE NOT BEEN VERIFIED. The `function` row's created_at and updated_at differ
    by three days, so something was edited through the API, and the export used for this
    migration carries `content` but NOT the valve values — they live in a separate
    column that the export does not include. Before cutover, read them:

        SELECT valves FROM function WHERE id = 'schat_guardrails';

    and diff against the defaults. If they differ, the difference must be reproduced
    here or the migration silently changes behaviour — and the plausible edits
    (enable_input_pii=false, a populated exempt_user_ids) all WEAKEN the control, so a
    silent revert to defaults would fail safe rather than open. Worth knowing either way.

    Next step (Item 8, follow-up commit): source these from the ConfigMap so they are
    reviewable configuration rather than defaults frozen in code.
    """
    return {}
