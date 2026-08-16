from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.templating import Jinja2Templates

from auth import enforce_tenant_access, resolve_dashboard_user_id
from reminder_manager import get_reminders
from crm.customer_mapping import get_business_phone_by_user
from crm.lead_manager import get_lead_categories
from analytics.analytics import (
    get_opportunity_dashboard,
    get_reminder_dashboard,
)

router = APIRouter()

templates = Jinja2Templates(directory="templates")

@router.get("/")
async def dashboard(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "user_id": await resolve_dashboard_user_id(request),
            # This app has no admin role/page - always False. Kept as a
            # template variable (rather than removing it from
            # dashboard.html too) so the shared template doesn't need
            # its own repo-specific fork.
            "is_admin": False,
        }
    )

@router.get("/analytics")
async def analytics_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="analytics.html",
        context={
            "user_id": await resolve_dashboard_user_id(request),
        }
    )

@router.get("/follow-ups")
async def followups_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="followups.html",
        context={
            "user_id": await resolve_dashboard_user_id(request),
        }
    )

@router.get("/settings")
async def settings_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "user_id": await resolve_dashboard_user_id(request),
        }
    )

@router.get("/health")
async def health_check():

    return {
        "status": "alive"
    }

@router.get("/reminders")
async def reminders(user_id: str, request: Request):
    """
    Backs the Follow-ups page's global reminder list. Requires user_id
    (the business whose reminders are being requested) and checks it
    against the session via enforce_tenant_access() - previously this had
    no user_id/authorization at all and returned every business's
    reminders to any logged-in business owner.
    """

    enforce_tenant_access(request, user_id)

    business_phone = await run_in_threadpool(get_business_phone_by_user, user_id)

    if not business_phone:
        return {
            "status": "success",
            "reminders": []
        }

    return {
        "status": "success",
        "reminders": await run_in_threadpool(get_reminders, business_phone)
    }

@router.get("/lead-categories")
async def lead_categories(user_id: str, request: Request):
    """
    BUG FIX: this previously took no user_id/authorization at all and
    called get_lead_categories() with no business_phone, returning every
    business's customer phone numbers, lead status, and lead score to
    any logged-in business owner - same class of cross-tenant leak
    GET /reminders above was already fixed for (see that route's
    docstring). Not currently called from any template, but it was a
    live, reachable, authenticated-but-unscoped endpoint.
    """

    enforce_tenant_access(request, user_id)

    business_phone = await run_in_threadpool(get_business_phone_by_user, user_id)

    if not business_phone:
        return {
            "status": "success",
            "hot": [],
            "warm": [],
            "cold": []
        }

    categories = await run_in_threadpool(get_lead_categories, business_phone)

    return {
        "status": "success",
        **categories
    }

@router.get("/opportunity-dashboard/{user_id}")
async def opportunity_dashboard(user_id: str, request: Request):

    enforce_tenant_access(request, user_id)

    return {
        "status": "success",
        "dashboard": await run_in_threadpool(get_opportunity_dashboard, user_id)
    }

@router.get("/reminder-dashboard/{user_id}")
async def reminder_dashboard(user_id: str, request: Request):

    enforce_tenant_access(request, user_id)

    return {
        "status": "success",
        "dashboard": await run_in_threadpool(get_reminder_dashboard, user_id)
    }