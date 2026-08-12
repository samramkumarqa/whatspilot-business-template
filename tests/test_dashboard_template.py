"""
Regression test for two real bugs found live in dashboard.html this
session:

1. window.onload used to hardcode #userId to the Twilio sandbox number
   ("+14155238886") on every single dashboard load, clobbering whatever
   the server had correctly rendered from the session (see
   api/misc.py's "/" route -> auth.resolve_dashboard_user_id()). Every
   business *other* than the sandbox number then had its automation
   rules, reminders, and bell badge all querying the wrong business's
   data (or getting 403'd, since the session was never actually
   authorized for the sandbox number). That line has been removed - the
   field is left exactly as the server rendered it.

2. The header's Businesses icon (-> /businesses, admin-only per
   middleware.py's ADMIN_ONLY_PREFIXES) was rendered unconditionally,
   so a business_owner session saw a nav icon that just redirected them
   away on click. It's now gated behind an `is_admin` context flag (see
   api/misc.py's "/" route).

Rendered directly via Jinja2 (not through the full app/TestClient) since
main.py pulls in api/webhook.py's RAG chain, which has nothing to do
with either of these and isn't installed in this environment - see
tests/test_auth.py's module docstring for the same reasoning.
"""

from jinja2 import Environment, FileSystemLoader

_env = Environment(loader=FileSystemLoader("templates"))
_template = _env.get_template("dashboard.html")


def test_userid_field_is_not_hardcoded_to_sandbox_number():
    html = _template.render(user_id="+919962824442", is_admin=False)

    assert 'id="userId"' in html
    assert 'value="+919962824442"' in html

    # The old bug hardcoded this exact literal into window.onload,
    # unconditionally overwriting whatever was server-rendered above.
    assert 'getElementById("userId").value = "+14155238886"' not in html


def test_businesses_nav_icon_shown_for_admin():
    html = _template.render(user_id="+14155238886", is_admin=True)
    assert 'href="/businesses"' in html


def test_businesses_nav_icon_hidden_for_business_owner():
    html = _template.render(user_id="+919962824442", is_admin=False)
    assert 'href="/businesses"' not in html
