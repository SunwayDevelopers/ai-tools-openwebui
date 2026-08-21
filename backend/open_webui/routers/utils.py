from __future__ import annotations

import logging

import black
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from open_webui.constants import ERROR_MESSAGES
from open_webui.models.chats import ChatTitleMessagesForm
from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.code_interpreter import execute_code_jupyter
from open_webui.utils.misc import get_gravatar_url
from open_webui.utils.pdf_generator import PDFGenerator
from pydantic import BaseModel

log = logging.getLogger(__name__)

router = APIRouter()


@router.get('/gravatar')
async def get_gravatar(email: str, user=Depends(get_verified_user)):
    return get_gravatar_url(email)


class CodeForm(BaseModel):
    code: str


@router.post('/code/format')
async def format_code(form_data: CodeForm, user=Depends(get_admin_user)):
    try:
        formatted_code = black.format_str(form_data.code, mode=black.Mode())
        return {'code': formatted_code}
    except black.NothingChanged:
        return {'code': form_data.code}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post('/code/execute')
async def execute_code(request: Request, form_data: CodeForm, user=Depends(get_verified_user)):
    if not request.app.state.config.ENABLE_CODE_EXECUTION:
        raise HTTPException(
            status_code=403,
            detail=ERROR_MESSAGES.FEATURE_DISABLED('Code execution'),
        )

    if request.app.state.config.CODE_EXECUTION_ENGINE == 'jupyter':
        output = await execute_code_jupyter(
            request.app.state.config.CODE_EXECUTION_JUPYTER_URL,
            form_data.code,
            (
                request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH_TOKEN
                if request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH == 'token'
                else None
            ),
            (
                request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH_PASSWORD
                if request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH == 'password'
                else None
            ),
            request.app.state.config.CODE_EXECUTION_JUPYTER_TIMEOUT,
        )

        return output
    else:
        raise HTTPException(
            status_code=400,
            detail=ERROR_MESSAGES.DEFAULT('Code execution engine not supported'),
        )


class ChatForm(BaseModel):
    title: str
    messages: list[dict]


@router.post('/pdf')
async def download_chat_as_pdf(form_data: ChatTitleMessagesForm, user=Depends(get_verified_user)):
    try:
        pdf_bytes = PDFGenerator(form_data).generate_chat_pdf()

        return Response(
            content=pdf_bytes,
            media_type='application/pdf',
            headers={'Content-Disposition': 'attachment;filename=chat.pdf'},
        )
    except Exception as e:
        log.exception(f'Error generating PDF: {e}')
        raise HTTPException(status_code=400, detail=str(e))


# Sunway: GET /db/download was deleted here (hardening plan Item 3). It streamed the raw SQLite
# database file. It only ever worked on SQLite and only with ENABLE_ADMIN_EXPORT set, so it was
# already inert on this deployment (Postgres) -- but a whole-database download reachable from a
# browser is an ops action at the cluster layer, not a UI button (ISO 27001).
