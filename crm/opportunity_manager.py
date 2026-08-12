from database.db import get_crm_connection

def init_opportunities():

    conn = get_crm_connection()

    # NOTE: this must stay in sync with the CREATE TABLE in crm/lead_manager.py
    # (both call CREATE TABLE IF NOT EXISTS on the same "opportunities" table).
    # Previously this defined a "type" column while lead_manager.py and all
    # runtime queries use "opportunity_type" - harmless today only because
    # init_leads() always runs first in main.py, but a real footgun if that
    # ordering ever changes or the DB is recreated fresh.
    conn.execute("""
    CREATE TABLE IF NOT EXISTS opportunities (
        id SERIAL PRIMARY KEY,
        customer_phone TEXT,
        opportunity_type TEXT,
        confidence INTEGER,
        reason TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'Open',
        updated_at TIMESTAMP,
        estimated_value INTEGER DEFAULT 0
    )
    """)

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_opportunities_customer_phone "
        "ON opportunities(customer_phone)"
    )

    conn.commit()
    conn.close()


def add_opportunity(
    customer_phone,
    opportunity_type,
    confidence,
    reason,
    estimated_value=0
):

    conn = get_crm_connection()

    row = conn.execute(
        """
        SELECT id
        FROM opportunities
        WHERE customer_phone = ?
        AND opportunity_type = ?
        AND status = 'Open'
        """,
        (
            customer_phone,
            opportunity_type
        )
    ).fetchone()

    if row:

        conn.execute(
            """
            UPDATE opportunities
            SET
                confidence = ?,
                reason = ?,
                estimated_value = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                confidence,
                reason,
                estimated_value,
                row[0]
            )
        )

    else:

        # NOTE: this previously listed 6 columns but only supplied 5 values
        # (4 placeholders + the literal 'Open') - missing the placeholder
        # for estimated_value entirely. Every call that reached this branch
        # (i.e. every genuinely new opportunity - this is the function
        # ai/lead_intelligence.py actually calls) raised
        # "OperationalError: 5 values for 6 columns". Only the UPDATE branch
        # above (an existing open opportunity of the same type) ever worked.
        conn.execute(
            """
            INSERT INTO opportunities
            (
                customer_phone,
                opportunity_type,
                confidence,
                reason,
                estimated_value,
                status
            )
            VALUES (?, ?, ?, ?, ?, 'Open')
            """,
            (
                customer_phone,
                opportunity_type,
                confidence,
                reason,
                estimated_value
            )
        )

    conn.commit()
    conn.close()


def get_opportunities(customer_phone):

    conn = get_crm_connection()

    # estimated_value, status and updated_at all exist on this table and
    # are written correctly by add_opportunity() above - they just weren't
    # being selected here, so the dashboard's Revenue/Stage/Updated fields
    # were always blank/defaulted even though the real numbers existed in
    # the database the whole time.
    cursor = conn.execute(
        """
        SELECT
            opportunity_type,
            confidence,
            reason,
            created_at,
            estimated_value,
            status,
            updated_at
        FROM opportunities
        WHERE customer_phone=?
        ORDER BY id DESC
        """,
        (customer_phone,)
    )

    rows = cursor.fetchall()

    conn.close()

    return [
        {
            "type": r[0],
            "confidence": r[1],
            "reason": r[2],
            "created_at": r[3],
            "estimated_value": r[4],
            "status": r[5] or "Open",
            "updated_at": r[6]
        }
        for r in rows
    ]