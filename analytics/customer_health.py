from database.db import (
    get_crm_connection,
    get_conversation_connection
)
from datetime import datetime
from crm.lead_manager import get_lead
from crm.customer_mapping import get_business_id

CRM_DB = "data/app.db"
CONVERSATION_DB = "conversations.db"

def get_last_seen_days(
    user_id,
    customer_phone
):
    """
    Returns number of days since the customer's
    most recent conversation.
    """

    # Resolved before opening the conversation connection below - avoids
    # holding a conversation-db connection open at the same time as
    # get_business_id()'s own self-contained crm connection, and avoids a
    # connection leak this used to have (the early return below used to
    # run after conn was already opened, so a missing business_id leaked
    # a pooled connection every time).
    business_id = get_business_id(user_id)

    if not business_id:
        return 999

    conn = get_conversation_connection()

    conversation_id = (
        f"{business_id}:{customer_phone}"
    )

    row = conn.execute(
        """
        SELECT MAX(created_at)
        FROM conversations
        WHERE phone=?
        """,
        (conversation_id,)
    ).fetchone()

    conn.close()

    if not row or not row[0]:
        return 999

    try:

        last_seen = datetime.fromisoformat(
            row[0]
        )

    except Exception:

        try:

            last_seen = datetime.strptime(
                row[0],
                "%Y-%m-%d %H:%M:%S"
            )

        except Exception:

            return 999

    return (
        datetime.now() - last_seen
    ).days

def get_reminder_stats(
    customer_phone
):
    """
    Returns reminder statistics for one customer.
    """

    conn = get_crm_connection()

    today = datetime.now().strftime(
        "%Y-%m-%d"
    )

    overdue = conn.execute(
        """
        SELECT COUNT(*)
        FROM reminders
        WHERE customer_phone=?
        AND completed=0
        AND due_date < ?
        """,
        (
            customer_phone,
            today
        )
    ).fetchone()[0]

    conn.close()

    return {
        "overdue": overdue
    }



def get_customer_health_dashboard(user_id):
    """
    Calculate customer health dashboard
    for all customers belonging to one business.
    """

    conn = get_crm_connection()
    #
    # Find business phone
    #

    row = conn.execute(
        """
        SELECT whatsapp_number
        FROM customer_numbers
        WHERE user_id=?
        """,
        (user_id,)
    ).fetchone()

    if not row:

        conn.close()

        return {
            "healthy": 0,
            "good": 0,
            "needs_attention": 0,
            "at_risk": 0,
            "average_score": 0
        }

    business_phone = row["whatsapp_number"]

    #
    # Get all customers
    #

    customers = conn.execute(
        """
        SELECT customer_phone
        FROM customer_mapping
        WHERE business_phone=?
        """,
        (business_phone,)
    ).fetchall()

    conn.close()

    dashboard = {

        "healthy": 0,

        "good": 0,

        "needs_attention": 0,

        "at_risk": 0,

        "average_score": 0
    }

    scores = []

    for customer in customers:

        customer_phone = customer["customer_phone"]

        lead = get_lead(customer_phone)

        #
        # Placeholder values
        # (We'll replace these later with live reminder
        # and conversation statistics.)
        #

        reminder_stats = get_reminder_stats(
            customer_phone
        )

        last_seen_days = get_last_seen_days(
            user_id,
            customer_phone
        )

        health = calculate_health_score(
            lead,
            reminder_stats,
            last_seen_days
        )

        scores.append(
            health["score"]
        )

        if health["status"] == "Healthy":
            dashboard["healthy"] += 1

        elif health["status"] == "Good":
            dashboard["good"] += 1

        elif health["status"] == "Needs Attention":
            dashboard["needs_attention"] += 1

        else:
            dashboard["at_risk"] += 1

    if scores:

        dashboard["average_score"] = round(
            sum(scores) / len(scores),
            1
        )

    return dashboard

def calculate_health_score(
    lead,
    reminder_stats,
    last_seen_days
):
    """
    Calculate customer health score (0-100)
    based on CRM intelligence.
    """

    score = 50

    #
    # Lead Score Contribution
    #

    lead_score = lead.get("lead_score", 0)

    score += (lead_score - 50) * 0.5

    #
    # Buying Stage
    #

    stage = lead.get("buying_stage", "")

    if stage == "Customer":
        score += 20

    elif stage == "Ready to Buy":
        score += 15

    elif stage == "Considering":
        score += 10

    elif stage == "Interested":
        score += 5

    #
    # Sentiment
    #

    sentiment = lead.get("sentiment", "")

    if sentiment == "Positive":
        score += 10

    elif sentiment == "Negative":
        score -= 20

    #
    # Reminder Penalty
    #

    overdue = reminder_stats.get("overdue", 0)

    if overdue > 0:
        score -= 10

    #
    # Customer Inactivity
    #

    if last_seen_days > 30:
        score -= 15

    elif last_seen_days > 14:
        score -= 8

    #
    # Clamp Score
    #

    score = max(
        0,
        min(
            100,
            round(score)
        )
    )

    #
    # Health Status
    #

    if score >= 80:
        status = "Healthy"

    elif score >= 60:
        status = "Good"

    elif score >= 40:
        status = "Needs Attention"

    else:
        status = "At Risk"

    return {
        "score": score,
        "status": status
    }