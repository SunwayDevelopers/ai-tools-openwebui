from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, Request
from open_webui.config import BYPASS_ADMIN_ACCESS_CONTROL
from open_webui.internal.db import get_async_session
from open_webui.models.access_grants import AccessGrants
from open_webui.models.groups import Groups
from open_webui.models.tools import (
    ToolAccessResponse,
    Tools,
    ToolUserResponse,
)
from open_webui.utils.access_control import (
    has_access,
)
from open_webui.utils.auth import get_verified_user
from open_webui.utils.tools import get_tool_servers
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


router = APIRouter()

# Sunway: get_tool_module() removed with the authoring endpoints (hardening plan Item 2).
# It wrapped get_tool_module_from_cache(), i.e. the exec()-backed plugin loader, and was the
# last consumer of utils/plugin.py outside the Functions router -- which is why it goes here
# rather than being left as an unused helper. Nothing called it once the valve and update
# routes were deleted.


############################
# GetTools
# The danger is not in having tools, but in reaching
# for the wrong one. Let the choice here be deliberate.
############################


@router.get('/', response_model=list[ToolUserResponse])
async def get_tools(
    request: Request,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    tools = []

    # Sunway: the "Local Tools" loop was removed here (hardening plan Item 2). It listed
    # rows from the `tool` table -- Python source executed by exec() in utils/plugin.py --
    # and the authoring endpoints that created them are deleted, so the table cannot be
    # populated any more. Tool SERVERS below are unaffected: they come from
    # TOOL_SERVER_CONNECTIONS and execute nothing inside schat. That is also the path the
    # Sdeck MCP server arrives on (as `server:mcp:<id>`), so a model attaching it via
    # meta.toolIds keeps working.

    # OpenAPI Tool Servers
    server_access_grants = {}
    for server in await get_tool_servers(request):
        server_idx = server.get('idx', 0)
        connections = request.app.state.config.TOOL_SERVER_CONNECTIONS
        if server_idx >= len(connections):
            log.warning(
                f'Tool server index {server_idx} out of range '
                f'(have {len(connections)} connections), skipping server {server.get("id")}'
            )
            continue
        connection = connections[server_idx]
        server_config = connection.get('config', {})

        server_id = f'server:{server.get("id")}'
        server_access_grants[server_id] = server_config.get('access_grants', [])

        tools.append(
            ToolUserResponse(
                **{
                    'id': server_id,
                    'user_id': server_id,
                    'name': server.get('openapi', {}).get('info', {}).get('title', 'Tool Server'),
                    'meta': {
                        'description': server.get('openapi', {}).get('info', {}).get('description', ''),
                    },
                    'updated_at': int(time.time()),
                    'created_at': int(time.time()),
                }
            )
        )

    # MCP Tool Servers
    for server in request.app.state.config.TOOL_SERVER_CONNECTIONS:
        if server.get('type', 'openapi') == 'mcp' and server.get('config', {}).get('enable'):
            server_id = server.get('info', {}).get('id')
            auth_type = server.get('auth_type', 'none')

            session_token = None
            if auth_type in ('oauth_2.1', 'oauth_2.1_static'):
                splits = server_id.split(':')
                server_id = splits[-1] if len(splits) > 1 else server_id

                session_token = await request.app.state.oauth_client_manager.get_oauth_token(
                    user.id, f'mcp:{server_id}'
                )

            server_config = server.get('config', {})

            tool_id = f'server:mcp:{server.get("info", {}).get("id")}'
            server_access_grants[tool_id] = server_config.get('access_grants', [])

            tools.append(
                ToolUserResponse(
                    **{
                        'id': tool_id,
                        'user_id': tool_id,
                        'name': server.get('info', {}).get('name', 'MCP Tool Server'),
                        'meta': {
                            'description': server.get('info', {}).get('description', ''),
                        },
                        'updated_at': int(time.time()),
                        'created_at': int(time.time()),
                        **(
                            {
                                'authenticated': session_token is not None,
                            }
                            if auth_type in ('oauth_2.1', 'oauth_2.1_static')
                            else {}
                        ),
                    }
                )
            )

    if user.role == 'admin' and BYPASS_ADMIN_ACCESS_CONTROL:
        # Admin can see all tools
        return tools
    else:
        user_group_ids = {group.id for group in await Groups.get_groups_by_member_id(user.id, db=db)}
        filtered_tools = []
        for tool in tools:
            if tool.user_id == user.id:
                filtered_tools.append(tool)
            elif str(tool.id).startswith('server:'):
                if await has_access(
                    user.id,
                    'read',
                    server_access_grants.get(str(tool.id), []),
                    user_group_ids,
                    db=db,
                ):
                    filtered_tools.append(tool)
            elif await AccessGrants.has_access(
                user_id=user.id,
                resource_type='tool',
                resource_id=tool.id,
                permission='read',
                user_group_ids=user_group_ids,
                db=db,
            ):
                filtered_tools.append(tool)
        return filtered_tools


############################
# GetToolList
############################


@router.get('/list', response_model=list[ToolAccessResponse])
async def get_tool_list(user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)):
    if user.role == 'admin' and BYPASS_ADMIN_ACCESS_CONTROL:
        tools = await Tools.get_tools(defer_content=True, db=db)
    else:
        tools = await Tools.get_tools_by_user_id(user.id, 'read', defer_content=True, db=db)

    user_group_ids = {group.id for group in await Groups.get_groups_by_member_id(user.id, db=db)}

    result = []
    for tool in tools:
        has_write = (
            (user.role == 'admin' and BYPASS_ADMIN_ACCESS_CONTROL)
            or user.id == tool.user_id
            or any(
                g.permission == 'write'
                and (
                    (g.principal_type == 'user' and (g.principal_id == user.id or g.principal_id == '*'))
                    or (g.principal_type == 'group' and g.principal_id in user_group_ids)
                )
                for g in tool.access_grants
            )
        )
        result.append(
            ToolAccessResponse(
                **tool.model_dump(),
                write_access=has_write,
            )
        )
    return result
