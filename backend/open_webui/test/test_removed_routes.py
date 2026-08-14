"""Sunway: every route removed by the hardening plan must stay removed.

WHY THIS EXISTS. Part 4 of the deletion manifest asks for exactly this, and its reasoning is
the point: *"the manifest is only as good as its enforcement."* Roughly ninety routes were
deleted across a dozen commits. Nothing else in this repository would notice if one came back —
CI runs no tests, and an upstream merge that restores a router file or re-adds a decorator would
land silently. Several of these endpoints returned other users' message content, stored
credentials, or ran Python from a database row, so a silent restoration is not a cosmetic
regression.

HOW IT WORKS, and why it is not an integration test. These assertions are made by parsing the
router sources, not by importing the application. Importing `open_webui.main` pulls in the
embedding stack and connects to a database, which takes minutes and needs infrastructure — a
test that expensive does not get run, and a test that does not get run enforces nothing. Parsing
is sub-second and needs neither.

The trade-off, stated plainly: this catches a route being re-declared in a router file, which is
what an upstream merge or a well-meaning revert actually does. It would not catch a route
re-introduced by some other mechanism (a new router file under a different name, a dynamically
mounted sub-application). For that, run the route inventory in
`reports/security/route_inventory.py` and diff the counts.

WHEN THIS TEST FAILS, the fix is almost never to edit the list. It means a removed capability is
back. Check `docs/rollout-scope.md` for why it went, and delete it again. Only amend the list if
a capability is being **deliberately** reinstated — in which case update the ledger in the same
commit.
"""

from __future__ import annotations

import ast
import re

import pytest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
ROUTERS = BACKEND / 'open_webui' / 'routers'

# Matches @router.get('/path') and @app.get('/path'), including a newline after the paren.
_DECORATOR = re.compile(r'@(?:router|app)\.(get|post|put|patch|delete)\(\s*[\'"]([^\'"]*)[\'"]')


# ── router files deleted outright ────────────────────────────────────────────
#
# Deleting the file removes every route in it, so these need no per-route entries.
# Route counts at deletion are recorded for the reviewer's benefit.
DELETED_MODULES = {
    'open_webui/routers/functions.py': 'Functions authoring — 17 routes; Python exec()ed from a DB row',
    'open_webui/routers/channels.py': 'Channels — 28 routes, incl. the only unauthenticated write endpoint',
    'open_webui/routers/evaluations.py': 'Evaluations — 15 routes; arena leaderboard and the feedback store',
    'open_webui/functions.py': 'pipe-model execution',
    'open_webui/utils/actions.py': 'custom action execution',
    'open_webui/utils/plugin.py': 'the exec() loader, and the startup pip-install-from-DB routine',
}


# ── individual routes removed from surviving files ───────────────────────────
#
# Keyed by router module stem; each entry is (METHOD, path-as-declared). Paths are the
# router-relative ones in the decorator, so no mount-prefix bookkeeping is needed.
REMOVED_ROUTES: dict[str, list[tuple[str, str]]] = {
    # returned message content, chat previews and conversation tags to any admin
    'analytics': [
        ('GET', '/messages'),
        ('GET', '/models/{model_id:path}/chats'),
        ('GET', '/models/{model_id:path}/overview'),
    ],
    # one admin reading another user's chats, and a dump of every message of every user
    'chats': [
        ('GET', '/all/db'),
        ('GET', '/list/user/{user_id}'),
    ],
    # both returned the entire config row UNMASKED — every stored credential in one response
    'configs': [
        ('GET', '/export'),
        ('POST', '/import'),
    ],
    # ran a `function` row of type `action` through exec()
    'main': [
        ('POST', '/api/chat/actions/{action_id}'),
    ],
    # external run-arbitrary-Python plugin server: upload, add, delete, valve editing
    'pipelines': [
        ('DELETE', '/delete'),
        ('GET', '/'),
        ('GET', '/list'),
        ('GET', '/{pipeline_id}/valves'),
        ('GET', '/{pipeline_id}/valves/spec'),
        ('POST', '/add'),
        ('POST', '/upload'),
        ('POST', '/{pipeline_id}/valves/update'),
    ],
    # tool AUTHORING. /create needed only the workspace.tools permission, not admin.
    # GET '/' and GET '/list' deliberately survive — they list tool SERVERS, which execute
    # nothing inside schat and are how the Sdeck MCP server reaches a model.
    'tools': [
        ('DELETE', '/id/{id}/delete'),
        ('GET', '/export'),
        ('GET', '/id/{id}'),
        ('GET', '/id/{id}/valves'),
        ('GET', '/id/{id}/valves/spec'),
        ('GET', '/id/{id}/valves/user'),
        ('GET', '/id/{id}/valves/user/spec'),
        ('POST', '/create'),
        ('POST', '/id/{id}/access/update'),
        ('POST', '/id/{id}/update'),
        ('POST', '/id/{id}/valves/update'),
        ('POST', '/id/{id}/valves/user/update'),
        ('POST', '/load/url'),
    ],
    # editing another admin's role, email or name — see docs/rollout-scope.md 3.5
    'users': [
        ('POST', '/{user_id}/update'),
    ],
    # streamed the raw SQLite database file
    'utils': [
        ('GET', '/db/download'),
    ],
}


def _declared_routes(path: Path) -> set[tuple[str, str]]:
    return {(m.group(1).upper(), m.group(2)) for m in _DECORATOR.finditer(path.read_text(encoding='utf-8'))}


def _source_for(stem: str) -> Path:
    return BACKEND / 'open_webui' / 'main.py' if stem == 'main' else ROUTERS / f'{stem}.py'


@pytest.mark.parametrize('rel_path', sorted(DELETED_MODULES), ids=lambda p: p.split('/')[-1])
def test_deleted_module_is_absent(rel_path):
    """A module deleted by the hardening plan must not reappear."""
    assert not (BACKEND / rel_path).exists(), (
        f'{rel_path} is back. It was deleted deliberately: {DELETED_MODULES[rel_path]}. '
        f'See docs/rollout-scope.md before restoring it.'
    )


@pytest.mark.parametrize(
    'stem,method,route',
    [(stem, m, r) for stem, routes in sorted(REMOVED_ROUTES.items()) for m, r in routes],
    ids=lambda v: str(v).replace('/', '_'),
)
def test_removed_route_is_absent(stem, method, route):
    """A route deleted by the hardening plan must not be re-declared."""
    source = _source_for(stem)
    assert source.exists(), f'{source} is missing; this test needs updating'
    assert (method, route) not in _declared_routes(source), (
        f'{method} {route} was re-declared in {source.name}. It was removed by the hardening '
        f'plan — see docs/rollout-scope.md for why. Do not simply delete this assertion.'
    )


def test_surviving_tool_listing_routes_are_intact():
    """The inverse guard: tool SERVER listing must not be deleted by over-zealous cleanup.

    GET '/' and GET '/list' are how the Sdeck MCP server reaches a model. Removing them would
    break slide generation, which no other test here would notice.
    """
    declared = _declared_routes(ROUTERS / 'tools.py')
    for route in ('/', '/list'):
        assert ('GET', route) in declared, (
            f'GET {route} is missing from tools.py. Tool SERVERS are in scope -- only tool '
            f'AUTHORING was removed. This is the Sdeck MCP path.'
        )


def test_no_python_exec_in_backend():
    """Part 4 of the deletion manifest: no Python `exec()` anywhere in the backend.

    Checked with the AST rather than by grepping, which matters here. A textual search matches
    the Sunway comments and docstrings that record what was removed, and it matches Valkey's
    `Batch.exec()` — a Redis pipeline method, nothing to do with Python's builtin. Looking for a
    Call node whose callee is the bare name `exec` excludes all three structurally: comments and
    docstrings are not code, and an attribute call is not a Name.
    """
    offenders = []
    for py in sorted((BACKEND / 'open_webui').rglob('*.py')):
        if 'test' in py.parts:
            continue
        try:
            tree = ast.parse(py.read_text(encoding='utf-8'), filename=str(py))
        except SyntaxError as e:  # a file that will not parse is its own problem
            pytest.fail(f'{py.relative_to(BACKEND)} does not parse: {e}')
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'exec':
                offenders.append(f'{py.relative_to(BACKEND)}:{node.lineno}')
    assert not offenders, (
        'Python exec() reappeared in the backend — the whole point of hardening plan Item 2 was '
        'that database content can no longer become running code:\n  ' + '\n  '.join(offenders)
    )
