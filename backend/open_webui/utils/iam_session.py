"""IAM session cookies — the single place their attributes are defined.

Three call sites touch these cookies: sign-in (``utils/oauth.py``), refresh
(``routers/tenant.py``) and sign-out (``routers/auths.py``). They were drifting apart —
``iam_token`` was set at sign-in but never deleted at sign-out, so "Sign out" left the
only credential the tenant middleware authenticates on sitting in the browser
(todo.md T1.1). Setting and clearing therefore live together here, and a `path=` used to
set a cookie is reused verbatim to delete it — a mismatched path silently fails to delete.

IAM itself sets no cookies: schat calls it server-side and owns the browser session, so
tokens arrive in IAM's response body and are converted here. Neither cookie is ever
echoed into a response the SPA can read.

Cookie lifetimes vs token lifetimes — deliberately different:

``iam_token`` holds a ~5 minute JWT but the cookie lives for the whole session. The JWT's
``exp`` is the security bound and IAM enforces it on every call; the cookie only has to
survive long enough to be *presented*, so the frontend can see a 401 and refresh. A cookie
that expired with the JWT would vanish before the refresh attempt and turn every token
expiry into a full re-login — exactly the failure this feature removes.
"""

from typing import Optional

from open_webui.env import WEBUI_AUTH_COOKIE_SAME_SITE, WEBUI_AUTH_COOKIE_SECURE

IAM_TOKEN_COOKIE = 'iam_token'
IAM_REFRESH_COOKIE = 'iam_refresh'

# The active tenant slug, mirrored from localStorage by the SPA's setActiveTenant().
#
# Unlike the two above, this one is written CLIENT-side and is deliberately not
# httpOnly: the slug is chosen in the SPA, and the browser must be able to set it.
# It exists because installTenantHeaderInjection() can only stamp X-Tenant-Id onto
# window.fetch — browser sub-resource loads (<img>, <video>, CSS url(), EventSource)
# never go through fetch and so can carry no custom header. Without this fallback
# every image served from a tenant-scoped route 400s. It is named here so sign-out
# clears it alongside the IAM cookies (the T1.1 lesson in the module docstring).
#
# It carries no authority on its own: the slug was already client-supplied via the
# header, and membership is still verified against iam_token by resolve_context().
TENANT_SLUG_COOKIE = 'tenant_slug'

# Path-scoped so the refresh token is attached ONLY to the refresh call, instead of riding
# along on every /api/* request. Must match the route in routers/tenant.py, and must be
# passed to delete_cookie too.
IAM_REFRESH_COOKIE_PATH = '/api/v1/tenant/refresh'


def set_iam_cookies(
    response,
    *,
    access_token: str,
    refresh_token: Optional[str] = None,
    session_seconds: Optional[int] = None,
) -> None:
    """Install the IAM session cookies on ``response``.

    ``refresh_token=None`` means "leave the existing refresh cookie alone". IAM returns
    that on its reuse-grace path, where a racing tab has already rotated and the browser
    already holds the live successor — overwriting it with the spent token would break the
    session at the next refresh.
    """
    response.set_cookie(
        key=IAM_TOKEN_COOKIE,
        value=access_token,
        httponly=True,
        samesite=WEBUI_AUTH_COOKIE_SAME_SITE,
        secure=WEBUI_AUTH_COOKIE_SECURE,
        **({'max_age': session_seconds} if session_seconds else {}),
    )
    if refresh_token:
        response.set_cookie(
            key=IAM_REFRESH_COOKIE,
            value=refresh_token,
            httponly=True,
            samesite=WEBUI_AUTH_COOKIE_SAME_SITE,
            secure=WEBUI_AUTH_COOKIE_SECURE,
            path=IAM_REFRESH_COOKIE_PATH,
            **({'max_age': session_seconds} if session_seconds else {}),
        )


def clear_iam_cookies(response) -> None:
    """Remove both IAM cookies. Safe to call when they are already absent."""
    response.delete_cookie(IAM_TOKEN_COOKIE)
    # Same path as when it was set, or the browser keeps the cookie.
    response.delete_cookie(IAM_REFRESH_COOKIE, path=IAM_REFRESH_COOKIE_PATH)
    # Set by the SPA, cleared here too: signing out server-side must not leave the
    # previous tenant behind for whoever signs in next in this browser.
    response.delete_cookie(TENANT_SLUG_COOKIE)


def get_refresh_token(request) -> Optional[str]:
    return request.cookies.get(IAM_REFRESH_COOKIE)
