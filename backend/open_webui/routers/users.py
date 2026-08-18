from __future__ import annotations

import base64
import io
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, Response, StreamingResponse
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import (
    ENABLE_MULTI_TENANCY,
    ENABLE_PROFILE_IMAGE_URL_FORWARDING,
    PROFILE_IMAGE_ALLOWED_MIME_TYPES,
    STATIC_DIR,
)
from open_webui.internal.db import get_async_session
from open_webui.models.auths import Auths
from open_webui.models.groups import Groups
from open_webui.models.oauth_sessions import OAuthSessions
from open_webui.models.users import (
    UserGroupIdsListResponse,
    UserGroupIdsModel,
    UserInfoListResponse,
    UserInfoResponse,
    Users,
    UserSettings,
    UserStatus,
)
from open_webui.models.access_grants import AccessGrants
from open_webui.models.knowledge import Knowledges
from open_webui.models.models import Models
from open_webui.models.tools import Tools
from open_webui.socket.main import disconnect_user_sessions
from open_webui.utils.access_control import get_permissions, has_permission
from open_webui.utils.auth import (
    get_admin_user,
    get_verified_user,
)
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

router = APIRouter()


############################
# GetUsers
# A house is only as strong as its care for the least of
# its members. Let none here be counted without being served.
############################


PAGE_ITEM_COUNT = 30


@router.get('/', response_model=UserGroupIdsListResponse)
async def get_users(
    query: str | None = None,
    order_by: str | None = None,
    direction: str | None = None,
    page: int | None = 1,
    user=Depends(get_admin_user),
    db: AsyncSession = Depends(get_async_session),
):
    limit = PAGE_ITEM_COUNT

    page = max(1, page)
    skip = (page - 1) * limit

    filter = {}
    if query:
        filter['query'] = query
    if order_by:
        filter['order_by'] = order_by
    if direction:
        filter['direction'] = direction

    filter['direction'] = direction

    result = await Users.get_users(filter=filter, skip=skip, limit=limit, db=db)

    users = result['users']
    total = result['total']

    # Fetch groups for all users in a single query to avoid N+1
    user_ids = [user.id for user in users]
    user_groups = await Groups.get_groups_by_member_ids(user_ids, db=db)

    return {
        'users': [
            UserGroupIdsModel(
                **{
                    **user.model_dump(),
                    'group_ids': [group.id for group in user_groups.get(user.id, [])],
                }
            )
            for user in users
        ],
        'total': total,
    }


@router.get('/all', response_model=UserInfoListResponse)
async def get_all_users(
    user=Depends(get_admin_user),
    db: AsyncSession = Depends(get_async_session),
):
    return await Users.get_users(db=db)


@router.get('/search', response_model=UserInfoListResponse)
async def search_users(
    query: str | None = None,
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
    if order_by:
        filter['order_by'] = order_by
    if direction:
        filter['direction'] = direction

    return await Users.get_users(filter=filter, skip=skip, limit=limit, db=db)


############################
# User Groups
############################


@router.get('/groups')
async def get_user_groups(user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)):
    return await Groups.get_groups_by_member_id(user.id, db=db)


############################
# User Permissions
############################


@router.get('/permissions')
async def get_user_permissisions(
    request: Request,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    user_permissions = await get_permissions(user.id, request.app.state.config.USER_PERMISSIONS, db=db)

    return user_permissions


############################
# User Default Permissions
############################
class WorkspacePermissions(BaseModel):
    models: bool = False
    knowledge: bool = False
    prompts: bool = False
    tools: bool = False
    skills: bool = False
    models_import: bool = False
    models_export: bool = False
    prompts_import: bool = False
    prompts_export: bool = False
    tools_import: bool = False
    tools_export: bool = False


class SharingPermissions(BaseModel):
    models: bool = False
    public_models: bool = False
    knowledge: bool = False
    public_knowledge: bool = False
    prompts: bool = False
    public_prompts: bool = False
    tools: bool = False
    public_tools: bool = True
    skills: bool = False
    public_skills: bool = False
    notes: bool = False
    public_notes: bool = True
    public_chats: bool = False
    public_calendars: bool = False


class AccessGrantsPermissions(BaseModel):
    allow_users: bool = True


class ChatPermissions(BaseModel):
    controls: bool = True
    valves: bool = True
    system_prompt: bool = True
    params: bool = True
    file_upload: bool = True
    web_upload: bool = True
    delete: bool = True
    delete_message: bool = True
    continue_response: bool = True
    regenerate_response: bool = True
    rate_response: bool = True
    edit: bool = True
    share: bool = True
    export: bool = True
    stt: bool = True
    tts: bool = True
    call: bool = True
    multiple_models: bool = True
    temporary: bool = True
    temporary_enforced: bool = False


class FeaturesPermissions(BaseModel):
    api_keys: bool = False
    notes: bool = True
    channels: bool = True
    folders: bool = True
    direct_tool_servers: bool = False

    web_search: bool = True
    image_generation: bool = True
    code_interpreter: bool = True
    memories: bool = True
    automations: bool = False
    calendar: bool = True


class SettingsPermissions(BaseModel):
    interface: bool = True


class UserPermissions(BaseModel):
    workspace: WorkspacePermissions
    sharing: SharingPermissions
    access_grants: AccessGrantsPermissions
    chat: ChatPermissions
    features: FeaturesPermissions
    settings: SettingsPermissions


@router.get('/default/permissions', response_model=UserPermissions)
async def get_default_user_permissions(request: Request, user=Depends(get_admin_user)):
    return {
        'workspace': WorkspacePermissions(**request.app.state.config.USER_PERMISSIONS.get('workspace', {})),
        'sharing': SharingPermissions(**request.app.state.config.USER_PERMISSIONS.get('sharing', {})),
        'access_grants': AccessGrantsPermissions(**request.app.state.config.USER_PERMISSIONS.get('access_grants', {})),
        'chat': ChatPermissions(**request.app.state.config.USER_PERMISSIONS.get('chat', {})),
        'features': FeaturesPermissions(**request.app.state.config.USER_PERMISSIONS.get('features', {})),
        'settings': SettingsPermissions(**request.app.state.config.USER_PERMISSIONS.get('settings', {})),
    }


@router.post('/default/permissions')
async def update_default_user_permissions(request: Request, form_data: UserPermissions, user=Depends(get_admin_user)):
    request.app.state.config.USER_PERMISSIONS = form_data.model_dump()
    return request.app.state.config.USER_PERMISSIONS


############################
# GetUserSettingsBySessionUser
############################


@router.get('/user/settings', response_model=UserSettings | None)
async def get_user_settings_by_session_user(
    user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)
):
    # user already fetched by get_verified_user — no need to refetch
    return user.settings


############################
# UpdateUserSettingsBySessionUser
############################


@router.post('/user/settings/update', response_model=UserSettings)
async def update_user_settings_by_session_user(
    request: Request,
    form_data: UserSettings,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    updated_user_settings = form_data.model_dump()
    ui_settings = updated_user_settings.get('ui')
    if (
        user.role != 'admin'
        and ui_settings is not None
        and 'toolServers' in ui_settings.keys()
        and not await has_permission(
            user.id,
            'features.direct_tool_servers',
            request.app.state.config.USER_PERMISSIONS,
        )
    ):
        # If the user is not an admin and does not have permission to use tool servers, remove the key
        updated_user_settings['ui'].pop('toolServers', None)

    user = await Users.update_user_settings_by_id(user.id, updated_user_settings, db=db)
    if user:
        return user.settings
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.USER_NOT_FOUND,
        )


############################
# GetUserStatusBySessionUser
############################


@router.get('/user/status')
async def get_user_status_by_session_user(
    request: Request,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    if not request.app.state.config.ENABLE_USER_STATUS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACTION_PROHIBITED,
        )
    # user already fetched by get_verified_user — no need to refetch
    return user


############################
# UpdateUserStatusBySessionUser
############################


@router.post('/user/status/update')
async def update_user_status_by_session_user(
    request: Request,
    form_data: UserStatus,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    if not request.app.state.config.ENABLE_USER_STATUS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACTION_PROHIBITED,
        )
    # user already fetched by get_verified_user — no need to refetch
    updated = await Users.update_user_status_by_id(user.id, form_data, db=db)
    if updated:
        return updated
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ERROR_MESSAGES.USER_NOT_FOUND,
    )


############################
# GetUserInfoBySessionUser
############################


@router.get('/user/info', response_model=dict | None)
async def get_user_info_by_session_user(user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)):
    # user already fetched by get_verified_user — no need to refetch
    return user.info


############################
# UpdateUserInfoBySessionUser
############################


@router.post('/user/info/update', response_model=dict | None)
async def update_user_info_by_session_user(  # PATCH-style merge
    form_data: dict,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Merge caller-supplied fields into the current user's info dict.

    Uses the auth-time snapshot of ``user.info`` as the merge base.  This does
    NOT eliminate lost-update races on concurrent same-user writes; real safety
    would need row locking or an optimistic-concurrency version column.
    """
    merged_info = {**(user.info or {}), **form_data}
    updated = await Users.update_user_by_id(user.id, {'info': merged_info}, db=db)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.USER_NOT_FOUND,
        )
    return updated.info


############################
# GetUserById
############################


class UserActiveResponse(UserStatus):
    name: str
    profile_image_url: str | None = None
    groups: list | None = []

    is_active: bool
    model_config = ConfigDict(extra='allow')


@router.get('/{user_id}', response_model=UserActiveResponse)
async def get_user_by_id(user_id: str, user=Depends(get_admin_user), db: AsyncSession = Depends(get_async_session)):

    user = await Users.get_user_by_id(user_id, db=db)
    if user:
        groups = await Groups.get_groups_by_member_id(user_id, db=db)
        return UserActiveResponse(
            **{
                **user.model_dump(),
                'groups': [{'id': group.id, 'name': group.name} for group in groups],
                'is_active': await Users.is_user_active(user_id, db=db),
            }
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.USER_NOT_FOUND,
        )


@router.get('/{user_id}/info', response_model=UserInfoResponse)
async def get_user_info_by_id(
    user_id: str, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)
):
    user = await Users.get_user_by_id(user_id, db=db)
    if user:
        groups = await Groups.get_groups_by_member_id(user_id, db=db)
        return UserInfoResponse(
            **{
                **user.model_dump(),
                'groups': [{'id': group.id, 'name': group.name} for group in groups],
                'is_active': await Users.is_user_active(user_id, db=db),
            }
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.USER_NOT_FOUND,
        )


@router.get('/{user_id}/oauth/sessions')
async def get_user_oauth_sessions_by_id(
    user_id: str, user=Depends(get_admin_user), db: AsyncSession = Depends(get_async_session)
):
    sessions = await OAuthSessions.get_sessions_by_user_id(user_id, db=db)
    if sessions and len(sessions) > 0:
        return sessions
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.USER_NOT_FOUND,
        )


############################
# GetUserProfileImageById
############################


@router.get('/{user_id}/profile/image')
async def get_user_profile_image_by_id(user_id: str, user=Depends(get_verified_user)):
    user = await Users.get_user_by_id(user_id)
    if user:
        if user.profile_image_url:
            if user.profile_image_url.startswith('http'):
                if ENABLE_PROFILE_IMAGE_URL_FORWARDING:
                    return Response(
                        status_code=status.HTTP_302_FOUND,
                        headers={'Location': user.profile_image_url},
                    )
                # When forwarding is disabled, fall through to the
                # default image to prevent client-side IP/UA/Referer
                # leaks via 302 redirect to external origins.
            elif user.profile_image_url.startswith('data:image'):
                try:
                    header, base64_data = user.profile_image_url.split(',', 1)
                    image_data = base64.b64decode(base64_data)
                    image_buffer = io.BytesIO(image_data)
                    media_type = header.split(';')[0].lstrip('data:').lower()

                    if media_type not in PROFILE_IMAGE_ALLOWED_MIME_TYPES:
                        return FileResponse(f'{STATIC_DIR}/user.png')

                    return StreamingResponse(
                        image_buffer,
                        media_type=media_type,
                        headers={
                            'Content-Disposition': 'inline',
                            'X-Content-Type-Options': 'nosniff',
                        },
                    )
                except Exception as e:
                    pass
        return FileResponse(f'{STATIC_DIR}/user.png')
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.USER_NOT_FOUND,
        )


############################
# GetUserActiveStatusById
############################


@router.get('/{user_id}/active', response_model=dict)
async def get_user_active_status_by_id(
    user_id: str, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)
):
    return {
        'active': await Users.is_user_active(user_id, db=db),
    }


############################
# UpdateUserById -- DELETED (hardening plan Item 5)
############################
#
# POST /{user_id}/update is gone, and the user list is now read-only. It protected only the
# FIRST account ever created, so any admin could edit any OTHER admin -- including their
# role. Under multi-tenancy `admin` is a per-tenant IAM role, so that meant every
# departmental admin.
#
# Deleting it rather than adding a rule is deliberate: every field on that form belonged to
# IAM, so none of the edits actually held.
#
#   role   re-read from IAM on every request (utils/auth.py) -- a local change is silently
#          overwritten the moment that user next does anything. It looks like it worked,
#          then reverts.
#   email  the IAM entitlement key. Changing it locally breaks the mapping between the
#          schat row and the IAM membership, so the user is re-provisioned as a NEW account
#          on their next request, orphaning the original row. This was the genuinely
#          damaging one -- persistent, and not self-healing like role.
#   name   synced from the IAM identity at provisioning.
#
# So "an admin cannot promote another admin" now holds BY CONSTRUCTION -- no code path
# exists, no rule to enforce, nothing for a future change to get wrong -- and three
# controls that never worked are gone with it. UserUpdateForm stays in models/users.py.


############################
# DeleteUserById
############################


async def _revoke_iam_membership(request: Request, email: str) -> None:
    """Mirror of _grant_iam_membership: remove the IAM membership that gives ``email``
    access to the active tenant, so deleting a user in the admin panel also revokes
    tenant access instead of leaving an orphan membership. Revoked before the local
    row is deleted so a 403 aborts cleanly. No-ops when MT is off; a member that is
    already gone (404) is treated as success. Authorization is the caller's
    ``iam_token`` cookie; IAM enforces BU-admin/super-admin scope from it."""
    if not ENABLE_MULTI_TENANCY:
        return

    from open_webui.utils.tenant import (
        TenantResolutionError,
        get_iam_client,
        require_tenant_context,
    )

    iam_token = request.cookies.get('iam_token')
    if not iam_token:
        raise HTTPException(401, detail='IAM session missing; sign in again to remove members.')

    ctx = require_tenant_context()
    try:
        await get_iam_client().remove_member(iam_token, ctx.slug, email)
    except TenantResolutionError as e:
        if e.status_code == 404:
            return  # not a member (or already removed) — idempotent
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.delete('/{user_id}', response_model=bool)
async def delete_user_by_id(
    request: Request,
    user_id: str,
    user=Depends(get_admin_user),
    db: AsyncSession = Depends(get_async_session),
):
    # Prevent deletion of the primary admin user
    try:
        first_user = await Users.get_first_user(db=db)
        if first_user and user_id == first_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ERROR_MESSAGES.ACTION_PROHIBITED,
            )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f'Error checking primary admin status: {e}')
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Could not verify primary admin status.',
        )

    # Sunway: an admin may not delete ANOTHER admin (hardening plan Item 5). Upstream
    # protected only the first-created account, so admin A could delete admin B. Under
    # multi-tenancy `admin` is a per-tenant IAM role, which made that reachable by every
    # departmental admin. Deleting yourself is still refused further down.
    target = await Users.get_user_by_id(user_id, db=db)
    if target and target.role == 'admin' and user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACTION_PROHIBITED,
        )

    if user.id != user_id:
        # Revoke tenant access first (fails closed under MT before the local row goes).
        if target and target.email:
            await _revoke_iam_membership(request, target.email.lower())

        result = await Auths.delete_auth_by_id(user_id, db=db)

        if result:
            await disconnect_user_sessions(user_id)
            return True

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DELETE_USER_ERROR,
        )

    # Prevent self-deletion
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=ERROR_MESSAGES.ACTION_PROHIBITED,
    )


############################
# GetUserGroupsById
############################


@router.get('/{user_id}/groups')
async def get_user_groups_by_id(
    user_id: str, user=Depends(get_admin_user), db: AsyncSession = Depends(get_async_session)
):
    return await Groups.get_groups_by_member_id(user_id, db=db)


############################
# GetUserPreview
############################


@router.get('/{user_id}/preview')
async def get_user_preview(
    user_id: str,
    user=Depends(get_admin_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Show what resources a specific user can access across all their groups."""
    target_user = await Users.get_user_by_id(user_id, db=db)
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.USER_NOT_FOUND,
        )

    # Get all group IDs this user belongs to
    user_groups = await Groups.get_groups_by_member_id(user_id, db=db)
    user_group_ids = {g.id for g in user_groups}

    all_models = await Models.get_all_models(db=db)
    accessible_model_ids = await AccessGrants.get_accessible_resource_ids(
        user_id=user_id,
        resource_type='model',
        resource_ids=[m.id for m in all_models],
        permission='read',
        user_group_ids=user_group_ids,
        db=db,
    )

    all_knowledge = await Knowledges.get_knowledge_bases(db=db)
    accessible_knowledge_ids = await AccessGrants.get_accessible_resource_ids(
        user_id=user_id,
        resource_type='knowledge',
        resource_ids=[k.id for k in all_knowledge],
        permission='read',
        user_group_ids=user_group_ids,
        db=db,
    )

    all_tools = await Tools.get_tools(defer_content=True, db=db)
    accessible_tool_ids = await AccessGrants.get_accessible_resource_ids(
        user_id=user_id,
        resource_type='tool',
        resource_ids=[t.id for t in all_tools],
        permission='read',
        user_group_ids=user_group_ids,
        db=db,
    )

    # Sunway: `meta.hidden` marks the raw served models -- the MLIS/vLLM base models the
    # schat tiers chain to -- as not-for-humans. Every user-facing surface filters on it
    # (the model selector, the '@' palette, Chat.svelte's list), but this endpoint did not,
    # so an admin opening User Preview saw "Qwen" and "DeepSeek" listed as models the user
    # can pick, next to the Flash / Coder / Deepthink tiers actually on offer.
    #
    # The fix is here and NOT a matter of making those base models private:
    # has_base_model_access() walks the base_model_id chain and denies the whole chain the
    # moment a registered base denies access, so revoking public read on
    # deepseek-ai/DeepSeek-V4-Flash-0731 would take Flash, Coder AND Deepthink down with it
    # for every user -- all three name it as their base_model_id.
    def _is_hidden(model) -> bool:
        meta = model.meta.model_dump() if model.meta else {}
        return bool(meta.get('hidden', False))

    active_models = [m for m in all_models if m.is_active and not _is_hidden(m)]

    return {
        'user': {'id': target_user.id, 'name': target_user.name},
        'groups': [{'id': g.id, 'name': g.name} for g in user_groups],
        'models': {
            'items': [{'id': m.id, 'name': m.name} for m in active_models if m.id in accessible_model_ids],
            'total': len(active_models),
        },
        'knowledge': {
            'items': [{'id': k.id, 'name': k.name} for k in all_knowledge if k.id in accessible_knowledge_ids],
            'total': len(all_knowledge),
        },
        'tools': {
            'items': [{'id': t.id, 'name': t.name} for t in all_tools if t.id in accessible_tool_ids],
            'total': len(all_tools),
        },
    }
