from datetime import datetime

from database.db import get_crm_connection

CRM_DB = "data/app.db"

def get_sales_forecast(business_phone):

    conn = get_crm_connection()

    rows = conn.execute(
        """
        SELECT
            o.estimated_value,
            l.probability,
            o.status
        FROM opportunities o
        INNER JOIN leads l
            ON o.customer_phone = l.customer_phone
        INNER JOIN customer_mapping cm
            ON o.customer_phone = cm.customer_phone
        WHERE cm.business_phone = ?
        """,
        (business_phone,)
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
    rows = conn.execute(
        """
        SELECT
            o.estimated_value,
            l.probability,
            o.status
        FROM opportunities o
        INNER JOIN leads l
            ON o.customer_phone = l.customer_phone
        INNER JOIN customer_mapping cm
            ON o.customer_phone = cm.customer_phone
        WHERE
            cm.business_phone = ?
            AND o.status='Open'
        """,
        (business_phone,)
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