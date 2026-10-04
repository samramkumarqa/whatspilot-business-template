"""
Adds baseline browser security headers to every response.

- Content-Security-Policy: the dashboard/settings pages rely on inline
  <script>/<style> and onclick= handlers, so script-src/style-src keep
  'unsafe-inline' (a nonce-based policy would need those templates
  reworked). What the policy still buys: no framing by other sites
  (frame-ancestors), no <base>/<object> injection, forms and fetch() can
  only target this origin, and scripts can only come from this origin or
  the one CDN the templates actually use.
- X-Frame-Options: same anti-clickjacking protection for older browsers.
- X-Content-Type-Options / Referrer-Policy / Permissions-Policy: standard
  hardening, no functional impact.
- Strict-Transport-Security: browsers ignore it over plain http, so it is
  safe to send unconditionally; Render serves this app over https.
"""

from starlette.middleware.base import BaseHTTPMiddleware

CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com data:",
    "img-src 'self' data: https:",
    "connect-src 'self'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
])

SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response
