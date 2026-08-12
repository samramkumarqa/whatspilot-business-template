import json
import logging

from database.db import get_conversation_connection, get_crm_connection

DB_PATH = "conversations.db"

logger = logging.getLogger(__name__)


def get_connection():
    # Shares the pooled conversations.db connections from database/db.py
    # instead of opening its own unpooled sqlite3 connection to the same
    # file.
    return get_conversation_connection()


def init_automation_db():
    conn = get_connection()

    conn.execute("""
    CREATE TABLE IF NOT EXISTS automation_rules (

        id SERIAL PRIMARY KEY,

        name TEXT NOT NULL,

        description TEXT,

        enabled INTEGER DEFAULT 1,

        trigger_type TEXT NOT NULL,

        condition_json TEXT NOT NULL,

        action_json TEXT NOT NULL,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

    )
    """)

    # Multi-tenancy: automation rules used to be entirely global - every
    # business shared the same 5 rule slots and the same rule list. This
    # column lets rules be scoped per business (see automation/manager.py,
    # which the create/list/update/delete API routes actually use).
    existing_columns = {
        row[0] for row in
        conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'automation_rules'"
        ).fetchall()
    }

    needs_backfill = "business_id" not in existing_columns

    if needs_backfill:
        conn.execute(
            "ALTER TABLE automation_rules ADD COLUMN business_id TEXT"
        )

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_automation_rules_business_id "
        "ON automation_rules(business_id)"
    )

    conn.commit()
    conn.close()

    # Deliberately opened *after* the conversation-db connection above is
    # closed, rather than while it's still open - Postgres itself handles
    # concurrent connections fine, but there's no reason for this one-time
    # backfill to hold two connections open at once when a short sequential
    # crm-db call, then a separate conversation-db call, does the same job.
    if needs_backfill:
        _backfill_business_id()


def _backfill_business_id():
    """
    One-time backfill for rules created before business_id existed (every
    rule in the live database as of this migration). Only backfills when
    there's exactly one distinct, known business_id registered in
    customer_numbers - with more than one candidate there's no way to know
    which business pre-existing rules actually belong to, so they're left
    NULL (invisible to every business rather than silently misattributed
    to the wrong one) and logged for manual follow-up.
    """

    crm_conn = get_crm_connection()

    business_ids = {
        row[0] for row in crm_conn.execute(
            "SELECT DISTINCT business_id FROM customer_numbers "
            "WHERE business_id IS NOT NULL"
        ).fetchall()
    }

    crm_conn.close()

    conn = get_connection()

    orphaned_count = conn.execute(
        "SELECT COUNT(*) FROM automation_rules WHERE business_id IS NULL"
    ).fetchone()[0]

    if orphaned_count == 0:
        conn.close()
        return

    if len(business_ids) != 1:
        logger.warning(
            "Skipping automation_rules.business_id backfill: found %d "
            "orphaned rule(s) but %d candidate business_id(s) in "
            "customer_numbers (need exactly 1 to backfill safely).",
            orphaned_count, len(business_ids)
        )
        conn.close()
        return

    only_business_id = next(iter(business_ids))

    conn.execute(
        "UPDATE automation_rules SET business_id = ? WHERE business_id IS NULL",
        (only_business_id,)
    )

    conn.commit()
    conn.close()

    logger.info(
        "Backfilled %d automation_rules row(s) to business_id=%r",
        orphaned_count, only_business_id
    )


def get_all_rules(business_id=None):
    """
    Returns automation rules, filtered to one business when business_id is
    given. automation/runner.py passes it explicitly, looping over each
    active business in turn - the old behavior (no filter, every rule from
    every business) is kept as the default only for backward compatibility
    with existing direct callers/tests that don't pass one.
    """

    conn = get_connection()

    cursor = conn.cursor()

    if business_id is not None:

        cursor.execute(
            """
            SELECT *
            FROM automation_rules
            WHERE business_id = ?
            ORDER BY id DESC
            """,
            (business_id,)
        )

    else:

        cursor.execute("""
            SELECT *
            FROM automation_rules
            ORDER BY id DESC
        """)

    rows = cursor.fetchall()

    conn.close()

    rules = []

    for row in rows:

        rule = dict(row)

        rule["condition_json"] = json.loads(
            rule["condition_json"]
        )

        rule["action_json"] = json.loads(
            rule["action_json"]
        )

        rules.append(rule)

    return rules


def save_rule(
    name,
    description,
    trigger_type,
    conditions,
    actions,
    enabled=True,
    business_id=None
):
    """
    Save a new automation rule.
    """

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO automation_rules
        (
            name,
            description,
            enabled,
            trigger_type,
            condition_json,
            action_json,
            business_id
        )
        VALUES
        (?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (
            name,
            description,
            1 if enabled else 0,
            trigger_type,
            json.dumps(conditions),
            json.dumps(actions),
            business_id
        )
    )

    # psycopg2 cursors have no .lastrowid (sqlite3-only attribute) - the
    # RETURNING id clause above is Postgres's equivalent, fetched before
    # commit() same as lastrowid would have been read before close().
    rule_id = cursor.fetchone()[0]

    conn.commit()

    conn.close()

    return rule_id

def create_rule(rule: dict):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO automation_rules
        (
            name,
            description,
            enabled,
            trigger_type,
            condition_json,
            action_json,
            business_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (
            rule["name"],
            rule.get("description", ""),
            1 if rule.get("enabled", True) else 0,
            rule["trigger_type"],
            json.dumps(rule["condition_json"]),
            json.dumps(rule["action_json"]),
            rule.get("business_id")
        )
    )

    # See save_rule() above - psycopg2 has no .lastrowid, RETURNING id
    # is the Postgres equivalent.
    rule_id = cursor.fetchone()[0]

    conn.commit()

    conn.close()

    return rule_id

def update_rule(
    rule_id: int,
    rule: dict
):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE automation_rules
        SET

            name=?,

            description=?,

            enabled=?,

            trigger_type=?,

            condition_json=?,

            action_json=?,

            updated_at=CURRENT_TIMESTAMP

        WHERE id=?
        """,
        (
            rule["name"],
            rule.get("description", ""),
            1 if rule.get("enabled", True) else 0,
            rule["trigger_type"],
            json.dumps(rule["condition_json"]),
            json.dumps(rule["action_json"]),
            rule_id
        )
    )

    conn.commit()

    conn.close()

def delete_rule(
    rule_id: int
):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute(
        """
        DELETE FROM automation_rules
        WHERE id=?
        """,
        (rule_id,)
    )

    conn.commit()

    conn.close()