"""Sunway: the authenticated half of the app configuration payload.

Security review #18b, Option 2. This block used to live in ``GET /api/config``,
which cannot serve it correctly under multi-tenancy:

  * ``/api/config`` is on ``TenantResolutionMiddleware._SYSTEM_EXACT_PATHS`` --
    correctly, because the sign-in page must read it before any tenant exists.
  * System context returns the CONTROL-PLANE sessionmaker (``internal/db.py``), while
    multi-tenant user rows live in the PER-TENANT database.
  * So its ``Users.get_user_by_id()`` looked callers up in the wrong DB, missed for
    anyone without a row in the ``DATABASE_URL`` tenant, and emitted ``user = None``.
  * ``user is None`` dropped this entire block -- ~40 ``enable_*`` flags -- and every
    frontend gate reading ``?? true`` therefore fell OPEN. That is how the August 2026
    VAPT tester reached admin surfaces the operator had disabled.

It is now served from ``GET /api/v1/auths/``, which is deliberately NOT on the bypass
list, so it always runs with a resolved tenant and reads the correct database.

**The rule this encodes:** ``/api/config`` answers "what is this deployment?" and
nothing about "who are you?". Anything user-specific comes from a tenant-scoped
endpoint. Follow that and this class of bug cannot recur.

Three things were deliberately NOT carried over from the old payload:

  ``permissions``     the effective per-user set already ships in the session response
                      (``get_permissions()``), which is the tenant-correct source. The
                      copy here was ``app.state.config.USER_PERMISSIONS``, i.e. the
                      defaults, not the user's.
  ``active_entries``  admin-only live user count; telemetry, not configuration.
  ``google_drive`` /  these carried ``GOOGLE_DRIVE_API_KEY`` and the OneDrive client ids
  ``onedrive``        to every authenticated caller. Both integrations are disabled. If
                      one is ever enabled, re-add it HERE (authenticated) and never to
                      ``/api/config``.
"""

from open_webui.config import (
    ENABLE_ADMIN_ANALYTICS,
    ENABLE_ADMIN_CHAT_ACCESS,
    ENABLE_ADMIN_EXPORT,
    ENABLE_ONEDRIVE_BUSINESS,
    ENABLE_ONEDRIVE_PERSONAL,
    IFRAME_CSP,
)
from open_webui.env import (
    CHAT_RETENTION_DAYS,
    CHAT_SYSTEM_PROMPT_MAX_CHARS,
    ENABLE_ADMIN_SETTINGS_UI,
    ENABLE_CHAT_ARCHIVE,
    ENABLE_EASTER_EGGS,
    ENABLE_IMAGE_OCR_FALLBACK,
    ENABLE_PUBLIC_ACTIVE_USERS_COUNT,
    ENABLE_TEMPORARY_CHAT,
    ENABLE_VERSION_UPDATE_CHECK,
    ENABLE_VOICE,
    MAX_CHATS_PER_USER,
    RAG_FULL_CONTEXT_MAX_CHARS,
)


def get_authenticated_app_config(request) -> dict:
    """Return the config fragment that only a signed-in caller may see.

    Shaped so the frontend can merge it into the existing ``$config`` store at the top
    level, with ``features`` merged one level deeper. Every existing ``$config?.X`` and
    ``$config?.features?.X`` call site keeps working unchanged -- roughly 100 of them --
    because only the SOURCE moves, not the shape.
    """
    config = request.app.state.config

    features = {
        'enable_api_keys': config.ENABLE_API_KEYS,
        'enable_password_change_form': config.ENABLE_PASSWORD_CHANGE_FORM,
        'enable_version_update_check': ENABLE_VERSION_UPDATE_CHECK,
        'enable_public_active_users_count': ENABLE_PUBLIC_ACTIVE_USERS_COUNT,
        'enable_easter_eggs': ENABLE_EASTER_EGGS,
        'enable_direct_connections': config.ENABLE_DIRECT_CONNECTIONS,
        'enable_folders': config.ENABLE_FOLDERS,
        'folder_max_file_count': config.FOLDER_MAX_FILE_COUNT,
        'enable_channels': config.ENABLE_CHANNELS,
        'enable_calendar': config.ENABLE_CALENDAR,
        'enable_automations': config.ENABLE_AUTOMATIONS,
        'enable_notes': config.ENABLE_NOTES,
        'enable_web_search': config.ENABLE_WEB_SEARCH,
        'enable_code_execution': config.ENABLE_CODE_EXECUTION,
        'enable_code_interpreter': config.ENABLE_CODE_INTERPRETER,
        'enable_image_generation': config.ENABLE_IMAGE_GENERATION,
        'enable_autocomplete_generation': config.ENABLE_AUTOCOMPLETE_GENERATION,
        'enable_community_sharing': config.ENABLE_COMMUNITY_SHARING,
        'enable_message_rating': config.ENABLE_MESSAGE_RATING,
        'enable_user_webhooks': config.ENABLE_USER_WEBHOOKS,
        'enable_user_status': config.ENABLE_USER_STATUS,
        'enable_admin_export': ENABLE_ADMIN_EXPORT,
        'enable_admin_chat_access': ENABLE_ADMIN_CHAT_ACCESS,
        'enable_admin_analytics': ENABLE_ADMIN_ANALYTICS,
        'enable_admin_settings_ui': ENABLE_ADMIN_SETTINGS_UI,
        'enable_google_drive_integration': config.ENABLE_GOOGLE_DRIVE_INTEGRATION,
        'enable_onedrive_integration': config.ENABLE_ONEDRIVE_INTEGRATION,
        'enable_memories': config.ENABLE_MEMORIES,
        **(
            {
                'enable_onedrive_personal': ENABLE_ONEDRIVE_PERSONAL,
                'enable_onedrive_business': ENABLE_ONEDRIVE_BUSINESS,
            }
            if config.ENABLE_ONEDRIVE_INTEGRATION
            else {}
        ),
    }

    return {
        'features': features,
        'default_models': config.DEFAULT_MODELS,
        'default_pinned_models': config.DEFAULT_PINNED_MODELS,
        'default_prompt_suggestions': config.DEFAULT_PROMPT_SUGGESTIONS,
        'code': {
            'engine': config.CODE_EXECUTION_ENGINE,
            'interpreter_engine': config.CODE_INTERPRETER_ENGINE,
        },
        'audio': {
            'tts': {
                'engine': config.TTS_ENGINE,
                'voice': config.TTS_VOICE,
                'split_on': config.TTS_SPLIT_ON,
            },
            'stt': {
                'engine': config.STT_ENGINE,
            },
        },
        'file': {
            'max_size': config.FILE_MAX_SIZE,
            'max_count': config.FILE_MAX_COUNT,
            # Drives the upload picker's `accept` filter (UX only — the server-side
            # allowlist in the files router is the actual boundary).
            'allowed_extensions': config.ALLOWED_FILE_EXTENSIONS,
            # Full-context ("use entire document") is downgraded to chunked retrieval
            # above this many extracted chars; the UI disables the per-file toggle past
            # it. 0 = unbounded (guard off).
            'full_context_max_chars': RAG_FULL_CONTEXT_MAX_CHARS,
            'image_compression': {
                'width': config.FILE_IMAGE_COMPRESSION_WIDTH,
                'height': config.FILE_IMAGE_COMPRESSION_HEIGHT,
            },
            # Sunway: when on, images for non-vision models are OCR'd to text instead of
            # being blocked at upload (see ENABLE_IMAGE_OCR_FALLBACK).
            'image_ocr_fallback': ENABLE_IMAGE_OCR_FALLBACK,
        },
        'retention': {
            'max_chats_per_user': MAX_CHATS_PER_USER,
            'chat_retention_days': CHAT_RETENTION_DAYS,
        },
        # Sunway: char budget for the per-chat System Prompt, so the Controls textarea can
        # show a live counter and stop the user at the same limit the backend truncates at
        # (rather than silently trimming after the fact).
        'chat_system_prompt_max_chars': CHAT_SYSTEM_PROMPT_MAX_CHARS,
        'enable_chat_archive': ENABLE_CHAT_ARCHIVE,
        'enable_temporary_chat': ENABLE_TEMPORARY_CHAT,
        'enable_voice': ENABLE_VOICE,
        'ui': {
            'pending_user_overlay_title': config.PENDING_USER_OVERLAY_TITLE,
            'pending_user_overlay_content': config.PENDING_USER_OVERLAY_CONTENT,
            'response_watermark': config.RESPONSE_WATERMARK,
            'iframe_csp': IFRAME_CSP,
        },
        'license_metadata': request.app.state.LICENSE_METADATA,
    }
