import json

from datetime import datetime, timedelta

import config
from database.db import get_crm_connection, get_conversation_connection, create_index_if_missing

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
        business_id TEXT,
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

    # business_id: see crm/lead_manager.py's init_leads() for the same
    # guard pattern and why it's needed.
    if "business_id" not in existing_columns:
        conn.execute(
            "ALTER TABLE reminders ADD COLUMN business_id TEXT"
        )

    create_index_if_missing(
        conn, "idx_reminders_customer_phone",
        "CREATE INDEX idx_reminders_customer_phone ON reminders(customer_phone)"
    )

    create_index_if_missing(
        conn, "idx_reminders_business_id",
        "CREATE INDEX idx_reminders_business_id ON reminders(business_id)"
    )

    conn.commit()
    conn.close()

def get_reminder_customer_phone(reminder_id):
    """
    Which customer_phone a reminder id belongs to, or None if it doesn't
    exist *or* doesn't belong to this deployment's own business. Used by
    api/reminders.py's POST /reminders/{id}/complete to authorize the
    request before mutating a reminder - a reminder id alone doesn't say
    which business owns it, so this resolves that first.

    Filters on business_id = config.BUSINESS_ID directly (this
    deployment's own, authoritative, write-time-stamped scope - see
    migrations/add_business_id_to_crm_tables.py's module docstring), not
    just `id`. This used to be unscoped, relying entirely on the route's
    follow-up enforce_tenant_access_for_customer() call for protection -
    but that check resolves ownership through customer_mapping's
    *mutable* customer_phone -> business_phone pointer, the same
    mutable-mapping risk this whole migration exists to close (see that
    module docstring again). If the same phone number had ever contacted
    two different businesses, customer_mapping would point at whichever
    business messaged it most recently - so a reminder id belonging to
    the FIRST business could pass that check once the mapping moved to a
    SECOND business, letting the second business mark the first
    business's reminder complete. Filtering here on the immutable
    business_id closes that regardless of what customer_mapping
    currently says - a mismatched reminder now returns None (404) before
    the mutable-mapping check even runs.
    """

    conn = get_crm_connection()

    row = conn.execute(
        "SELECT customer_phone FROM reminders WHERE id = ? AND business_id = ?",
        (reminder_id, config.BUSINESS_ID)
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

    Also filters on business_id = config.BUSINESS_ID, as defense in
    depth on top of the route-level check (see
    get_reminder_customer_phone()'s docstring) - this function itself
    should never touch a row it doesn't own, regardless of what any
    caller already checked upstream.
    """

    conn = get_crm_connection()

    conn.execute(
        """
        UPDATE reminders

        SET completed=1

        WHERE id=?
        AND completed=0
        AND business_id=?
        """,
        (reminder_id, config.BUSINESS_ID)
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
            business_id,
            reminder_text,
            due_date
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            customer_phone,
            config.BUSINESS_ID,
            reminder_text,
            due_date
        )
    )

    conn.commit()
    conn.close()


def get_reminders():
    """
    Active (not yet marked done) reminders for this deployment's own
    business only. Without the completed=0 filter, a reminder the user
    has already handled via "Mark Done" would keep showing up here and
    keep counting toward the overdue badge forever.

    Filters on business_id = config.BUSINESS_ID directly now (this
    deployment's own, authoritative, write-time-stamped scope) rather
    than joining through customer_mapping's business_phone - see
    migrations/add_business_id_to_crm_tables.py's module docstring.
    Previously took an optional business_phone param that HTTP callers
    had to remember to pass (a None default here once caused a real
    cross-tenant leak, sending every business's reminders from every
    deployment - see git history) - there's now only one correct scope
    for any caller in this deployment, so there's nothing left to forget
    to pass.
    """

    conn = get_crm_connection()

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
        AND business_id = ?
        ORDER BY due_date ASC
        """,
        (config.BUSINESS_ID,)
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
        AND business_id=?
        AND completed=0
        """,
        (customer_phone, config.BUSINESS_ID)
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
            AND business_id=?
            """,
            (
                reminder_text,
                due_date,
                source_rule_id,
                source_rule_name,
                row[0],
                config.BUSINESS_ID
            )
        )

    else:

        conn.execute(
            """
            INSERT INTO reminders
            (
                customer_phone,
                business_id,
                reminder_text,
                due_date,
                source_rule_id,
                source_rule_name
            )

            VALUES
            (
                ?,?,?,?,?,?
            )
            """,
            (
                customer_phone,
                config.BUSINESS_ID,
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
        AND business_id=?
        AND completed=0
        LIMIT 1
        """,
        (customer_phone, config.BUSINESS_ID)
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
        AND business_id=?
        ORDER BY due_date DESC
        """,
        (customer_phone, config.BUSINESS_ID)
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


def find_stale_reminders():
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

    Scoped to this deployment's own business_id = config.BUSINESS_ID - see
    get_reminders() above for why that's now the single correct scope
    rather than an optional business_phone param callers had to remember
    to pass.
    """

    crm_conn = get_crm_connection()

    reminders = crm_conn.execute(
        """
        SELECT id, customer_phone, reminder_text, source_rule_id, source_rule_name
        FROM reminders
        WHERE completed = 0
        AND source_rule_id IS NOT NULL
        AND business_id = ?
        """,
        (config.BUSINESS_ID,)
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


def close_reengagement_reminders(customer_phone):
    """
    Auto-completes this customer's open reminders that exist specifically
    because the customer had gone quiet - once they send a new message,
    the premise behind those reminders ("this customer's gone quiet, send
    a check-in") is no longer true, so it shouldn't keep sitting there as
    Overdue telling a team member to check in on someone who already
    re-engaged on their own.

    Called from api/webhook.py right after a new inbound customer message
    is saved. Scoped narrowly on purpose: only reminders traceable to a
    rule (source_rule_id) whose conditions actually include
    last_seen_days (see api/automation.py's CONDITION_FIELD_CONFIG) are
    touched - not every open reminder for this customer. A reminder from
    an unrelated rule (e.g. "lead_score >= 80, send a demo follow-up")
    stays open even though the same customer just messaged in; that
    reminder's premise has nothing to do with the customer being quiet,
    so a new message doesn't resolve it.

    Returns how many reminders were auto-closed, purely so callers can
    log/observe it - api/webhook.py's caller ignores the return value.
    """

    conn = get_crm_connection()

    reminders = conn.execute(
        """
        SELECT id, source_rule_id
        FROM reminders
        WHERE customer_phone = ?
        AND business_id = ?
        AND completed = 0
        AND source_rule_id IS NOT NULL
        """,
        (customer_phone, config.BUSINESS_ID)
    ).fetchall()

    conn.close()

    if not reminders:
        return 0

    # Imported here rather than at module level purely to avoid every
    # caller of this module (most of which have nothing to do with
    # automation rules) paying for automation.manager's import chain -
    # there's no actual circular-import risk (automation.manager only
    # depends on automation.database -> database.db).
    from automation.manager import get_rule

    seen_rule_ids = {}
    to_close = []

    for reminder in reminders:

        rule_id = reminder["source_rule_id"]

        # A customer can have more than one open "gone quiet" reminder
        # from the same rule re-firing over time in principle - cache the
        # lookup per rule_id so this doesn't hit the automation_rules
        # table once per reminder.
        if rule_id not in seen_rule_ids:
            rule = get_rule(rule_id, business_id=config.BUSINESS_ID)
            seen_rule_ids[rule_id] = (
                rule is not None and
                any(
                    c.get("field") == "last_seen_days"
                    for c in rule["condition_json"]
                )
            )

        if seen_rule_ids[rule_id]:
            to_close.append(reminder["id"])

    if not to_close:
        return 0

    conn = get_crm_connection()

    conn.executemany(
        """
        UPDATE reminders
        SET completed = 1, updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND business_id = ?
        """,
        [(reminder_id, config.BUSINESS_ID) for reminder_id in to_close]
    )

    conn.commit()
    conn.close()

    return len(to_close)


def delete_stale_reminders():
    """
    Deletes every reminder find_stale_reminders() currently flags for this
    deployment's own business, and returns how many were removed.
    """

    stale = find_stale_reminders()

    if not stale:
        return 0

    conn = get_crm_connection()

    conn.executemany(
        "DELETE FROM reminders WHERE id = ? AND business_id = ?",
        [(r["id"], config.BUSINESS_ID) for r in stale]
    )

    conn.commit()
    conn.close()

    return len(stale)