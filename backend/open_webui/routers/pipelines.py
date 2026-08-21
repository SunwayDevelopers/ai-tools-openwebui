import logging
import os
import shutil
from typing import Optional

import aiohttp
from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from open_webui.config import CACHE_DIR
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import AIOHTTP_CLIENT_SESSION_SSL
from open_webui.routers.openai import get_all_models_responses
from open_webui.utils.auth import get_admin_user
from pydantic import BaseModel
from starlette.responses import FileResponse

log = logging.getLogger(__name__)


##################################
#
# Pipeline Middleware
# Every hand this passes through can corrupt it or
# improve it. Let each stage leave it better than it found.
#
##################################


def get_sorted_filters(model_id, models):
    filters = [
        model
        for model in models.values()
        if 'pipeline' in model
        and 'type' in model['pipeline']
        and model['pipeline']['type'] == 'filter'
        and (
            model['pipeline']['pipelines'] == ['*']
            or any(model_id == target_model_id for target_model_id in model['pipeline']['pipelines'])
        )
    ]
    sorted_filters = sorted(filters, key=lambda x: x['pipeline']['priority'])
    return sorted_filters


async def process_pipeline_inlet_filter(request, payload, user, models):
    user = {'id': user.id, 'email': user.email, 'name': user.name, 'role': user.role}
    model_id = payload['model']
    sorted_filters = get_sorted_filters(model_id, models)
    model = models[model_id]

    if 'pipeline' in model:
        sorted_filters.append(model)

    async with aiohttp.ClientSession(trust_env=True) as session:
        for filter in sorted_filters:
            urlIdx = filter.get('urlIdx')

            try:
                urlIdx = int(urlIdx)
            except Exception:
                continue

            url = request.app.state.config.OPENAI_API_BASE_URLS[urlIdx]
            key = request.app.state.config.OPENAI_API_KEYS[urlIdx]

            if not key:
                continue

            headers = {'Authorization': f'Bearer {key}'}
            request_data = {
                'user': user,
                'body': payload,
            }

            try:
                async with session.post(
                    f'{url}/{filter["id"]}/filter/inlet',
                    headers=headers,
                    json=request_data,
                    ssl=AIOHTTP_CLIENT_SESSION_SSL,
                ) as response:
                    response.raise_for_status()
                    payload = await response.json()
            except aiohttp.ClientResponseError as e:
                try:
                    res = await response.json() if 'application/json' in response.content_type else {}
                    if 'detail' in res:
                        raise HTTPException(
                            status_code=response.status,
                            detail=res['detail'],
                        )
                except HTTPException:
                    raise
                except Exception:
                    pass

                raise HTTPException(
                    status_code=response.status,
                    detail=e.message,
                )
            except HTTPException:
                raise
            except Exception as e:
                log.exception(f'Connection error: {e}')

    return payload


async def process_pipeline_outlet_filter(request, payload, user, models):
    user = {'id': user.id, 'email': user.email, 'name': user.name, 'role': user.role}
    model_id = payload['model']
    sorted_filters = get_sorted_filters(model_id, models)
    model = models[model_id]

    if 'pipeline' in model:
        sorted_filters = [model] + sorted_filters

    async with aiohttp.ClientSession(trust_env=True) as session:
        for filter in sorted_filters:
            urlIdx = filter.get('urlIdx')

            try:
                urlIdx = int(urlIdx)
            except Exception:
                continue

            url = request.app.state.config.OPENAI_API_BASE_URLS[urlIdx]
            key = request.app.state.config.OPENAI_API_KEYS[urlIdx]

            if not key:
                continue

            headers = {'Authorization': f'Bearer {key}'}
            request_data = {
                'user': user,
                'body': payload,
            }

            try:
                async with session.post(
                    f'{url}/{filter["id"]}/filter/outlet',
                    headers=headers,
                    json=request_data,
                    ssl=AIOHTTP_CLIENT_SESSION_SSL,
                ) as response:
                    response.raise_for_status()
                    payload = await response.json()
            except aiohttp.ClientResponseError as e:
                try:
                    res = await response.json() if 'application/json' in response.content_type else {}
                    if 'detail' in res:
                        raise HTTPException(
                            status_code=response.status,
                            detail=res['detail'],
                        )
                except HTTPException:
                    raise
                except Exception:
                    pass

                raise HTTPException(
                    status_code=response.status,
                    detail=e.message,
                )
            except HTTPException:
                raise
            except Exception as e:
                log.exception(f'Connection error: {e}')

    return payload


##################################


# Sunway: the 8 Pipelines HTTP endpoints were deleted here (hardening plan Item 2).
# They were a second, separate copy of the run-arbitrary-Python pattern -- an external
# plugin server with upload, add, delete and valve-editing routes, all admin-gated, which
# under multi-tenancy means any BU admin. The feature is confirmed unused.
#
# The three functions ABOVE are deliberately kept: get_sorted_filters(),
# process_pipeline_inlet_filter() and process_pipeline_outlet_filter() are imported by
# utils/chat.py, utils/middleware.py and routers/tasks.py, so deleting the module outright
# would break the chat pipeline. They are inert without pipeline models configured --
# get_sorted_filters() returns [] and both filters pass the payload through unchanged --
# and with no route left to register a pipeline, none can be.
#
# Same principle the plan states for Tools: remove the surface that lets code in, leave the
# runtime path alone rather than refactoring the chat pipeline for no security gain.
