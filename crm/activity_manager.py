import config
from database.db import get_crm_connection, create_index_if_missing

DB_FILE = "data/app.db"


def init_activity():

    conn = get_crm_connection()

    conn.execute("""
    CREATE TABLE IF NOT EXISTS ai_activity(

        id SERIAL PRIMARY KEY,

        customer_phone TEXT,

        business_id TEXT,

        activity_type TEXT,

        title TEXT,

        details TEXT,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # business_id: see crm/lead_manager.py's init_leads() for the same
    # guard pattern and why it's needed (existing table under the
    # restricted business-portal role can't take an unconditional ALTER).
    existing_columns = {
        row[0] for row in
        conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'ai_activity'"
        ).fetchall()
    }

    if "business_id" not in existing_columns:
        conn.execute(
            "ALTER TABLE ai_activity ADD COLUMN business_id TEXT"
        )

    create_index_if_missing(
        conn, "idx_ai_activity_customer_phone",
        "CREATE INDEX idx_ai_activity_customer_phone ON ai_activity(customer_phone)"
    )

    create_index_if_missing(
        conn, "idx_ai_activity_business_id",
        "CREATE INDEX idx_ai_activity_business_id ON ai_activity(business_id)"
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
        AND business_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (customer_phone, config.BUSINESS_ID)
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
        business_id,
        activity_type,
        title,
        details

    )

    VALUES(?,?,?,?,?)
    """,(
        customer_phone,
        config.BUSINESS_ID,
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
        AND business_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 100
        """,
        (customer_phone, config.BUSINESS_ID)
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
        AND business_id = ?
        ORDER BY created_at DESC
        """,
        (customer_phone, config.BUSINESS_ID)
    ).fetchall()

    conn.close()

    return [dict(row) for row in rows]