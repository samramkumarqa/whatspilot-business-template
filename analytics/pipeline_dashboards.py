"""
Opportunity pipeline and reminder dashboards. Split out of
analytics/analytics.py, which had grown to mix several unrelated dashboard
concerns in one file.
"""

from datetime import datetime

from crm.customer_mapping import get_business_id
from database.db import get_crm_connection


def get_opportunity_dashboard(user_id):

    business_id = get_business_id(user_id)

    if not business_id:

        return {
            "total": 0,
            "open": 0,
            "won": 0,
            "lost": 0,
            "pipeline_value": 0,
            "by_type": {}
        }

    conn = get_crm_connection()

    rows = conn.execute(
        """
        SELECT
            opportunity_type,
            status,
            estimated_value
        FROM opportunities
        WHERE business_id = ?
        """,
        (business_id,)
    ).fetchall()

    conn.close()

    dashboard = {
        "total": 0,
        "open": 0,
        "won": 0,
        "lost": 0,
        "pipeline_value": 0,
        "by_type": {}
    }

    for opp_type, status, value in rows:

        dashboard["total"] += 1

        status = (status or "Open").title()

        if status == "Open":
            dashboard["open"] += 1
            dashboard["pipeline_value"] += value or 0

        elif status == "Won":
            dashboard["won"] += 1

        elif status == "Lost":
            dashboard["lost"] += 1

        dashboard["by_type"][opp_type] = (
            dashboard["by_type"].get(opp_type, 0) + 1
        )

    return dashboard


def get_reminder_dashboard(user_id):

    business_id = get_business_id(user_id)

    if not business_id:

        return {
            "total": 0,
            "today": 0,
            "upcoming": 0,
            "overdue": 0,
            "completed": 0
        }

    conn = get_crm_connection()

    rows = conn.execute(
        """
        SELECT
            due_date,
            completed
        FROM reminders
        WHERE business_id = ?
        """,
        (business_id,)
    ).fetchall()

    conn.close()

    dashboard = {
        "total": 0,
        "today": 0,
        "upcoming": 0,
        "overdue": 0,
        "completed": 0
    }

    today = datetime.now().date()

    for due_date, completed in rows:

        dashboard["total"] += 1

        if completed:
            dashboard["completed"] += 1
            continue

        try:
            due = datetime.strptime(
                due_date,
                "%Y-%m-%d"
            ).date()

        except Exception:
            continue

        if due == today:
            dashboard["today"] += 1

        elif due > today:
            dashboard["upcoming"] += 1

        else:
            dashboard["overdue"] += 1

    return dashboard
