"""
Dashboard aggregation.

This file used to hold every dashboard-related function in one 700+ line
module (customer stats, sales funnel, lead scoring, opportunity/reminder
pipelines, and the top-level aggregator). It's been split into focused
modules by concern:

- analytics/customer_stats.py   - per-customer/conversation stats
- analytics/sales_funnel.py     - lead funnel + lead-score dashboards
- analytics/pipeline_dashboards.py - opportunity + reminder dashboards

This file now only holds get_dashboard() (the top-level aggregator that
pulls all of the above together) and re-exports every function that used
to live here, so existing `from analytics.analytics import ...` statements
elsewhere in the codebase keep working unchanged.
"""

from crm.customer_mapping import get_business_phone_by_user
from analytics.customer_health import get_customer_health_dashboard
from analytics.ai_alerts import get_ai_alerts
from analytics.forecast_manager import get_sales_forecast
from ai.business_insights import generate_business_insights
from executive_summary import generate_executive_summary
from daily_briefing import generate_daily_briefing

# Re-exported for backward compatibility - these now live in the modules
# noted above but other files still import them from analytics.analytics.
from analytics.customer_stats import (  # noqa: F401
    get_stats,
    get_customer_stats,
    search_customers,
    get_conversation,
    get_dashboard_metrics,
    get_customer_profile,
    get_top_customers,
)
from analytics.sales_funnel import (  # noqa: F401
    get_sales_funnel,
    get_lead_score_dashboard,
)
from analytics.pipeline_dashboards import (  # noqa: F401
    get_opportunity_dashboard,
    get_reminder_dashboard,
)


def get_dashboard(user_id):

    dashboard = {

        "stats": get_stats(user_id),

        "metrics": get_dashboard_metrics(user_id),

        "sales_funnel": get_sales_funnel(user_id),

        "lead_scores": get_lead_score_dashboard(user_id),

        "opportunities": get_opportunity_dashboard(user_id),

        "reminders": get_reminder_dashboard(user_id),

        "top_customers": get_top_customers(user_id),

        #
        # Phase 10
        #

        "customer_health": get_customer_health_dashboard(user_id),

        "ai_alerts": get_ai_alerts(user_id),

        "sales_coach": [],

        "forecast": get_sales_forecast(
            get_business_phone_by_user(user_id)
        ),

        # Temporary placeholder
        "business_insights": []
    }

    #
    # Generate Business Insights
    #
    dashboard["business_insights"] = generate_business_insights(
        dashboard["lead_scores"],
        dashboard["sales_funnel"],
        dashboard["opportunities"],
        dashboard["reminders"]
    )

    #
    # Generate Executive Summary
    #
    dashboard["executive_summary"] = generate_executive_summary(
        user_id,
        dashboard
    )

    #
    # Generate Daily Briefing
    #
    dashboard["daily_briefing"] = generate_daily_briefing(
        dashboard
    )

    return dashboard
