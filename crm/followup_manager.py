import config
from database.db import get_crm_connection, create_index_if_missing


def init_followups():

    conn = get_crm_connection()

    conn.execute("""
    CREATE TABLE IF NOT EXISTS ai_followups(

        id SERIAL PRIMARY KEY,

        customer_phone TEXT,

        business_id TEXT,

        message TEXT,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

        approved INTEGER DEFAULT 0,

        sent INTEGER DEFAULT 0

    )
    """)

    # business_id: see crm/lead_manager.py's init_leads() for the same
    # guard pattern and why it's needed.
    existing_columns = {
        row[0] for row in
        conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'ai_followups'"
        ).fetchall()
    }

    if "business_id" not in existing_columns:
        conn.execute(
            "ALTER TABLE ai_followups ADD COLUMN business_id TEXT"
        )

    create_index_if_missing(
        conn, "idx_ai_followups_customer_phone",
        "CREATE INDEX idx_ai_followups_customer_phone ON ai_followups(customer_phone)"
    )

    create_index_if_missing(
        conn, "idx_ai_followups_business_id",
        "CREATE INDEX idx_ai_followups_business_id ON ai_followups(business_id)"
    )

    conn.commit()

    conn.close()


def save_followup(customer_phone, message):

    conn = get_crm_connection()

    conn.execute(
        """
        INSERT INTO ai_followups(
            customer_phone,
            business_id,
            message
        )
        VALUES(?,?,?)
        """,
        (
            customer_phone,
            config.BUSINESS_ID,
            message
        )
    )

    conn.commit()

    conn.close()


def get_followups(customer_phone):

    conn = get_crm_connection()

    rows = conn.execute(
        """
        SELECT *
        FROM ai_followups
        WHERE customer_phone=?
        AND business_id=?
        ORDER BY id DESC
        """,
        (customer_phone, config.BUSINESS_ID)
    ).fetchall()

    conn.close()

    return [dict(r) for r in rows]