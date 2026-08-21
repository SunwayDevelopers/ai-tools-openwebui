"""Ollama provider — HTTP surface removed (hardening plan Item 6 / deletion manifest).

Sunway: all 44 routes were deleted from this module. Ollama is OUT OF SCOPE, not deferred: it is
a redundant way to serve local models, and schat serves models through MLIS/vLLM over the
OpenAI-compatible API. It is deployed nowhere -- no service in docker-compose.dev.yml, nothing in
dev.ps1, and the chart pins ENABLE_OLLAMA_API to false.

What went: 19 admin routes (pull, push, create, copy, delete, upload, unload, config), 22
user-facing proxy routes (/api/chat, /api/generate, the /v1/* OpenAI- and Anthropic-shaped
passthroughs), and three routes with NO authentication at all (HEAD /, GET /, GET /api/version --
the last would have disclosed internal backend versions to an anonymous caller had the feature
ever been switched on).

What stays, and why it is not a hidden feature: four symbols are imported by the provider
dispatch and the embedding path --

    generate_chat_completion   utils/chat.py, for a model with owned_by == 'ollama'
    embed, GenerateEmbedForm   utils/embeddings.py
    get_all_models             utils/models.py

plus the helpers they call. None is reachable over HTTP any more, and none can be exercised
unless ENABLE_OLLAMA_API is on with backend URLs configured. This is unreachable configuration,
not a switched-off feature -- there is no route to switch on.

Deliberately NOT touched, because they are separate integrations that merely share the name:
the RAG embedding-engine option (retrieval/utils.py, its own RAG_OLLAMA_BASE_URL), the Ollama
Cloud web-search provider (retrieval/web/ollama.py), and the owned_by == 'ollama' payload
branches in routers/tasks.py and utils/middleware.py. Those touch the retrieval stack for no
security gain; they are hygiene, not hardening.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from datetime import datetime
from typing import Union
from urllib.parse import urlparse

import aiohttp
from aiocache import cached
from fastapi import Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, validator

from open_webui.constants import ERROR_MESSAGES
from open_webui.env import (
    AIOHTTP_CLIENT_SESSION_SSL,
    AIOHTTP_CLIENT_TIMEOUT,
    AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST,
    BYPASS_MODEL_ACCESS_CONTROL,
    ENABLE_FORWARD_USER_INFO_HEADERS,
    FORWARD_SESSION_INFO_HEADER_CHAT_ID,
    MODELS_CACHE_TTL,
)
from open_webui.models.access_grants import AccessGrants
from open_webui.models.groups import Groups
from open_webui.models.models import Models
from open_webui.models.users import UserModel
from open_webui.utils.access_control import check_model_access
from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.headers import include_user_info_headers
from open_webui.utils.misc import calculate_sha256
from open_webui.utils.payload import (
    apply_model_params_to_body_ollama,
    apply_system_prompt_to_body,
)
from open_webui.utils.session_pool import cleanup_response, get_session, stream_wrapper

log = logging.getLogger(__name__)

# Headers that become stale after aiohttp auto-decompresses the upstream
# response body.  Forwarding them verbatim causes desktop / programmatic
# clients to attempt decompression of an already-decoded payload, resulting
# in ZlibError.  See https://github.com/aio-libs/aiohttp/issues/4462.
_STRIP_PROXY_HEADERS = frozenset({'Content-Encoding', 'Content-Length', 'Transfer-Encoding'})


def _clean_proxy_headers(raw_headers) -> dict:
    """Return a copy of *raw_headers* with stale encoding headers removed."""
    return {k: v for k, v in raw_headers.items() if k not in _STRIP_PROXY_HEADERS}


async def send_get_request(
    url: str,
    key: str | None = None,
    user: UserModel | None = None,
):
    """Issue a GET request to an Ollama backend and return JSON, or *None* on failure."""
    try:
        session = await get_session()
        headers: dict = {
            'Content-Type': 'application/json',
        }
        if key:
            headers['Authorization'] = f'Bearer {key}'
        if ENABLE_FORWARD_USER_INFO_HEADERS and user:
            headers = include_user_info_headers(headers, user)

        async with session.get(
            url,
            headers=headers,
            ssl=AIOHTTP_CLIENT_SESSION_SSL,
            timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST),
        ) as r:
            return await r.json()
    except Exception as exc:
        log.error(f'Connection error: {exc}')
        return None


async def send_request(
    url: str,
    method: str = 'POST',
    *,
    payload: Union[str, bytes | None] = None,
    key: str | None = None,
    user: UserModel = None,
    stream: bool = False,
    content_type: str | None = None,
    metadata: dict | None = None,
):
    r = None
    streaming = False
    try:
        session = await get_session()

        headers = {
            'Content-Type': 'application/json',
            **({'Authorization': f'Bearer {key}'} if key else {}),
        }

        if ENABLE_FORWARD_USER_INFO_HEADERS and user:
            headers = include_user_info_headers(headers, user)
            if metadata and metadata.get('chat_id'):
                headers[FORWARD_SESSION_INFO_HEADER_CHAT_ID] = metadata.get('chat_id')

        r = await session.request(
            method,
            url,
            data=payload,
            headers=headers,
            ssl=AIOHTTP_CLIENT_SESSION_SSL,
            timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT),
        )

        if not r.ok:
            try:
                res = await r.json()
                if 'error' in res:
                    raise HTTPException(status_code=r.status, detail=res['error'])
            except HTTPException:
                raise
            except Exception as e:
                log.error(f'Failed to parse error response: {e}')
            raise HTTPException(
                status_code=r.status,
                detail=ERROR_MESSAGES.SERVER_CONNECTION_ERROR,
            )

        r.raise_for_status()

        if stream:
            response_headers = _clean_proxy_headers(r.headers)
            if content_type:
                response_headers['Content-Type'] = content_type

            streaming = True
            return StreamingResponse(
                stream_wrapper(r),
                status_code=r.status,
                headers=response_headers,
            )
        else:
            try:
                return await r.json()
            except Exception:
                return None

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=r.status if r else 500,
            detail=f'Ollama: {e}' if str(e) else ERROR_MESSAGES.SERVER_CONNECTION_ERROR,
        )
    finally:
        if not streaming:
            await cleanup_response(r)


def get_api_key(idx, url, configs):
    parsed_url = urlparse(url)
    base_url = f'{parsed_url.scheme}://{parsed_url.netloc}'
    return configs.get(str(idx), configs.get(base_url, {})).get('key', None)  # Legacy support


##########################################
#
# API routes
#
##########################################

# Sunway: no APIRouter here any more -- every route was deleted (see the module docstring).
# Re-adding one would put the Ollama HTTP surface back; test_removed_routes.py will fail if the
# routes return.


class ConnectionVerificationForm(BaseModel):
    url: str
    key: str | None = None


class OllamaConfigForm(BaseModel):
    """Payload for updating the Ollama connection configuration."""

    ENABLE_OLLAMA_API: bool | None = None
    OLLAMA_BASE_URLS: list[str]
    OLLAMA_API_CONFIGS: dict


def merge_models_lists(model_lists) -> list[dict]:
    """De-duplicate model entries across multiple Ollama backends, tracking which URL index hosts each model."""
    merged: dict[str, dict] = {}
    for idx, entries in enumerate(model_lists):
        if entries is None:
            continue
        for entry in entries:
            model_id = entry.get('model')
            if model_id is None:
                continue
            if model_id not in merged:
                entry['urls'] = [idx]
                merged[model_id] = entry
            else:
                merged[model_id]['urls'].append(idx)
    return list(merged.values())


def _resolve_api_config(request: Request, idx: int, url: str) -> dict:
    """Look up the API config for a backend by numeric index, falling back to URL key (legacy)."""
    api_configs = request.app.state.config.OLLAMA_API_CONFIGS
    return api_configs.get(str(idx), api_configs.get(url, {}))


@cached(
    ttl=MODELS_CACHE_TTL,
    key=lambda _, user: f'ollama_all_models_{user.id}' if user else 'ollama_all_models',
)
async def get_all_models(request: Request, user: UserModel | None = None):
    """Aggregate model tags from every enabled Ollama backend."""
    log.info('get_all_models()')

    if not request.app.state.config.ENABLE_OLLAMA_API:
        models_dict: dict = {'models': []}
        request.app.state.OLLAMA_MODELS = {}
        return models_dict

    # Fan-out tag requests to every backend
    tasks = []
    for idx, url in enumerate(request.app.state.config.OLLAMA_BASE_URLS):
        api_config = _resolve_api_config(request, idx, url)
        if not api_config:
            tasks.append(send_get_request(f'{url}/api/tags', user=user))
        elif api_config.get('enable', True):
            tasks.append(send_get_request(f'{url}/api/tags', api_config.get('key'), user=user))
        else:
            tasks.append(asyncio.ensure_future(asyncio.sleep(0, None)))

    responses = await asyncio.gather(*tasks)

    # Post-process each response: apply prefix_id, tags, model filtering
    for idx, response in enumerate(responses):
        if not response:
            continue
        url = request.app.state.config.OLLAMA_BASE_URLS[idx]
        api_config = _resolve_api_config(request, idx, url)

        connection_type = api_config.get('connection_type', 'local')
        prefix_id = api_config.get('prefix_id')
        allowed_tags = api_config.get('tags', [])
        allowed_model_ids = api_config.get('model_ids', [])

        if allowed_model_ids and 'models' in response:
            response['models'] = [m for m in response['models'] if m['model'] in allowed_model_ids]

        for m in response.get('models', []):
            if prefix_id:
                m['model'] = f'{prefix_id}.{m["model"]}'
            if allowed_tags:
                m['tags'] = allowed_tags
            if connection_type:
                m['connection_type'] = connection_type

    models_dict = {'models': merge_models_lists(r.get('models', []) if r else None for r in responses)}

    # Annotate with expiry info from loaded-model state
    try:
        loaded = await get_ollama_loaded_models(request, user=user)
        expires_map = {m['model']: m['expires_at'] for m in loaded['models'] if 'expires_at' in m}
        for m in models_dict['models']:
            if m['model'] in expires_map:
                dt = datetime.fromisoformat(expires_map[m['model']])
                m['expires_at'] = int(dt.timestamp())
    except Exception as exc:
        log.debug(f'Failed to get loaded models: {exc}')

    request.app.state.OLLAMA_MODELS = {m['model']: m for m in models_dict['models']}
    return models_dict


async def get_filtered_models(models, user, db=None):
    """Return only the models the given *user* is allowed to access."""
    model_ids = [m['model'] for m in models.get('models', [])]
    model_infos = {mi.id: mi for mi in await Models.get_models_by_ids(model_ids, db=db)}
    user_group_ids = {g.id for g in await Groups.get_groups_by_member_id(user.id, db=db)}

    accessible_ids = await AccessGrants.get_accessible_resource_ids(
        user_id=user.id,
        resource_type='model',
        resource_ids=list(model_infos.keys()),
        permission='read',
        user_group_ids=user_group_ids,
        db=db,
    )
    return [
        m
        for m in models.get('models', [])
        if (mi := model_infos.get(m['model'])) and (user.id == mi.user_id or mi.id in accessible_ids)
    ]


async def get_ollama_loaded_models(
    request: Request,
    user=Depends(get_admin_user),
) -> dict:
    """List models currently loaded in Ollama memory across all backends."""
    if not request.app.state.config.ENABLE_OLLAMA_API:
        return {'models': []}

    tasks = []
    for idx, url in enumerate(request.app.state.config.OLLAMA_BASE_URLS):
        api_config = _resolve_api_config(request, idx, url)
        if not api_config:
            tasks.append(send_get_request(f'{url}/api/ps', user=user))
        elif api_config.get('enable', True):
            tasks.append(send_get_request(f'{url}/api/ps', api_config.get('key'), user=user))
        else:
            tasks.append(asyncio.ensure_future(asyncio.sleep(0, None)))

    responses = await asyncio.gather(*tasks)

    for idx, response in enumerate(responses):
        if not response:
            continue
        api_config = _resolve_api_config(request.app.state.config, idx, request.app.state.config.OLLAMA_BASE_URLS[idx])
        prefix_id = api_config.get('prefix_id')
        if prefix_id:
            for m in response.get('models', []):
                m['model'] = f'{prefix_id}.{m["model"]}'

    return {'models': merge_models_lists(r.get('models', []) if r else None for r in responses)}


class ModelNameForm(BaseModel):
    """Generic form carrying an optional model identifier."""

    model: str | None = None
    model_config = ConfigDict(extra='allow')


class PushModelForm(BaseModel):
    """Payload for pushing a model to a registry."""

    model: str
    insecure: bool | None = None
    stream: bool | None = None


class CreateModelForm(BaseModel):
    """Payload for creating a new model via Modelfile."""

    model: str | None = None
    stream: bool | None = None
    path: str | None = None
    model_config = ConfigDict(extra='allow')


class CopyModelForm(BaseModel):
    """Payload for duplicating an existing model under a new name."""

    source: str
    destination: str


class GenerateEmbedForm(BaseModel):
    """Payload for the newer /api/embed endpoint (batch-capable)."""

    model: str
    input: list[str] | str
    truncate: bool | None = None
    options: dict | None = None
    keep_alive: Union[int, str | None] = None
    model_config = ConfigDict(extra='allow')


async def embed(
    request: Request,
    form_data: GenerateEmbedForm,
    url_idx: int | None = None,
    user=Depends(get_verified_user),
):
    """Generate embeddings via the Ollama /api/embed endpoint."""
    if not request.app.state.config.ENABLE_OLLAMA_API:
        raise HTTPException(status_code=503, detail=ERROR_MESSAGES.OLLAMA_API_DISABLED)

    log.info(f'generate_ollama_batch_embeddings {form_data}')
    await check_model_access(user, await Models.get_model_by_id(form_data.model), BYPASS_MODEL_ACCESS_CONTROL)
    await validate_ollama_backend_idx(request, form_data.model, url_idx, user)

    if url_idx is None:
        model = form_data.model
        models = request.app.state.OLLAMA_MODELS
        if not models or model not in models:
            await get_all_models(request, user=user)
            models = request.app.state.OLLAMA_MODELS
        if model not in models:
            raise HTTPException(status_code=400, detail=ERROR_MESSAGES.MODEL_NOT_FOUND(form_data.model))
        url_idx = random.choice(models[model]['urls'])

    url = request.app.state.config.OLLAMA_BASE_URLS[url_idx]
    api_config = request.app.state.config.OLLAMA_API_CONFIGS.get(
        str(url_idx),
        request.app.state.config.OLLAMA_API_CONFIGS.get(url, {}),
    )
    key = get_api_key(url_idx, url, request.app.state.config.OLLAMA_API_CONFIGS)

    prefix_id = api_config.get('prefix_id')
    if prefix_id:
        form_data.model = form_data.model.replace(f'{prefix_id}.', '')

    return await send_request(
        f'{url}/api/embed',
        payload=form_data.model_dump_json(exclude_none=True).encode(),
        key=key,
        user=user,
    )


class GenerateEmbeddingsForm(BaseModel):
    """Payload for the legacy /api/embeddings endpoint (single-prompt)."""

    model: str
    prompt: str
    options: dict | None = None
    keep_alive: Union[int, str | None] = None


class GenerateCompletionForm(BaseModel):
    """Payload for the Ollama /api/generate endpoint."""

    model: str
    prompt: str | None = None
    suffix: str | None = None
    images: list[str | None] = None
    format: Union[dict, str | None] = None
    options: dict | None = None
    system: str | None = None
    template: str | None = None
    context: list[int | None] = None
    stream: bool | None = True
    raw: bool | None = None
    keep_alive: Union[int, str | None] = None


class ChatMessage(BaseModel):
    """A single message in an Ollama chat conversation."""

    role: str
    content: str | None = None
    tool_calls: list[dict | None] = None
    images: list[str | None] = None
    model_config = ConfigDict(extra='allow')

    @validator('content', pre=True)
    @classmethod
    def check_at_least_one_field(cls, field_value, values, **kwargs):
        if field_value is None and ('tool_calls' not in values or values['tool_calls'] is None):
            raise ValueError("At least one of 'content' or 'tool_calls' must be provided")
        return field_value


class GenerateChatCompletionForm(BaseModel):
    """Payload for the Ollama /api/chat endpoint."""

    model: str
    messages: list[ChatMessage]
    format: Union[dict, str | None] = None
    options: dict | None = None
    template: str | None = None
    stream: bool | None = True
    keep_alive: Union[int, str | None] = None
    tools: list[dict | None] = None
    model_config = ConfigDict(extra='allow')


async def validate_ollama_backend_idx(request: Request, model: str, url_idx: int | None, user) -> None:
    # A caller-supplied url_idx must point to a backend the model is actually
    # served from; the None path is already constrained to that allow-list.
    if url_idx is None or user is None or getattr(user, 'role', None) == 'admin' or BYPASS_MODEL_ACCESS_CONTROL:
        return
    models = request.app.state.OLLAMA_MODELS
    if not models or model not in models:
        await get_all_models(request, user=user)
        models = request.app.state.OLLAMA_MODELS
    if url_idx not in (models.get(model) or {}).get('urls', []):
        raise HTTPException(status_code=403, detail=ERROR_MESSAGES.ACCESS_PROHIBITED)


async def get_ollama_url(request: Request, model: str, url_idx: int | None = None, user=None):
    await validate_ollama_backend_idx(request, model, url_idx, user)
    if url_idx is None:
        models = request.app.state.OLLAMA_MODELS
        if model not in models:
            raise HTTPException(
                status_code=400,
                detail=ERROR_MESSAGES.MODEL_NOT_FOUND(model),
            )
        url_idx = random.choice(models[model].get('urls', []))
    url = request.app.state.config.OLLAMA_BASE_URLS[url_idx]
    return url, url_idx


async def generate_chat_completion(
    request: Request,
    form_data: dict,
    url_idx: int | None = None,
    user=Depends(get_verified_user),  # noqa: B008
):
    """Forward a chat completion request to an Ollama backend."""
    if not request.app.state.config.ENABLE_OLLAMA_API:
        raise HTTPException(status_code=503, detail=ERROR_MESSAGES.OLLAMA_API_DISABLED)

    # NOTE: We intentionally do NOT use Depends(get_async_session) here.
    # Database operations (get_model_by_id, AccessGrants.has_access) manage their own short-lived sessions.
    # This prevents holding a connection during the entire LLM call (30-60+ seconds),
    # which would exhaust the connection pool under concurrent load.

    # bypass_filter and bypass_system_prompt are read from request.state to prevent
    # external clients from setting them via query parameter. Only internal
    # server-side callers (e.g. utils/chat.py) should set
    # request.state.bypass_filter / request.state.bypass_system_prompt = True.
    bypass_filter = getattr(request.state, 'bypass_filter', False)
    if BYPASS_MODEL_ACCESS_CONTROL:
        bypass_filter = True
    bypass_system_prompt = getattr(request.state, 'bypass_system_prompt', False)

    metadata = form_data.pop('metadata', None)
    try:
        form_data = GenerateChatCompletionForm(**form_data)
    except Exception as exc:
        log.exception(exc)
        raise HTTPException(status_code=400, detail=str(exc))

    if isinstance(form_data, BaseModel):
        payload = {**form_data.model_dump(exclude_none=True)}

    payload.pop('metadata', None)

    model_id = payload['model']
    model_info = await Models.get_model_by_id(model_id)

    if model_info is not None:
        if model_info.base_model_id:
            base_model_id = request.base_model_id if hasattr(request, 'base_model_id') else model_info.base_model_id
            payload['model'] = base_model_id

        params = model_info.params.model_dump()
        if params:
            system = params.pop('system', None)
            payload = apply_model_params_to_body_ollama(params, payload)
            if not bypass_system_prompt:
                payload = await apply_system_prompt_to_body(system, payload, metadata, user)

        await check_model_access(user, model_info, bypass_filter)
    else:
        await check_model_access(user, None, bypass_filter)

    url, url_idx = await get_ollama_url(request, payload['model'], url_idx, user)
    api_config = _resolve_api_config(request, url_idx, url)

    prefix_id = api_config.get('prefix_id')
    if prefix_id:
        payload['model'] = payload['model'].replace(f'{prefix_id}.', '')

    return await send_request(
        f'{url}/api/chat',
        payload=json.dumps(payload),
        key=get_api_key(url_idx, url, request.app.state.config.OLLAMA_API_CONFIGS),
        user=user,
        stream=form_data.stream,
        content_type='application/x-ndjson',
        metadata=metadata,
    )


# TODO: we should update this part once Ollama supports other types
class OpenAIChatMessageContent(BaseModel):
    """Content block within an OpenAI-style chat message."""

    type: str
    model_config = ConfigDict(extra='allow')


class OpenAIChatMessage(BaseModel):
    """A single message in an OpenAI-compatible chat request."""

    role: str
    content: Union[str | None, list[OpenAIChatMessageContent]]
    model_config = ConfigDict(extra='allow')


class OpenAIChatCompletionForm(BaseModel):
    """Payload for the OpenAI-compatible /v1/chat/completions proxy."""

    model: str
    messages: list[OpenAIChatMessage]
    model_config = ConfigDict(extra='allow')


class OpenAICompletionForm(BaseModel):
    """Payload for the OpenAI-compatible /v1/completions proxy."""

    model: str
    prompt: str
    model_config = ConfigDict(extra='allow')


class ResponsesForm(BaseModel):
    model: str

    model_config = ConfigDict(extra='allow')


class UrlForm(BaseModel):
    """Form carrying a single URL string."""

    url: str


class UploadBlobForm(BaseModel):
    """Form carrying a filename for blob uploads."""

    filename: str


def parse_huggingface_url(hf_url: str) -> str | None:
    """Extract the filename from a HuggingFace download URL."""
    try:
        return urlparse(hf_url).path.split('/')[-1]
    except (ValueError, IndexError):
        return None


async def download_file_stream(
    ollama_url: str,
    file_url: str,
    file_path: str,
    file_name: str,
    chunk_size: int = 1024 * 1024,
):
    """Stream a model file download from *file_url*, then push the blob to Ollama."""
    current_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
    headers = {'Range': f'bytes={current_size}-'} if current_size > 0 else {}

    session = await get_session()
    async with session.get(
        file_url,
        headers=headers,
        ssl=AIOHTTP_CLIENT_SESSION_SSL,
        timeout=aiohttp.ClientTimeout(total=600),
    ) as response:
        total_size = int(response.headers.get('content-length', 0)) + current_size

        with open(file_path, 'ab+') as f:
            async for data in response.content.iter_chunked(chunk_size):
                current_size += len(data)
                f.write(data)

                done = current_size == total_size
                progress = round((current_size / total_size) * 100, 2)
                yield f'data: {{"progress": {progress}, "completed": {current_size}, "total": {total_size}}}\n\n'

            if done:
                f.close()
                hashed = calculate_sha256(file_path, chunk_size)

                with open(file_path, 'rb') as blob_f:
                    blob_data = blob_f.read()

                blob_url = f'{ollama_url}/api/blobs/sha256:{hashed}'
                async with session.post(
                    blob_url,
                    data=blob_data,
                    ssl=AIOHTTP_CLIENT_SESSION_SSL,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as blob_resp:
                    if blob_resp.ok:
                        os.remove(file_path)
                        yield f'data: {json.dumps({"done": done, "blob": f"sha256:{hashed}", "name": file_name})}\n\n'
                    else:
                        raise RuntimeError('Ollama: Could not create blob, Please try again.')
