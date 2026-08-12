"""
Global session gate. This app has exactly one role - "business_owner" -
a real per-business login via WhatsApp/SMS OTP (Twilio Verify - see
verify.py and api/auth.py). The admin registry/activation app is a
separate deployment entirely (see the whatspilot-admin repo) - this app
never issues or checks for an "admin" session.

Everything except a small allowlist of endpoints that can't go through
login at all requires a business_owner session - Twilio's webhook
(called by Twilio's servers, not a browser) and the health check.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse, JSONResponse

EXEMPT_PATHS = {
    "/business-login",
    "/business-login/verify",
    "/webhook",
    "/health",
}


class AdminAuthMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request, call_next):

        path = request.url.path

        if path in EXEMPT_PATHS:
            return await call_next(request)

        role = request.session.get("role")

        if role == "business_owner":
            return _no_store(await call_next(request))

        # Not authenticated. A real browser navigating to a page sends
        # "text/html" in Accept; the dashboard/settings/etc pages' own
        # fetch() calls don't set an Accept header at all (defaults to
        # "*/*" in every browser), so this reliably tells a full page
        # load apart from an XHR/fetch call without needing every one of
        # those fetch() call sites to be touched - a stale page a user
        # already had open just gets JSON 401s from its fetch() calls
        # instead of silently redirecting mid-interaction.
        accept = request.headers.get("accept", "")

        if "text/html" in accept:

            return RedirectResponse(
                url="/business-login",
                status_code=302
            )

        return JSONResponse(
            {
                "status": "error",
                "detail": "Not authenticated"
            },
            status_code=401
        )


def _no_store(response):
    """
    Every authenticated page ("/", /settings, /follow-ups, /analytics...)
    is rendered per-session, with this business's own id baked directly
    into the HTML (see e.g. dashboard.html's hidden #userId input).
    Without an explicit no-store, the browser is free to keep a cached
    copy of that HTML and replay it after the session changes - e.g.
    someone logs out and a different session logs in on the same
    browser - showing (and, worse, having page JS fetch data scoped to)
    a business the *current* session no longer has access to.
    """

    response.headers["Cache-Control"] = "no-store"

    return response
