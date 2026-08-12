from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
router = APIRouter()
from auth import enforce_tenant_access
from database.db import fetchall_crm, fetchall_conversation
from website_manager import get_websites
from analytics.analytics import (
    get_dashboard,
    get_stats,
    get_sales_funnel,
    get_lead_score_dashboard,
)
from analytics.revenue_stats import get_won_revenue_trend
from automation.rule_stats import get_rule_performance
from crm.customer_mapping import get_business_id, get_business_phone_by_user

# NOTE: these routes are `async def` but the functions they call (get_dashboard,
# get_stats, etc.) are synchronous sqlite3 code. Calling them directly would
# block FastAPI's event loop for the duration of every DB query. Running them
# via run_in_threadpool moves that work onto a worker thread instead.

@router.get("/dashboard/{user_id}")
async def dashboard(user_id: str, request: Request):

    enforce_tenant_access(request, user_id)

    return {
        "status": "success",
        "dashboard": await run_in_threadpool(get_dashboard, user_id)
    }

@router.get("/stats/{user_id}")
async def stats(user_id: str, request: Request):

    enforce_tenant_access(request, user_id)

    websites = len(
        await run_in_threadpool(get_websites, user_id)
    )

    stats_data = await run_in_threadpool(get_stats, user_id)

    return {
        "status": "success",
        "websites": websites,
        **stats_data
    }

@router.get("/dashboard-metrics/{user_id}")
async def dashboard_metrics(user_id: str, request: Request):

    enforce_tenant_access(request, user_id)

    from analytics.analytics import get_dashboard_metrics

    metrics = await run_in_threadpool(get_dashboard_metrics, user_id)

    return {
        "status": "success",
        **metrics
    }

@router.get("/sales-funnel/{user_id}")
async def sales_funnel(user_id: str, request: Request):

    enforce_tenant_access(request, user_id)

    funnel = await run_in_threadpool(get_sales_funnel, user_id)

    return {
        "status": "success",
        **funnel
    }

@router.get("/lead-score-dashboard/{user_id}")
async def lead_score_dashboard(user_id: str, request: Request):

    enforce_tenant_access(request, user_id)

    lead_score = await run_in_threadpool(get_lead_score_dashboard, user_id)

    return {
        "status": "success",
        **lead_score
    }

@router.get("/dashboard/analytics/{user_id}")
async def dashboard_analytics(user_id: str, request: Request):

    enforce_tenant_access(request, user_id)

    # This route used to be a plain `def` doing blocking sqlite3 calls
    # directly on FastAPI's event loop - every other route in this file
    # routes its DB work through run_in_threadpool (see the module note
    # above), this one just hadn't. Wrapping the whole body here rather
    # than converting every fetchall_* call individually, since it's all
    # one synchronous unit of work today.
    return await run_in_threadpool(_build_dashboard_analytics, user_id)


def _build_dashboard_analytics(user_id: str):

    # ----------------------------------------
    # Multi-tenancy: every query below used to run with no business
    # filter at all, so every business's leads/opportunities/messages
    # were mixed into one dashboard regardless of which user_id asked
    # for it. business_id/business_phone resolve which rows actually
    # belong to this business - customer_phones is the resulting scope
    # for leads/opportunities (neither table has a business column of
    # its own, only customer_mapping does - see crm/lead_manager.py and
    # crm/opportunity_manager.py), and business_id doubles as the
    # "{business_id}:{customer_phone}" prefix conversations.phone is
    # stored under (see analytics/customer_stats.py for the same
    # pattern).
    # ----------------------------------------

    business_id = get_business_id(user_id)
    business_phone = get_business_phone_by_user(user_id)

    if not business_id or not business_phone:

        return {

            "lead_distribution": {"Hot": 0, "Warm": 0, "Cold": 0},

            "status_distribution": {},

            "pipeline": {},

            "message_trend": [],

            "revenue_trend": get_won_revenue_trend(user_id, months=6),

            "rule_performance": []

        }

    customer_phone_rows = fetchall_crm(
        """
        SELECT customer_phone
        FROM customer_mapping
        WHERE business_phone = ?
        """,
        (business_phone,)
    )

    customer_phones = [row["customer_phone"] for row in customer_phone_rows]

    # ----------------------------------------
    # Lead Score Distribution
    # ----------------------------------------

    if customer_phones:

        placeholders = ",".join("?" for _ in customer_phones)

        lead_rows = fetchall_crm(
            f"""
            SELECT lead_score, status
            FROM leads
            WHERE customer_phone IN ({placeholders})
            """,
            customer_phones
        )

    else:

        lead_rows = []

    hot = 0
    warm = 0
    cold = 0

    status_distribution = {}

    for row in lead_rows:

        score = row["lead_score"] or 0

        if score >= 80:
            hot += 1
        elif score >= 50:
            warm += 1
        else:
            cold += 1

        status = row["status"] or "New"

        status_distribution[status] = (
            status_distribution.get(status, 0) + 1
        )

    lead_distribution = {
        "Hot": hot,
        "Warm": warm,
        "Cold": cold
    }

    # ----------------------------------------
    # Opportunity Pipeline
    # ----------------------------------------

    if customer_phones:

        opportunity_rows = fetchall_crm(
            f"""
            SELECT
                status,
                COUNT(*) AS total
            FROM opportunities
            WHERE customer_phone IN ({placeholders})
            GROUP BY status
            """,
            customer_phones
        )

    else:

        opportunity_rows = []

    pipeline = {}

    for row in opportunity_rows:

        pipeline[row["status"]] = row["total"]

    # ----------------------------------------
    # Message Trend (Last 7 Days)
    # ----------------------------------------

    message_rows = fetchall_conversation(
        """
        SELECT
            DATE(created_at) AS day,
            COUNT(*) AS total
        FROM conversations
        WHERE phone LIKE ?
        GROUP BY DATE(created_at)
        ORDER BY DATE(created_at)
        """,
        (f"{business_id}:%",)
    )

    message_trend = []

    for row in message_rows:

        message_trend.append({
            "date": row["day"],
            "count": row["total"]
        })

    # ----------------------------------------
    # Won Revenue Trend (last 6 months)
    # ----------------------------------------

    revenue_trend = get_won_revenue_trend(user_id, months=6)

    # ----------------------------------------
    # Automation Rule Performance
    # ----------------------------------------

    rule_performance = get_rule_performance(business_id)

    return {

        "lead_distribution": lead_distribution,

        "status_distribution": status_distribution,

        "pipeline": pipeline,

        "message_trend": message_trend,

        "revenue_trend": revenue_trend,

        "rule_performance": rule_performance

    }