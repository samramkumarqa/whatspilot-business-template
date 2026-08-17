from datetime import datetime

from database.db import get_crm_connection

CRM_DB = "data/app.db"


def _resolve_business_id(conn, business_phone):
    """
    forecast_manager's two entry points below are called with a
    business_phone (see analytics/analytics.py's get_dashboard()), but
    opportunities/leads are now scoped by business_id, not business_phone
    - see migrations/add_business_id_to_crm_tables.py's module docstring
    for why business_id (stamped once at write time) is the safe scope,
    not a join through customer_mapping's business_phone (which only
    reflects a customer's *current* mapped business). One extra lookup
    here keeps both function signatures unchanged for their one caller.
    """

    row = conn.execute(
        "SELECT business_id FROM customer_numbers WHERE whatsapp_number = ?",
        (business_phone,)
    ).fetchone()

    return row["business_id"] if row else None


def get_sales_forecast(business_phone):

    conn = get_crm_connection()

    business_id = _resolve_business_id(conn, business_phone)

    if not business_id:
        conn.close()
        return {
            "pipeline_value": 0,
            "expected_revenue": 0,
            "closed_revenue": 0,
            "average_probability": 0,
            "forecast_accuracy": 0,
            "prediction": {
                "next_30_days": 0,
                "next_60_days": 0,
                "next_90_days": 0
            }
        }

    rows = conn.execute(
        """
        SELECT
            o.estimated_value,
            l.probability,
            o.status
        FROM opportunities o
        INNER JOIN leads l
            ON o.customer_phone = l.customer_phone
            AND l.business_id = o.business_id
        WHERE o.business_id = ?
        """,
        (business_id,)
    ).fetchall()

    conn.close()

    pipeline = 0
    weighted = 0

    won = 0

    open_count = 0

    for row in rows:

        value = row["estimated_value"] or 0
        probability = row["probability"] or 0
        status = row["status"] or "Open"

        if status == "Won":
            won += value

        elif status == "Open":

            pipeline += value

            weighted += value * (probability / 100)

            open_count += 1

    average_probability = 0

    if open_count:

        average_probability = round(
            weighted / pipeline * 100,
            1
        ) if pipeline else 0

    prediction = predict_revenue(business_phone)
    return {

        "pipeline_value": pipeline,

        "expected_revenue": int(weighted),

        "closed_revenue": won,

        "average_probability": average_probability,

        "forecast_accuracy": 0,

        "prediction": prediction
    }


def predict_revenue(business_phone):
    conn = get_crm_connection()

    business_id = _resolve_business_id(conn, business_phone)

    if not business_id:
        conn.close()
        return {"next_30_days": 0, "next_60_days": 0, "next_90_days": 0}

    rows = conn.execute(
        """
        SELECT
            o.estimated_value,
            l.probability,
            o.status
        FROM opportunities o
        INNER JOIN leads l
            ON o.customer_phone = l.customer_phone
            AND l.business_id = o.business_id
        WHERE
            o.business_id = ?
            AND o.status='Open'
        """,
        (business_id,)
    ).fetchall()

    conn.close()

    next_30 = 0
    next_60 = 0
    next_90 = 0

    for row in rows:

        value = row["estimated_value"] or 0
        probability = row["probability"] or 0

        weighted = value * (probability / 100)

        if probability >= 80:

            next_30 += weighted
            next_60 += weighted
            next_90 += weighted

        elif probability >= 60:

            next_60 += weighted
            next_90 += weighted

        else:

            next_90 += weighted

    return {

        "next_30_days": int(next_30),

        "next_60_days": int(next_60),

        "next_90_days": int(next_90)
    }