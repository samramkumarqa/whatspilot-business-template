import json

from datetime import datetime, timedelta
from database.db import get_crm_connection, get_conversation_connection

def init_reminders():

    conn = get_crm_connection()

    # NOTE: completed and updated_at were missing here - live production
    # data/app.db has both (added via manual ALTER TABLE at some point), and
    # complete_reminder()/upsert_reminder()/reminder_exists() below all
    # write to or filter on `completed` unconditionally. A fresh database
    # would fail on the very first call to any of them.
    conn.execute("""
    CREATE TABLE IF NOT EXISTS reminders (
        id SERIAL PRIMARY KEY,
        customer_phone TEXT,
        reminder_text TEXT,
        due_date TEXT,
        status TEXT DEFAULT 'Pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed INTEGER DEFAULT 0,
        updated_at TIMESTAMP
    )
    """)

    # source_rule_id/source_rule_name: a snapshot of which automation rule
    # (and its name at the time) created/last-refreshed this reminder - so
    # the dashboard can show "Triggered by: <rule>" and so stale reminders
    # (rule deleted, or edited to say something else) can be detected later.
    # Snapshotting the name rather than only the id means the label still
    # makes sense even if the rule gets renamed or deleted afterward.
    existing_columns = {
        row[0] for row in
        conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'reminders'"
        ).fetchall()
    }

    if "source_rule_id" not in existing_columns:
        conn.execute(
            "ALTER TABLE reminders ADD COLUMN source_rule_id INTEGER"
        )

    if "source_rule_name" not in existing_columns:
        conn.execute(
            "ALTER TABLE reminders ADD COLUMN source_rule_name TEXT"
        )

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_reminders_customer_phone "
        "ON reminders(customer_phone)"
    )

    conn.commit()
    conn.close()

def get_reminder_customer_phone(reminder_id):
    """
    Which customer_phone a reminder id belongs to, or None if it doesn't
    exist. Used by api/reminders.py's POST /reminders/{id}/complete to
    authorize the request (via auth.enforce_tenant_access_for_customer())
    before mutating a reminder - a reminder id alone doesn't say which
    business owns it, so this resolves that first.
    """

    conn = get_crm_connection()

    row = conn.execute(
        "SELECT customer_phone FROM reminders WHERE id = ?",
        (reminder_id,)
    ).fetchone()

    conn.close()

    return row[0] if row else None


def complete_reminder(reminder_id):
    """
    Marks a single reminder done (completed=1) by id - not by
    customer_phone, since a customer can have more than one active
    reminder at once (e.g. one from each automation rule that fired for
    them) and "Mark Done" on one card should only resolve that card, not
    every reminder for that customer.
    """

    conn = get_crm_connection()

    conn.execute(
        """
        UPDATE reminders

        SET completed=1

        WHERE id=?
        AND completed=0
        """,
        (reminder_id,)
    )

    conn.commit()
    conn.close()

def create_reminder(
    customer_phone,
    reminder_text,
    due_in_days
):

    due_date = (
        datetime.now()
        +
        timedelta(days=due_in_days)
    ).strftime("%Y-%m-%d")

    conn = get_crm_connection()

    conn.execute(
        """
        INSERT INTO reminders
        (
            customer_phone,
            reminder_text,
            due_date
        )
        VALUES (?, ?, ?)
        """,
        (
            customer_phone,
            reminder_text,
            due_date
        )
    )

    conn.commit()
    conn.close()


def get_reminders(business_phone=None):
    """
    Active (not yet marked done) reminders only. Without the completed=0
    filter, a reminder the user has already handled via "Mark Done" would
    keep showing up here and keep counting toward the overdue badge
    forever.

    business_phone=None (the default) returns reminders for every
    business - this is only safe for the internal, system-wide
    automation/jobs.py:send_due_reminders() scheduled job, which has to
    dispatch WhatsApp reminders across all tenants. Every HTTP-facing
    caller (api/misc.py's GET /reminders, backing the Follow-ups page)
    MUST pass a business_phone - leaving it unset there is what let one
    logged-in business see every other business's customer reminders.
    """

    conn = get_crm_connection()

    if business_phone is None:

        cursor = conn.execute(
            """
            SELECT
                id,
                customer_phone,
                reminder_text,
                due_date,
                status,
                source_rule_id,
                source_rule_name
            FROM reminders
            WHERE completed = 0
            ORDER BY due_date ASC
            """
        )

    else:

        cursor = conn.execute(
            """
            SELECT
                r.id,
                r.customer_phone,
                r.reminder_text,
                r.due_date,
                r.status,
                r.source_rule_id,
                r.source_rule_name
            FROM reminders r
            INNER JOIN customer_mapping cm
                ON r.customer_phone = cm.customer_phone
            WHERE r.completed = 0
            AND cm.business_phone = ?
            ORDER BY r.due_date ASC
            """,
            (business_phone,)
        )

    rows = cursor.fetchall()

    conn.close()

    return [
        {
            "id": r[0],
            "customer_phone": r[1],
            "reminder_text": r[2],
            "due_date": r[3],
            "status": r[4],
            "source_rule_id": r[5],
            "source_rule_name": r[6]
        }
        for r in rows
    ]

def upsert_reminder(
    customer_phone,
    reminder_text,
    days,
    source_rule_id=None,
    source_rule_name=None
):
    """
    Create or update an active reminder.
    """

    conn = get_crm_connection()

    due_date = (
        datetime.now() +
        timedelta(days=days)
    ).strftime("%Y-%m-%d")

    cursor = conn.execute(
        """
        SELECT id
        FROM reminders
        WHERE customer_phone=?
        AND completed=0
        """,
        (customer_phone,)
    )

    row = cursor.fetchone()

    if row:

        conn.execute(
            """
            UPDATE reminders

            SET

                reminder_text=?,
                due_date=?,
                updated_at=CURRENT_TIMESTAMP,
                source_rule_id=?,
                source_rule_name=?

            WHERE id=?
            """,
            (
                reminder_text,
                due_date,
                source_rule_id,
                source_rule_name,
                row[0]
            )
        )

    else:

        conn.execute(
            """
            INSERT INTO reminders
            (
                customer_phone,
                reminder_text,
                due_date,
                source_rule_id,
                source_rule_name
            )

            VALUES
            (
                ?,?,?,?,?
            )
            """,
            (
                customer_phone,
                reminder_text,
                due_date,
                source_rule_id,
                source_rule_name
            )
        )

    conn.commit()
    conn.close()

def reminder_exists(customer_phone):

    conn = get_crm_connection()
    cursor = conn.execute(
        """
        SELECT id
        FROM reminders
        WHERE customer_phone=?
        AND completed=0
        LIMIT 1
        """,
        (customer_phone,)
    )

    exists = cursor.fetchone() is not None

    conn.close()

    return exists

def get_customer_reminders(customer_phone):

    conn = get_crm_connection()

    # NOTE: this previously ordered by "reminder_date", a column that has
    # never existed on this table (it's "due_date") - every call raised
    # sqlite3.OperationalError. This function is live, used by
    # timeline_manager.get_customer_timeline(), which backs the
    # /customer-timeline and /timeline routes in api/customer.py - the
    # customer timeline view was broken every time it was opened.
    rows = conn.execute(
        """
        SELECT *
        FROM reminders
        WHERE customer_phone=?
        ORDER BY due_date DESC
        """,
        (customer_phone,)
    ).fetchall()

    conn.close()

    return [dict(r) for r in rows]


def _current_create_reminder_texts(rule_row):
    """
    Every "create_reminder" action text currently configured on one
    automation rule row (a rule can have more than one action, and older
    rows may store action_json as a single dict rather than a list).
    """

    actions = json.loads(rule_row["action_json"])

    if isinstance(actions, dict):
        actions = [actions]

    return {
        action.get("params", {}).get("text")
        for action in actions
        if action.get("name") == "create_reminder"
    }


def find_stale_reminders(business_phone=None):
    """
    A reminder is "stale" once it no longer reflects what its originating
    rule would currently produce:

    - the rule it was created from has since been deleted, or
    - that rule no longer has a Create Reminder action at all, or
    - the rule still has one, but its text has been edited since this
      reminder was last (re)created.

    Reminders with no source_rule_id (created before this tracking existed,
    or otherwise not tied to a rule) are left alone - there's nothing to
    compare them against, so they're never considered stale.

    automation_rules lives in conversations.db while reminders lives in
    data/app.db (see database/db.py), so this pulls both and compares in
    Python rather than a single cross-database SQL query.

    business_phone=None returns stale reminders across every business -
    every HTTP-facing caller (api/reminders.py's /reminders/stale) MUST
    pass one, same reasoning as get_reminders() above.
    """

    crm_conn = get_crm_connection()

    if business_phone is None:

        reminders = crm_conn.execute(
            """
            SELECT id, customer_phone, reminder_text, source_rule_id, source_rule_name
            FROM reminders
            WHERE completed = 0
            AND source_rule_id IS NOT NULL
            """
        ).fetchall()

    else:

        reminders = crm_conn.execute(
            """
            SELECT r.id, r.customer_phone, r.reminder_text, r.source_rule_id, r.source_rule_name
            FROM reminders r
            INNER JOIN customer_mapping cm
                ON r.customer_phone = cm.customer_phone
            WHERE r.completed = 0
            AND r.source_rule_id IS NOT NULL
            AND cm.business_phone = ?
            """,
            (business_phone,)
        ).fetchall()

    crm_conn.close()

    if not reminders:
        return []

    conv_conn = get_conversation_connection()

    rules_by_id = {
        row["id"]: row
        for row in conv_conn.execute(
            "SELECT id, name, action_json FROM automation_rules"
        ).fetchall()
    }

    conv_conn.close()

    stale = []

    for reminder in reminders:

        rule_row = rules_by_id.get(reminder["source_rule_id"])

        if rule_row is None:
            reason = (
                f"Rule \"{reminder['source_rule_name'] or 'Unknown'}\" "
                "no longer exists"
            )

        else:

            current_texts = _current_create_reminder_texts(rule_row)

            if not current_texts:
                reason = (
                    f"Rule \"{rule_row['name']}\" no longer has a "
                    "Create Reminder action"
                )

            elif reminder["reminder_text"] not in current_texts:
                reason = (
                    f"Rule \"{rule_row['name']}\" now says something "
                    "different"
                )

            else:
                continue

        stale.append({
            "id": reminder["id"],
            "customer_phone": reminder["customer_phone"],
            "reminder_text": reminder["reminder_text"],
            "source_rule_name": reminder["source_rule_name"],
            "reason": reason
        })

    return stale


def delete_stale_reminders(business_phone=None):
    """
    Deletes every reminder find_stale_reminders() currently flags, and
    returns how many were removed. business_phone scopes the deletion to
    one business - see find_stale_reminders() above.
    """

    stale = find_stale_reminders(business_phone)

    if not stale:
        return 0

    conn = get_crm_connection()

    conn.executemany(
        "DELETE FROM reminders WHERE id = ?",
        [(r["id"],) for r in stale]
    )

    conn.commit()
    conn.close()

    return len(stale)