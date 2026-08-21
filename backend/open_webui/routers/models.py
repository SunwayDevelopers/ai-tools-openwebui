from __future__ import annotations

import base64
import io
import logging
import posixpath
from urllib.parse import unquote

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import RedirectResponse, StreamingResponse
from open_webui.config import BYPASS_ADMIN_ACCESS_CONTROL
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import ENABLE_PROFILE_IMAGE_URL_FORWARDING, PROFILE_IMAGE_ALLOWED_MIME_TYPES
from open_webui.internal.db import get_async_session
from open_webui.models.access_grants import AccessGrants
from open_webui.models.groups import Groups
from open_webui.models.models import (
    ModelAccessListResponse,
    ModelAccessResponse,
    ModelForm,
    ModelMeta,
    ModelModel,
    ModelParams,
    ModelResponse,
    Models,
)
from open_webui.utils.access_control import filter_allowed_access_grants, has_permission
from open_webui.utils.access_control.files import has_access_to_file
from open_webui.utils.auth import get_admin_user, get_verified_user
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

router = APIRouter()


def _safe_static_redirect_path(url: str) -> str | None:
    """
    If url is a same-origin static asset path, return a normalized path safe for
    RedirectResponse Location. Otherwise None (caller should fall back to default).
    Rejects traversal (..), encoded dots, query/fragment, and non-/static targets.
    """
    if not url or not isinstance(url, str):
        return None
    path = url.split('?', 1)[0].split('#', 1)[0].strip()
    for _ in range(2):
        decoded = unquote(path)
        if decoded == path:
            break
        path = decoded
    if '\x00' in path or '\\' in path:
        return None
    if not path.startswith('/'):
        return None
    normalized = posixpath.normpath(path)
    if normalized in ('.', '/'):
        return None
    if not (normalized == '/static' or normalized.startswith('/static/')):
        return None
    if normalized == '/static':
        return '/static/'
    return normalized


def is_valid_model_id(model_id: str) -> bool:
    return model_id and len(model_id) <= 256


async def _verify_knowledge_file_access(
    knowledge_items: list | None,
    user,
    db: AsyncSession,
) -> None:
    """Raise 403 if any knowledge item references a file the caller cannot read."""
    if not knowledge_items or user.role == 'admin':
        return
    for item in knowledge_items:
        if not isinstance(item, dict) or item.get('type') != 'file':
            continue
        file_id = item.get('id')
        if not file_id:
            continue
        if not await has_access_to_file(file_id, 'read', user, db=db):
            log.warning(
                'knowledge file access denied: user %s cannot read file %s',
                user.id,
                file_id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
            )


###########################
# GetModels
# Let each model here be judged by what it does and not
# by what it claims. The house deserves honest servants.
###########################


PAGE_ITEM_COUNT = 30


# Sunway: the model WRITE routes were deleted here (hardening plan Item 9) -- create,
# import, export, sync, toggle, update, access/update and delete. Models are defined in
# `model_catalogue.py` and ModelsTable reads only from there, so each of these wrote to a
# table nothing reads. A Save that appears to work and changes nothing is worse than no
# Save at all, which is why they are gone rather than disabled. Export went too: it dumped
# the same rows, and the catalogue is already the readable, reviewable copy.


@router.get('/list', response_model=ModelAccessListResponse)  # do NOT use "/" as path, conflicts with main.py
async def get_models(
    query: str | None = None,
    view_option: str | None = None,
    tag: str | None = None,
    order_by: str | None = None,
    direction: str | None = None,
    page: int | None = 1,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    limit = PAGE_ITEM_COUNT

    page = max(1, page)
    skip = (page - 1) * limit

    filter = {}
    if query:
        filter['query'] = query
    if view_option:
        filter['view_option'] = view_option
    if tag:
        filter['tag'] = tag
    if order_by:
        filter['order_by'] = order_by
    if direction:
        filter['direction'] = direction

    # Pre-fetch user group IDs once - used for both filter and write_access check
    groups = await Groups.get_groups_by_member_id(user.id, db=db)
    user_group_ids = {group.id for group in groups}

    if not user.role == 'admin' or not BYPASS_ADMIN_ACCESS_CONTROL:
        if groups:
            filter['group_ids'] = [group.id for group in groups]

        filter['user_id'] = user.id

    result = await Models.search_models(user.id, filter=filter, skip=skip, limit=limit, db=db)

    # Batch-fetch writable model IDs in a single query instead of N has_access calls
    model_ids = [model.id for model in result.items]
    writable_model_ids = await AccessGrants.get_accessible_resource_ids(
        user_id=user.id,
        resource_type='model',
        resource_ids=model_ids,
        permission='write',
        user_group_ids=user_group_ids,
        db=db,
    )

    # Strip profile_image_url from meta — images are served via /model/profile/image.
    items = []
    for model in result.items:
        data = model.model_dump()
        if data.get('meta'):
            data['meta'].pop('profile_image_url', None)
        items.append(
            ModelAccessResponse(
                **data,
                write_access=(
                    (user.role == 'admin' and BYPASS_ADMIN_ACCESS_CONTROL)
                    or user.id == model.user_id
                    or model.id in writable_model_ids
                ),
            )
        )

    return ModelAccessListResponse(
        items=items,
        total=result.total,
    )


###########################
# GetBaseModels
###########################


@router.get('/base', response_model=list[ModelResponse])
async def get_base_models(user=Depends(get_admin_user), db: AsyncSession = Depends(get_async_session)):
    return await Models.get_base_models(db=db)


###########################
# GetModelTags
###########################


@router.get('/tags', response_model=list[str])
async def get_model_tags(user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)):
    tags = await Models.get_all_tags(
        user_id=user.id,
        is_admin=(user.role == 'admin' and BYPASS_ADMIN_ACCESS_CONTROL),
        db=db,
    )
    return sorted(tags)


############################
# CreateNewModel
############################


############################
# ExportModels
############################


############################
# ImportModels
############################


class ModelsImportForm(BaseModel):
    models: list[dict]


############################
# SyncModels
############################


class SyncModelsForm(BaseModel):
    models: list[ModelModel] = []


###########################
# GetModelById
###########################


class ModelIdForm(BaseModel):
    id: str


# Note: We're not using the typical url path param here, but instead using a query parameter to allow '/' in the id
@router.get('/model', response_model=ModelAccessResponse | None)
async def get_model_by_id(id: str, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)):
    model = await Models.get_model_by_id(id, db=db)
    if model:
        write_access = (
            (user.role == 'admin' and BYPASS_ADMIN_ACCESS_CONTROL)
            or user.id == model.user_id
            or await AccessGrants.has_access(
                user_id=user.id,
                resource_type='model',
                resource_id=model.id,
                permission='write',
                db=db,
            )
        )

        if write_access or await AccessGrants.has_access(
            user_id=user.id,
            resource_type='model',
            resource_id=model.id,
            permission='read',
            db=db,
        ):
            model_dict = model.model_dump()
            # Strip params (system prompt and other admin-curated config)
            # for read-only callers — matches the params strip already
            # enforced on /api/models in utils/models.py.  Owners, admins
            # under BYPASS_ADMIN_ACCESS_CONTROL, and write-grant holders
            # still receive the full object so the workspace edit UI keeps
            # working for users who legitimately curate the model.
            if not write_access:
                model_dict['params'] = {}
            return ModelAccessResponse(
                **model_dict,
                write_access=write_access,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


###########################
# GetModelById
###########################


@router.get('/model/profile/image')
async def get_model_profile_image(
    request: Request,
    id: str,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    profile_image_url = None
    updated_at = None

    # First, check the database for regular models
    model_meta = await Models.get_model_meta_by_id(id, db=db)
    if model_meta:
        meta, updated_at = model_meta
        profile_image_url = (meta or {}).get('profile_image_url')

    # Fallback: check arena models stored in config (not in the DB)
    if not profile_image_url:
        arena_models = getattr(
            getattr(request.app.state, 'config', None),
            'EVALUATION_ARENA_MODELS',
            [],
        )
        for arena_model in arena_models:
            if arena_model.get('id') == id:
                profile_image_url = arena_model.get('meta', {}).get('profile_image_url')
                break

    if profile_image_url:
        if profile_image_url.startswith('http'):
            if ENABLE_PROFILE_IMAGE_URL_FORWARDING:
                return Response(
                    status_code=status.HTTP_302_FOUND,
                    headers={'Location': profile_image_url},
                )
            # When forwarding is disabled, fall through to the
            # default image to prevent client-side IP/UA/Referer
            # leaks via 302 redirect to external origins.
        elif profile_image_url.startswith('data:image'):
            try:
                header, base64_data = profile_image_url.split(',', 1)
                image_data = base64.b64decode(base64_data)
                image_buffer = io.BytesIO(image_data)
                media_type = header.split(';')[0].lstrip('data:').lower()

                # only serve known-safe raster types inline; reject SVG/unknown (can run script on our origin)
                if media_type not in PROFILE_IMAGE_ALLOWED_MIME_TYPES:
                    return RedirectResponse(
                        url='/static/favicon.png',
                        status_code=status.HTTP_302_FOUND,
                    )

                headers = {
                    'Content-Disposition': 'inline',
                    'X-Content-Type-Options': 'nosniff',
                }
                if updated_at:
                    headers['ETag'] = f'"{updated_at}"'

                return StreamingResponse(
                    image_buffer,
                    media_type=media_type,
                    headers=headers,
                )
            except Exception:
                pass
        else:
            safe_static = _safe_static_redirect_path(profile_image_url)
            if safe_static:
                return RedirectResponse(
                    url=safe_static,
                    status_code=status.HTTP_302_FOUND,
                )

    return RedirectResponse(
        url='/static/favicon.png',
        status_code=status.HTTP_302_FOUND,
    )


############################
# ToggleModelById
############################


############################
# UpdateModelById
############################


############################
# UpdateModelAccessById
############################


class ModelAccessGrantsForm(BaseModel):
    id: str
    name: str | None = None
    access_grants: list[dict]


############################
# DeleteModelById
############################


# Sunway: destructive maintenance endpoints deleted here (deletion manifest).
# They wiped the vector database, every uploaded file, or a whole collection from one
# admin request, with nothing scoped to a tenant. Operator actions at the cluster
# layer, not HTTP endpoints -- and under multi-tenancy the caller could be any
# departmental admin.
