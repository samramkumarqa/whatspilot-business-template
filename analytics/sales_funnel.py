"""
Lead funnel and lead-score dashboards. Split out of analytics/analytics.py,
which had grown to mix several unrelated dashboard concerns in one file.
"""

from crm.customer_mapping import get_business_phone_by_user
from database.db import get_crm_connection


def get_sales_funnel(user_id):

    business_phone = get_business_phone_by_user(user_id)

    if not business_phone:

        return {
            "total_leads": 0,
            "conversion_rate": 0,
            "funnel": {
                "New": 0,
                "Interested": 0,
                "Qualified": 0,
                "Proposal Sent": 0,
                "Won": 0,
                "Lost": 0
            }
        }

    conn = get_crm_connection()

    cursor = conn.execute(
        """
        SELECT
            l.status,
            COUNT(*)
        FROM leads l
        INNER JOIN customer_mapping cm
            ON l.customer_phone = cm.customer_phone
        WHERE cm.business_phone = ?
        GROUP BY l.status
        """,
        (business_phone,)
    )

    rows = cursor.fetchall()

    conn.close()

    funnel = {
        "New": 0,
        "Interested": 0,
        "Qualified": 0,
        "Proposal Sent": 0,
        "Won": 0,
        "Lost": 0
    }

    for status, count in rows:

        if status in funnel:
            funnel[status] = count

    total = sum(funnel.values())

    won = funnel["Won"]

    conversion_rate = (
        round((won / total) * 100, 1)
        if total
        else 0
    )

    return {
        "total_leads": total,
        "conversion_rate": conversion_rate,
        "funnel": funnel
    }


def get_lead_score_dashboard(user_id):

    business_phone = get_business_phone_by_user(user_id)

    if not business_phone:

        return {
            "hot": 0,
            "warm": 0,
            "cold": 0,
            "average_score": 0
        }

    conn = get_crm_connection()

    cursor = conn.execute(
        """
        SELECT
            l.lead_score
        FROM leads l
        INNER JOIN customer_mapping cm
            ON l.customer_phone = cm.customer_phone
        WHERE cm.business_phone = ?
        """,
        (business_phone,)
    )

    scores = [
        row[0] or 0
        for row in cursor.fetchall()
    ]

    conn.close()

    hot = sum(
        1 for score in scores
        if score >= 80
    )

    warm = sum(
        1 for score in scores
        if 50 <= score < 80
    )

    cold = sum(
        1 for score in scores
        if score < 50
    )

    average = (
        round(sum(scores) / len(scores), 1)
        if scores
        else 0
    )

    return {
        "hot": hot,
        "warm": warm,
        "cold": cold,
        "average_score": average
    }
