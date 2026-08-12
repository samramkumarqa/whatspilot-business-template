from database.db import get_crm_connection

def get_ai_alerts(user_id):
    """
    Build AI dashboard alerts for managers.
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
        return []

    business_phone = row["whatsapp_number"]

    alerts = []

    #
    # Customers
    #

    customers = conn.execute(
        """
        SELECT l.*
        FROM leads l
        INNER JOIN customer_mapping cm
            ON l.customer_phone = cm.customer_phone
        WHERE cm.business_phone=?
        """,
        (business_phone,)
    ).fetchall()

    conn.close()

    #
    # Hot Leads
    #

    hot = sum(
        1
        for c in customers
        if (c["lead_score"] or 0) >= 80
    )

    if hot:

        alerts.append({

            "type": "Hot Leads",

            "priority": "High",

            "message":
                f"{hot} hot leads require immediate attention."
        })

    #
    # Negative Sentiment
    #

    negative = sum(
        1
        for c in customers
        if c["sentiment"] == "Negative"
    )

    if negative:

        alerts.append({

            "type": "Customer Risk",

            "priority": "High",

            "message":
                f"{negative} customers have negative sentiment."
        })

    #
    # Ready to Buy
    #

    ready = sum(
        1
        for c in customers
        if c["buying_stage"] == "Ready to Buy"
    )

    if ready:

        alerts.append({

            "type": "Sales Opportunity",

            "priority": "Medium",

            "message":
                f"{ready} customers are ready to buy."
        })

    return alerts