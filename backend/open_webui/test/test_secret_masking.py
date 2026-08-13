"""Admin-config endpoints must never return a stored credential.

A VAPT against staging lifted the shared LiteLLM token out of ``GET /openai/config``,
which returned ``OPENAI_API_KEYS`` in cleartext. Three more routers had the same shape.
These tests are the regression net for all four.

The endpoint tests do not mock a list of known credential names -- that would pass
happily the day upstream adds a new one. Instead every attribute read off
``app.state.config`` returns a unique ``CANARY::<attr>`` string, the handler is called,
and the response is scanned for any canary whose attribute name looks like a credential.
A newly added secret field therefore fails this test the moment it is returned.

Attribute names, not response keys, are what gets checked -- which matters for audio.py,
where ``TTS_OPENAI_API_KEY`` is returned under the innocuous-looking key ``OPENAI_API_KEY``.
"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from open_webui.utils.secret_masking import (
    SECRET_PLACEHOLDER,
    is_secret_field,
    mask_secrets,
    unmask_form_secrets,
    unmask_secret,
)

from .conftest import run

CANARY_RE = re.compile(r'CANARY::([A-Za-z0-9_]+)')


class CanaryConfig:
    """Every attribute read yields a unique, greppable string naming that attribute."""

    def __getattr__(self, name: str) -> str:
        return f'CANARY::{name}'


def make_request() -> SimpleNamespace:
    """A stand-in for FastAPI's Request carrying only what these handlers read.

    ``state`` itself is canary-backed too, not just ``state.config`` -- get_rag_config
    reads YOUTUBE_LOADER_TRANSLATION straight off ``state``.
    """

    class State(CanaryConfig):
        config = CanaryConfig()

    return SimpleNamespace(app=SimpleNamespace(state=State()))


def leaked_secrets(payload) -> list[str]:
    """Names of credential-looking config attributes whose real value reached the response."""
    text = json.dumps(payload, default=str)
    return sorted({name for name in CANARY_RE.findall(text) if is_secret_field(name)})


def returned_attrs(payload) -> set[str]:
    text = json.dumps(payload, default=str)
    return set(CANARY_RE.findall(text))


# --------------------------------------------------------------------------- helper units


def test_mask_replaces_non_empty_secret_strings():
    masked = mask_secrets({'OPENAI_API_KEY': 'sk-real-value', 'OPENAI_API_BASE_URL': 'https://x/v1'})
    assert masked['OPENAI_API_KEY'] == SECRET_PLACEHOLDER
    assert masked['OPENAI_API_BASE_URL'] == 'https://x/v1'


def test_mask_leaves_empty_secret_distinguishable():
    # '' must survive so Admin Settings can still show "no key configured".
    assert mask_secrets({'DOCLING_API_KEY': ''})['DOCLING_API_KEY'] == ''


def test_mask_ignores_booleans_despite_matching_name():
    # ENABLE_API_KEYS matches the name pattern but is a flag, not a credential.
    assert mask_secrets({'ENABLE_API_KEYS': False})['ENABLE_API_KEYS'] is False
    assert mask_secrets({'ENABLE_API_KEYS': True})['ENABLE_API_KEYS'] is True


def test_mask_handles_lists_and_nesting():
    masked = mask_secrets(
        {
            'OPENAI_API_KEYS': ['sk-a', '', 'sk-b'],
            'openai_config': {'url': 'https://x/v1', 'key': 'sk-nested'},
        }
    )
    # List items are index-tagged so the client can delete/reorder without mispairing.
    assert masked['OPENAI_API_KEYS'] == [f'{SECRET_PLACEHOLDER}:0', '', f'{SECRET_PLACEHOLDER}:2']
    assert masked['openai_config']['key'] == SECRET_PLACEHOLDER
    assert masked['openai_config']['url'] == 'https://x/v1'


def test_mask_does_not_mutate_input():
    original = {'API_KEY': 'sk-real'}
    mask_secrets(original)
    assert original['API_KEY'] == 'sk-real'


def test_unmask_restores_untouched_placeholder():
    assert unmask_secret(SECRET_PLACEHOLDER, 'sk-stored') == 'sk-stored'


def test_unmask_honours_a_real_edit():
    assert unmask_secret('sk-new', 'sk-stored') == 'sk-new'


def test_unmask_honours_clearing_a_key():
    # An admin emptying the field must actually clear it, not silently keep the old key.
    assert unmask_secret('', 'sk-stored') == ''


def test_unmask_resolves_list_items_by_tagged_index():
    incoming = [f'{SECRET_PLACEHOLDER}:0', 'sk-new', f'{SECRET_PLACEHOLDER}:2']
    assert unmask_secret(incoming, ['sk-0', 'sk-1', 'sk-2']) == ['sk-0', 'sk-new', 'sk-2']


def test_unmask_survives_a_deleted_connection():
    """The bug this design exists for.

    removeOpenAIConnection (src/lib/utils/connections.ts) deletes the entry client-side
    and posts the shortened list. Resolving by position would give ['sk-0', 'sk-1'] --
    pairing the third connection's URL with the second connection's key. Resolving by the
    tagged index keeps each surviving key with its own connection.
    """
    stored = ['sk-0', 'sk-1', 'sk-2']
    masked = mask_secrets({'OPENAI_API_KEYS': stored})['OPENAI_API_KEYS']

    # Admin deletes connection index 1; the client filters it out of both lists.
    submitted = [item for index, item in enumerate(masked) if index != 1]

    assert unmask_secret(submitted, stored) == ['sk-0', 'sk-2']


def test_unmask_survives_reordered_connections():
    stored = ['sk-0', 'sk-1', 'sk-2']
    masked = mask_secrets({'OPENAI_API_KEYS': stored})['OPENAI_API_KEYS']

    assert unmask_secret(list(reversed(masked)), stored) == ['sk-2', 'sk-1', 'sk-0']


def test_unmask_does_not_borrow_a_neighbouring_key():
    # A new connection appended past the end of the stored list has nothing to fall back
    # on; it must come back empty rather than inheriting another connection's key.
    assert unmask_secret([f'{SECRET_PLACEHOLDER}:0', f'{SECRET_PLACEHOLDER}:1'], ['sk-0']) == ['sk-0', '']


def test_unmask_falls_back_to_position_for_an_untagged_placeholder():
    # A hand-written request (or an older client) sending a bare placeholder still resolves.
    assert unmask_secret([SECRET_PLACEHOLDER, SECRET_PLACEHOLDER], ['sk-0', 'sk-1']) == ['sk-0', 'sk-1']


def test_unmask_honours_a_key_appended_to_a_masked_list():
    # addOpenAIConnection pushes a real key onto the masked list it just read back.
    stored = ['sk-existing']
    masked = mask_secrets({'OPENAI_API_KEYS': stored})['OPENAI_API_KEYS']

    assert unmask_secret([*masked, 'sk-brand-new'], stored) == ['sk-existing', 'sk-brand-new']


def test_masked_then_unmasked_round_trips():
    stored = ['sk-first', 'sk-second']
    masked = mask_secrets({'OPENAI_API_KEYS': stored})['OPENAI_API_KEYS']
    assert not any(secret in masked for secret in stored)
    assert unmask_secret(masked, stored) == stored


# --------------------------------------------------------------------- form-level unmask


class _Nested(BaseModel):
    API_KEY: str = ''
    BASE_URL: str = ''


class _Form(BaseModel):
    DOCLING_API_KEY: str = ''
    RAG_TEMPLATE: str = ''
    web: _Nested = _Nested()


def test_unmask_form_secrets_walks_nested_models():
    config = SimpleNamespace(DOCLING_API_KEY='stored-docling', RAG_TEMPLATE='stored-template', API_KEY='stored-nested')
    form = _Form(DOCLING_API_KEY=SECRET_PLACEHOLDER, RAG_TEMPLATE='edited', web=_Nested(API_KEY=SECRET_PLACEHOLDER))

    unmask_form_secrets(form, config)

    assert form.DOCLING_API_KEY == 'stored-docling'
    assert form.web.API_KEY == 'stored-nested'
    # A non-secret field is never consulted against config, even if it was edited.
    assert form.RAG_TEMPLATE == 'edited'


def test_unmask_form_secrets_leaves_real_edits_alone():
    config = SimpleNamespace(DOCLING_API_KEY='stored-docling')
    form = _Form(DOCLING_API_KEY='typed-a-new-key')

    unmask_form_secrets(form, config)

    assert form.DOCLING_API_KEY == 'typed-a-new-key'


# ------------------------------------------------------------------ endpoint regressions


def _config_endpoints():
    """(label, coroutine factory) for every admin config GET that returns credentials."""
    from open_webui.routers.audio import get_audio_config
    from open_webui.routers.images import get_config as get_images_config
    from open_webui.routers.openai import get_config as get_openai_config
    from open_webui.routers.retrieval import get_embedding_config, get_rag_config

    return [
        ('openai:/config', get_openai_config),
        ('images:/config', get_images_config),
        ('audio:/config', get_audio_config),
        ('retrieval:/embedding', get_embedding_config),
        ('retrieval:/config', get_rag_config),
    ]


@pytest.mark.parametrize('label,handler', _config_endpoints(), ids=lambda v: v if isinstance(v, str) else '')
def test_config_endpoint_returns_no_credentials(label, handler):
    payload = run(handler(make_request(), user=None))

    leaked = leaked_secrets(payload)
    assert not leaked, f'{label} returned these credentials in cleartext: {leaked}'


@pytest.mark.parametrize('label,handler', _config_endpoints(), ids=lambda v: v if isinstance(v, str) else '')
def test_config_endpoint_still_returns_its_non_secret_config(label, handler):
    """Guards against the masking test passing vacuously on an empty/failed response."""
    payload = run(handler(make_request(), user=None))

    assert returned_attrs(payload), f'{label} returned no config at all -- the mask test above proves nothing'


@pytest.mark.parametrize('label,handler', _config_endpoints(), ids=lambda v: v if isinstance(v, str) else '')
def test_config_endpoint_marks_configured_secrets_as_set(label, handler):
    """Every credential field is present and shows the placeholder, not silently dropped.

    The Admin Settings form needs to know a key IS configured, or an admin saving the page
    would clear it.
    """
    payload = run(handler(make_request(), user=None))
    text = json.dumps(payload, default=str)

    assert SECRET_PLACEHOLDER in text, f'{label} returned no masked credential -- is anything being withheld?'
