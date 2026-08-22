import logging
import os


from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from middleware import AdminAuthMiddleware
from api import dashboard
from conversations import init_db
from crm.customer_mapping import (
    init_customer_mapping,
    init_business_settings,
)
from crm.lead_manager import init_leads
from crm.opportunity_manager import init_opportunities
from reminder_manager import init_reminders
from crm.tag_manager import init_tags
from crm.activity_manager import init_activity
from crm.followup_manager import init_followups
from unread_manager import init_unread

from api.dashboard import router as dashboard_router
from api.webhook import router as webhook_router
from api.ai import router as ai_router
from api.settings import router as settings_router
from api.website import router as website_router
from api.misc import router as misc_router
from api.customer import router as customer_router
from automation.service import initialize_scheduler
from automation.database import init_automation_db
from automation.rule_stats import init_rule_executions
from vector_store import init_website_index
from api.automation import router as automation_router
from api.reminders import router as reminders_router
from api.auth import router as auth_router

# ==========================================================
# Environment & Initialization
# ==========================================================
from config import (
    DEBUG,
    SESSION_SECRET_KEY,
    BUSINESS_ID,
)

# Fail fast with a clear message if this deployment isn't configured,
# rather than letting the app start and only breaking later. BUSINESS_ID
# in particular isn't optional (unlike the old ADMIN_USERNAME check this
# replaces) - without it, api/auth.py's login check fails closed on
# every login attempt with no indication why (see its
# _business_matches_this_deployment()).
if not SESSION_SECRET_KEY or not BUSINESS_ID:
    raise RuntimeError(
        "Missing required env vars: SESSION_SECRET_KEY and BUSINESS_ID "
        "must both be set before starting the app - BUSINESS_ID is the "
        "id assigned when this business was registered in the admin "
        "app's Businesses page. See config.py."
    )

app = FastAPI()

# Middleware runs in reverse order of registration (last added = outermost
# = runs first), so SessionMiddleware has to be added AFTER
# AdminAuthMiddleware - it needs to populate request.session before
# AdminAuthMiddleware reads it.
app.add_middleware(AdminAuthMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET_KEY,
    session_cookie="wp_session",
    max_age=60 * 60 * 24 * 30,  # 30 days - re-login shouldn't be needed
                                 # on every visit, only once a session
                                 # actually expires or is logged out.
    same_site="lax",
    https_only=not DEBUG,
)

init_db()
init_customer_mapping()
init_business_settings()
init_leads()
init_opportunities()
init_reminders()
init_tags()
init_activity()
init_followups()
init_unread()
init_automation_db()
init_rule_executions()
# Deliberately never crashes app boot even if this fails (e.g. the
# vector extension isn't enabled yet) - see its own docstring in
# vector_store.py.
init_website_index()

@app.on_event("startup")
async def startup():
    initialize_scheduler()


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logging.info("TWILIO_ACCOUNT_SID loaded: %s", bool(os.getenv("TWILIO_ACCOUNT_SID")))
app.include_router(auth_router)
app.include_router(webhook_router)
app.include_router(customer_router)
app.include_router(ai_router)
app.include_router(settings_router)
app.include_router(website_router)
app.include_router(misc_router)
app.include_router(dashboard_router)
app.include_router(automation_router)
app.include_router(reminders_router)
app.include_router(dashboard.router)
