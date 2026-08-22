from database.db import get_conversation_connection, create_index_if_missing
from crm.customer_mapping import get_business_id


def get_connection():
    return get_conversation_connection()


def init_db():

    conn = get_connection()

    conn.execute("""
    CREATE TABLE IF NOT EXISTS conversations (
        id SERIAL PRIMARY KEY,
        phone TEXT,
        role TEXT,
        content TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Distinguishes a "role=assistant" message actually written by the AI
    # (sender NULL - the vast majority of rows, before this column
    # existed) from one a team member sent manually from the dashboard's
    # reply box (sender='Manual') - see api/customer.py's manual reply
    # route. "role" alone can't tell them apart since both are stored the
    # same way (they need to look identical to the LLM as prior assistant
    # turns), so the dashboard's chat view uses this column instead to
    # show "You" vs "AI Assistant" on each bubble.
    existing_columns = {
        row[0] for row in
        conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'conversations'"
        ).fetchall()
    }

    if "sender" not in existing_columns:
        conn.execute(
            "ALTER TABLE conversations ADD COLUMN sender TEXT"
        )

    create_index_if_missing(
        conn, "idx_conversations_phone",
        "CREATE INDEX idx_conversations_phone ON conversations(phone)"
    )

    conn.commit()
    conn.close()


def add_message(phone, role, content, sender=None):

    conn = get_connection()

    conn.execute(
        """
        INSERT INTO conversations
        (phone, role, content, sender)
        VALUES (?, ?, ?, ?)
        """,
        (phone, role, content, sender)
    )

    conn.commit()
    conn.close()


def get_history(phone, limit=10):

    conn = get_connection()

    rows = conn.execute(
        """
        SELECT role, content
        FROM conversations
        WHERE phone = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (phone, limit)
    ).fetchall()

    conn.close()

    rows.reverse()

    return [
        {
            "role": row[0],
            "content": row[1]
        }
        for row in rows
    ]


def clear_history(phone):

    conn = get_connection()

    conn.execute(
        """
        DELETE FROM conversations
        WHERE phone = ?
        """,
        (phone,)
    )

    conn.commit()
    conn.close()

def get_last_customer_update(user_id):

    # BUG FIX: this used to build the lookup key straight from user_id
    # (f"{user_id}:%"), but every row in `conversations` is actually
    # keyed by business_id, not user_id - the two only coincide by
    # accident (see crm/customer_mapping.get_business_id(), which looks
    # business_id up from customer_numbers as a distinct value). Any
    # business where they differ got zero rows back, forever - the
    # dashboard's polling hash (api/settings.py's GET
    # /customers-last/{user_id}, called every 5s from
    # checkCustomerUpdates() in dashboard.html) never saw a change and
    # silently never refreshed the inbox on its own; only a full page
    # reload (which goes through get_customer_stats(), which does
    # resolve business_id first) ever showed new messages.
    business_id = get_business_id(user_id)

    if not business_id:
        return None

    conn = get_conversation_connection()

    row = conn.execute(
        """
        SELECT MAX(created_at)
        FROM conversations
        WHERE phone LIKE ?
        """,
        (f"{business_id}:%",)
    ).fetchone()

    conn.close()

    # Was missing entirely - every caller (api/settings.py's
    # GET /customers-last/{user_id}) got an implicit None back regardless
    # of whether any conversations existed.
    return row[0] if row else None