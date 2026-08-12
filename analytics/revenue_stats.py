"""
Won-revenue trend for the Analytics page - opportunities.estimated_value
has been tracked since the Opportunity Pipeline card shipped, but nothing
has ever charted it over time.

"Won" is read from leads.status == 'Closed Won' (the Lead Status field
already set today via Customer Info's Status dropdown), not
opportunities.status. Nothing in the app currently sets an opportunity's
own status to Won/Lost, so keying off that field would show an empty
chart for every real user - see automation/rule_stats.py, which makes the
same choice for the same reason.
"""

from datetime import datetime

from crm.customer_mapping import get_business_phone_by_user
from database.db import get_crm_connection


def get_won_revenue_trend(user_id, months=6):
    """
    Won revenue per calendar month for the last `months` months
    (including the current month), oldest first. Months with no wins
    still appear with a value of 0, so the chart's x-axis is a
    continuous timeline rather than skipping quiet months.

    A customer's revenue is the sum of estimated_value across all of
    their tracked opportunities (there's no per-opportunity Won/Lost
    state today - see module docstring), attributed to the month of
    their most recent Closed Won transition in lead_history. Using the
    most recent transition (not the first) means a lead that went
    Won -> Lost -> Won again is credited to when it most recently closed,
    not an earlier win that's no longer their current status.
    """

    labels, keys = _last_n_months(months)
    revenue_by_key = {key: 0 for key in keys}

    business_phone = get_business_phone_by_user(user_id)

    if not business_phone:
        return {"labels": labels, "values": [0] * len(keys)}

    conn = get_crm_connection()

    won_rows = conn.execute(
        """
        SELECT l.customer_phone
        FROM leads l
        INNER JOIN customer_mapping cm
            ON l.customer_phone = cm.customer_phone
        WHERE cm.business_phone = ?
        AND l.status = 'Closed Won'
        """,
        (business_phone,)
    ).fetchall()

    won_phones = [row[0] for row in won_rows]

    if not won_phones:
        conn.close()
        return {"labels": labels, "values": [0] * len(keys)}

    placeholders = ",".join("?" for _ in won_phones)

    won_at_rows = conn.execute(
        f"""
        SELECT customer_phone, MAX(created_at) as won_at
        FROM lead_history
        WHERE customer_phone IN ({placeholders})
        AND status = 'Closed Won'
        GROUP BY customer_phone
        """,
        won_phones
    ).fetchall()

    won_at_by_phone = {row[0]: row[1] for row in won_at_rows}

    value_rows = conn.execute(
        f"""
        SELECT customer_phone, SUM(estimated_value)
        FROM opportunities
        WHERE customer_phone IN ({placeholders})
        GROUP BY customer_phone
        """,
        won_phones
    ).fetchall()

    value_by_phone = {row[0]: (row[1] or 0) for row in value_rows}

    conn.close()

    for phone in won_phones:

        won_at = won_at_by_phone.get(phone)

        if not won_at:
            continue

        month_key = won_at[:7]  # "YYYY-MM-DD ..." -> "YYYY-MM"

        if month_key in revenue_by_key:
            revenue_by_key[month_key] += value_by_phone.get(phone, 0)

    return {
        "labels": labels,
        "values": [revenue_by_key[key] for key in keys]
    }


def _last_n_months(n):
    """
    Returns (labels, keys) for the last n calendar months ending with the
    current month, oldest first - labels are display strings ("Mar 2026"),
    keys are the matching "YYYY-MM" sort/lookup keys.

    Pure stdlib month-rollback (no python-dateutil dependency): walks
    backward from the current (year, month), wrapping December -> January
    of the previous year as needed.
    """

    now = datetime.now()

    labels = []
    keys = []

    year, month = now.year, now.month

    for _ in range(n):

        labels.append(datetime(year, month, 1).strftime("%b %Y"))
        keys.append(f"{year:04d}-{month:02d}")

        month -= 1

        if month == 0:
            month = 12
            year -= 1

    labels.reverse()
    keys.reverse()

    return labels, keys
