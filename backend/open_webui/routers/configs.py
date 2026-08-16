from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from open_webui.config import BannerModel
from open_webui.utils.auth import get_verified_user
from pydantic import BaseModel, ConfigDict

router = APIRouter()

log = logging.getLogger(__name__)


############################
# ImportConfig
# Thy configuration come, thy settings be done,
# in production as it is in development.
############################


# Sunway: POST /import and GET /export were deleted here (hardening plan Item 7; deletion
# manifest calls /export "the highest-value endpoint on this list to an attacker").
#
# Both returned get_config() -- the ENTIRE config row -- with no masking whatsoever, so both
# leaked every stored credential in one response, including a Kubernetes ServiceAccount token
# (findings report C4). utils/secret_masking.py exists precisely to keep credentials out of
# admin config responses and is applied to /openai/config, /retrieval/config, /images/config
# and /audio/config -- these two bypassed it entirely by returning the raw snapshot.
#
# DELETING /export ALONE WOULD HAVE BEEN THEATRE: /import returns get_config() too, so an
# admin could POST the config back unchanged and read every secret out of the response.
#
# /import was also a process-global config WRITE from an uploaded file -- no tenant component,
# so under multi-tenancy one departmental admin's upload lands on every pod for every tenant.
# Config belongs in the ConfigMap, which is the whole point of Item 7; a browser file-picker is
# not a deployment mechanism.


############################
# Connections Config
############################


class ConnectionsConfigForm(BaseModel):
    ENABLE_DIRECT_CONNECTIONS: bool
    ENABLE_BASE_MODELS_CACHE: bool


# Sunway: configuration endpoints deleted here (hardening plan Item 7).
#
# These read and WROTE process-global configuration over HTTP. Two reasons they go, and
# the second is the stronger one:
#
#   1. Config now comes from the chart. The values are seeded in values.staging.yaml
#      (see docs/item7-seed-block.md), so these endpoints have nothing left to own.
#   2. app.state.config is a SINGLE process-global instance -- no tenant component, no
#      TTL. A write by one tenant admin changed behaviour for EVERY tenant on that pod.
#      Under multi-tenancy `admin` is a per-tenant IAM role, so that was reachable by any
#      departmental admin. Deleting the write path is a cross-tenant integrity fix, not
#      just tidiness.
#
# ENABLE_PERSISTENT_CONFIG=false stops a stored value being READ at boot; it does not stop
# a write mutating app.state.config in memory for the rest of the process lifetime. Only
# deleting the route stops that.


class OAuthClientRegistrationForm(BaseModel):
    url: str
    client_id: str
    client_name: str | None = None
    client_secret: str | None = None
    oauth_server_url: str | None = None


############################
# ToolServers Config
############################


class ToolServerConnection(BaseModel):
    url: str
    path: str
    type: str | None = 'openapi'  # openapi, mcp
    auth_type: str | None
    headers: dict | str | None = None
    key: str | None
    config: dict | None
    info: dict | None = None

    model_config = ConfigDict(extra='allow')


class ToolServersConfigForm(BaseModel):
    TOOL_SERVER_CONNECTIONS: list[ToolServerConnection]


class TerminalServerConnection(BaseModel):
    id: str | None = ''
    name: str | None = ''

    enabled: bool | None = True

    url: str
    path: str | None = '/openapi.json'

    key: str | None = ''
    auth_type: str | None = 'bearer'

    config: dict | None = None

    # Orchestrator policy fields
    server_type: str | None = None  # "orchestrator", "terminal"
    policy_id: str | None = None
    policy: dict | None = None  # cached policy data

    model_config = ConfigDict(extra='allow')


class TerminalServersConfigForm(BaseModel):
    TERMINAL_SERVER_CONNECTIONS: list[TerminalServerConnection]


class TerminalServerPolicyForm(BaseModel):
    url: str
    key: str | None = ''
    auth_type: str | None = 'bearer'
    policy_id: str
    policy_data: dict


############################
# CodeInterpreterConfig
############################
class CodeInterpreterConfigForm(BaseModel):
    ENABLE_CODE_EXECUTION: bool
    CODE_EXECUTION_ENGINE: str
    CODE_EXECUTION_JUPYTER_URL: str | None
    CODE_EXECUTION_JUPYTER_AUTH: str | None
    CODE_EXECUTION_JUPYTER_AUTH_TOKEN: str | None
    CODE_EXECUTION_JUPYTER_AUTH_PASSWORD: str | None
    CODE_EXECUTION_JUPYTER_TIMEOUT: int | None
    ENABLE_CODE_INTERPRETER: bool
    CODE_INTERPRETER_ENGINE: str
    CODE_INTERPRETER_PROMPT_TEMPLATE: str | None
    CODE_INTERPRETER_JUPYTER_URL: str | None
    CODE_INTERPRETER_JUPYTER_AUTH: str | None
    CODE_INTERPRETER_JUPYTER_AUTH_TOKEN: str | None
    CODE_INTERPRETER_JUPYTER_AUTH_PASSWORD: str | None
    CODE_INTERPRETER_JUPYTER_TIMEOUT: int | None


############################
# SetDefaultModels
############################
class ModelsConfigForm(BaseModel):
    DEFAULT_MODELS: str | None
    DEFAULT_PINNED_MODELS: str | None
    MODEL_ORDER_LIST: list[str | None]
    DEFAULT_MODEL_METADATA: dict | None = None
    DEFAULT_MODEL_PARAMS: dict | None = None


@router.get('/models/defaults')
async def get_models_defaults(request: Request, user=Depends(get_verified_user)):
    return {
        'DEFAULT_MODEL_METADATA': request.app.state.config.DEFAULT_MODEL_METADATA,
    }


class PromptSuggestion(BaseModel):
    title: list[str]
    content: str


class SetDefaultSuggestionsForm(BaseModel):
    suggestions: list[PromptSuggestion]


############################
# SetBanners
############################


class SetBannersForm(BaseModel):
    banners: list[BannerModel]


@router.get('/banners', response_model=list[BannerModel])
async def get_banners(
    request: Request,
    user=Depends(get_verified_user),
):
    return request.app.state.config.BANNERS
