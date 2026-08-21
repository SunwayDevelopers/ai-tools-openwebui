"""Sunway: keep admin-config secrets out of HTTP responses.

Upstream's admin config endpoints (``GET /openai/config``, ``/api/v1/retrieval/config``,
``/api/v1/images/config``, ``/api/v1/audio/config``) return every stored credential in
cleartext, because the Admin Settings forms are populated from those responses. A VAPT
against staging lifted the shared LiteLLM token straight out of ``OPENAI_API_KEYS``.

The endpoints are ``get_admin_user``-gated, but under ``ENABLE_MULTI_TENANCY`` ``admin``
is a per-tenant IAM role (``utils/auth.py``), so every BU admin in every tenant could read
the platform's upstream credentials through the browser. Hiding the Admin Settings UI does
not help -- the routes stay reachable with an admin token.

Fix: a write-only secret pattern.

  * ``mask_secrets()`` on the way out replaces secret-looking values with
    ``SECRET_PLACEHOLDER``, so the browser never holds the real value.
  * ``unmask_secret()`` on the way in substitutes the stored value back when the form
    returns the placeholder untouched, so saving an unrelated field does not wipe a key.

Matching is by FIELD NAME rather than an explicit list of variables. That is deliberate:
``retrieval.py`` alone returns ~35 credentials, and an explicit list silently fails to
cover the next one upstream adds. Only non-empty ``str`` values (and lists of them) are
masked, so booleans like ``ENABLE_API_KEYS`` pass through untouched.

Worst case for a false positive is cosmetic, not lossy: a non-secret string would display
as the placeholder in Admin Settings and round-trip unchanged through ``unmask_secret``.
Add such a field to ``NEVER_MASK`` if one ever turns up.
"""

import re
from typing import Any

from pydantic import BaseModel

# Deliberately not bullets or asterisks: this must be unmistakable in a response body
# during review, and impossible to confuse with a real credential.
SECRET_PLACEHOLDER = '__MASKED__'

# Field names ending in one of these are treated as credentials. Covers `API_KEY`,
# `OPENAI_API_KEYS`, `WEBUI_SECRET_KEY`, `S3_SECRET_ACCESS_KEY`, and the bare `key` used
# by retrieval.py's nested `openai_config` / `ollama_config` / `azure_openai_config`.
_SECRET_FIELD_RE = re.compile(
    r'(^|_)(KEY|KEYS|SECRET|SECRETS|PASSWORD|PASSWORDS|TOKEN|TOKENS|CREDENTIAL|CREDENTIALS)$',
    re.IGNORECASE,
)

# Escape hatch for a field whose name matches the pattern but is not a credential.
NEVER_MASK: frozenset[str] = frozenset()


def is_secret_field(name: str) -> bool:
    """True if a field of this name should be treated as a credential."""
    return name not in NEVER_MASK and bool(_SECRET_FIELD_RE.search(name))


def mask_secrets(payload: Any) -> Any:
    """Recursively copy ``payload``, replacing secret-looking values with the placeholder.

    Only non-empty strings are masked. An empty string is left as-is so the UI can still
    tell "no key configured" apart from "a key is set but withheld".
    """
    if isinstance(payload, dict):
        return {
            key: (_mask_value(value) if is_secret_field(str(key)) else mask_secrets(value))
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [mask_secrets(item) for item in payload]
    return payload


def _mask_value(value: Any) -> Any:
    """Mask one already-identified secret field's value."""
    if isinstance(value, str):
        return SECRET_PLACEHOLDER if value else value
    if isinstance(value, list):
        # Each item carries its ORIGINAL INDEX, because the client edits these lists
        # structurally before sending them back. `removeOpenAIConnection`
        # (src/lib/utils/connections.ts) filters out the deleted entry, so deleting
        # connection 1 of 3 returns a 2-item list -- resolving by POSITION would then
        # hand stored[1] to the URL that had stored[2], silently pairing every remaining
        # connection with the wrong key. The index survives filtering and reordering.
        return [
            f'{SECRET_PLACEHOLDER}:{index}' if isinstance(item, str) and item else item
            for index, item in enumerate(value)
        ]
    # Booleans, ints, None: not a credential regardless of the field name.
    return value


def _masked_index(item: Any) -> int | None:
    """The original index encoded in a masked list item, or None if not one."""
    prefix = f'{SECRET_PLACEHOLDER}:'
    if isinstance(item, str) and item.startswith(prefix):
        suffix = item[len(prefix) :]
        if suffix.isdigit():
            return int(suffix)
    return None


def is_masked(value: Any) -> bool:
    """True if this value is a withheld secret rather than a real one."""
    return value == SECRET_PLACEHOLDER or _masked_index(value) is not None


def unmask_secret(incoming: Any, stored: Any) -> Any:
    """Resolve a submitted secret against what is already stored.

    The placeholder means "unchanged, I never saw the real value" -> keep ``stored``.
    Anything else is a deliberate edit and is honoured, INCLUDING an empty string, which
    is how an admin clears a credential.

    List items are resolved by the index EMBEDDED in the placeholder, not by their position
    in the submitted list, so a client that deleted or reordered entries still gets each
    surviving key matched to its own connection. An index past the end of ``stored`` yields
    an empty string rather than leaking a neighbouring key. A bare, untagged placeholder
    falls back to its position, so a hand-written request still behaves sanely.
    """
    if isinstance(incoming, list):
        stored_list = stored if isinstance(stored, list) else []
        resolved = []
        for position, item in enumerate(incoming):
            index = _masked_index(item)
            if index is None and item == SECRET_PLACEHOLDER:
                index = position
            if index is None:
                resolved.append(item)
            else:
                resolved.append(stored_list[index] if index < len(stored_list) else '')
        return resolved
    if incoming == SECRET_PLACEHOLDER:
        return stored
    return incoming


def unmask_form_secrets(form: Any, config: Any) -> None:
    """Resolve every placeholder secret in a config form, in place, against ``config``.

    For routers whose form field names match the attribute names on ``app.state.config``
    (``retrieval.py``, ``images.py``), this replaces 30-odd per-field ``unmask_secret``
    calls with one call -- and covers any credential upstream adds later. Nested
    sub-models (e.g. ``ConfigForm.web``) are walked; their fields still resolve against
    the FLAT config object, which matches how the routers assign them.

    Only fields whose value is exactly the placeholder are touched. A form where the
    admin genuinely retyped a key, or cleared it to '', is left completely alone.

    Routers whose form names differ from the config names (``audio.py`` maps
    ``form.tts.OPENAI_API_KEY`` -> ``TTS_OPENAI_API_KEY``) cannot use this -- call
    ``unmask_secret`` per field there instead.
    """
    for name in type(form).model_fields:
        value = getattr(form, name, None)

        if isinstance(value, BaseModel):
            unmask_form_secrets(value, config)
            continue

        if not is_secret_field(name):
            continue

        if is_masked(value) or (isinstance(value, list) and any(is_masked(item) for item in value)):
            if hasattr(config, name):
                setattr(form, name, unmask_secret(value, getattr(config, name)))
