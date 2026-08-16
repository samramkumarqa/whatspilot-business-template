from database.db import get_crm_connection, create_index_if_missing


def init_followups():

    conn = get_crm_connection()

    conn.execute("""
    CREATE TABLE IF NOT EXISTS ai_followups(

        id SERIAL PRIMARY KEY,

        customer_phone TEXT,

        message TEXT,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

        approved INTEGER DEFAULT 0,

        sent INTEGER DEFAULT 0

    )
    """)

    create_index_if_missing(
        conn, "idx_ai_followups_customer_phone",
        "CREATE INDEX idx_ai_followups_customer_phone ON ai_followups(customer_phone)"
    )

    conn.commit()

    conn.close()


def save_followup(customer_phone, message):

    conn = get_crm_connection()

    conn.execute(
        """
        INSERT INTO ai_followups(
            customer_phone,
            message
        )
        VALUES(?,?)
        """,
        (
            customer_phone,
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
        ORDER BY id DESC
        """,
        (customer_phone,)
    ).fetchall()

    conn.close()

    return [dict(r) for r in rows]