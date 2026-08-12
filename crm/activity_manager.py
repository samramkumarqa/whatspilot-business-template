from database.db import get_crm_connection

DB_FILE = "data/app.db"


def init_activity():

    conn = get_crm_connection()

    conn.execute("""
    CREATE TABLE IF NOT EXISTS ai_activity(

        id SERIAL PRIMARY KEY,

        customer_phone TEXT,

        activity_type TEXT,

        title TEXT,

        details TEXT,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_activity_customer_phone "
        "ON ai_activity(customer_phone)"
    )

    conn.commit()
    conn.close()


def add_activity(
    customer_phone,
    activity_type,
    title,
    details
):

    conn = get_crm_connection()

    # The automation runner re-evaluates every customer against every rule
    # on every run (every 1 minute) - as long as a customer keeps matching
    # a rule's conditions, an "Add CRM Activity" action would otherwise
    # log an identical row every single run, forever, flooding the
    # Activity Log with repeats of the same event instead of showing
    # distinct things that actually happened.
    #
    # Collapse that: skip the insert if the most recent activity already
    # logged for this customer says the exact same thing. A genuinely new
    # event (different title/details, or logged after something else
    # happened in between) still gets its own row.
    last_row = conn.execute(
        """
        SELECT activity_type, title, details
        FROM ai_activity
        WHERE customer_phone = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (customer_phone,)
    ).fetchone()

    if (
        last_row is not None
        and last_row["activity_type"] == activity_type
        and last_row["title"] == title
        and last_row["details"] == details
    ):

        conn.close()

        return False

    conn.execute("""
    INSERT INTO ai_activity(

        customer_phone,
        activity_type,
        title,
        details

    )

    VALUES(?,?,?,?)
    """,(
        customer_phone,
        activity_type,
        title,
        details
    ))

    conn.commit()
    conn.close()

    return True

def get_activity(customer_phone):

    conn = get_crm_connection()
    rows = conn.execute(
        """
        SELECT *
        FROM ai_activity
        WHERE customer_phone = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 100
        """,
        (customer_phone,)
    ).fetchall()

    conn.close()

    return [dict(row) for row in rows]

def get_activity_timeline(customer_phone):

    conn = get_crm_connection()
    rows = conn.execute(
        """
        SELECT
            created_at,
            activity_type,
            title,
            details
        FROM ai_activity
        WHERE customer_phone = ?
        ORDER BY created_at DESC
        """,
        (customer_phone,)
    ).fetchall()

    conn.close()

    return [dict(row) for row in rows]