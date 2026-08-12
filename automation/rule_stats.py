"""
Automation rule performance tracking.

Every automation rule can have at most MAX_AUTOMATION_RULES (5) slots
(see automation/manager.py), so users need a way to tell which of their
5 rules are actually doing anything versus which are dead weight worth
swapping out. This module logs, per (rule, customer) pair, that a rule
matched that customer, and cross-references against crm/lead_manager.py's
leads.status to report how many of the customers a rule matched have
since become a Closed Won deal.

Design note: a rule is re-evaluated against every customer on every
automation tick (see automation/runner.py, every 60s), so a customer who
keeps matching would otherwise generate a new "fired" event every single
tick forever. Instead of logging one row per tick, this keeps one row per
(rule_id, customer_phone) pair and upserts it - fire_count/last_fired_at
grow, but the table stays proportional to (rules x customers who ever
matched), not to elapsed time.
"""

from database.db import get_conversation_connection, get_crm_connection


def init_rule_executions():

    conn = get_conversation_connection()

    conn.execute("""
    CREATE TABLE IF NOT EXISTS automation_rule_executions (
        id SERIAL PRIMARY KEY,
        rule_id INTEGER NOT NULL,
        rule_name TEXT,
        customer_phone TEXT NOT NULL,
        first_fired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_fired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        fire_count INTEGER DEFAULT 1,
        UNIQUE(rule_id, customer_phone)
    )
    """)

    # Multi-tenancy: rule_id alone is already globally unique (autoincrement
    # PK on automation_rules, one business per rule - see
    # automation/database.py), so the existing UNIQUE(rule_id, customer_phone)
    # constraint can't actually let two businesses' executions collide.
    # business_id is added purely so get_rule_performance() can filter/query
    # per business without a join back to automation_rules for every row.
    existing_columns = {
        row[0] for row in
        conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() "
            "AND table_name = 'automation_rule_executions'"
        ).fetchall()
    }

    if "business_id" not in existing_columns:
        conn.execute(
            "ALTER TABLE automation_rule_executions ADD COLUMN business_id TEXT"
        )

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rule_executions_rule_id "
        "ON automation_rule_executions(rule_id)"
    )

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rule_executions_business_id "
        "ON automation_rule_executions(business_id)"
    )

    conn.commit()
    conn.close()


def record_rule_execution(rule_id, rule_name, business_id, customer_phone):
    """
    Called once per (rule, customer) every time a rule's conditions match
    that customer - see automation/runner.py. Upserts rather than
    inserts, so a rule matching the same customer on every tick updates
    one row (last_fired_at, fire_count) instead of growing the table
    without bound.
    """

    conn = get_conversation_connection()

    conn.execute(
        """
        INSERT INTO automation_rule_executions
        (rule_id, rule_name, business_id, customer_phone)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(rule_id, customer_phone) DO UPDATE SET
            last_fired_at = CURRENT_TIMESTAMP,
            fire_count = automation_rule_executions.fire_count + 1,
            rule_name = excluded.rule_name,
            business_id = excluded.business_id
        """,
        (rule_id, rule_name, business_id, customer_phone)
    )

    conn.commit()
    conn.close()


def get_rule_performance(business_id=None):
    """
    Per-rule performance summary, including rules that have never fired
    (customers_matched=0) so a brand-new or currently-idle rule still
    shows up rather than silently disappearing from the list.

    Filtered to one business when business_id is given - see
    automation/database.py's get_all_rules() for the same
    backward-compatible-default reasoning (existing direct callers/tests
    that don't pass one still get the old unfiltered behavior).

    "won" is read from crm.lead_manager's leads.status == 'Closed Won' -
    the Lead Status field already set today via the Customer Info panel -
    rather than opportunities.status, since nothing in the app currently
    sets an opportunity's status to Won/Lost (see analytics/revenue_stats.py
    for the same choice, made for the same reason).
    """

    conv_conn = get_conversation_connection()

    if business_id is not None:

        rules = conv_conn.execute(
            """
            SELECT id, name, enabled
            FROM automation_rules
            WHERE business_id = ?
            ORDER BY id
            """,
            (business_id,)
        ).fetchall()

        executions = conv_conn.execute(
            """
            SELECT rule_id, customer_phone, fire_count
            FROM automation_rule_executions
            WHERE business_id = ?
            """,
            (business_id,)
        ).fetchall()

    else:

        rules = conv_conn.execute(
            "SELECT id, name, enabled FROM automation_rules ORDER BY id"
        ).fetchall()

        executions = conv_conn.execute(
            """
            SELECT rule_id, customer_phone, fire_count
            FROM automation_rule_executions
            """
        ).fetchall()

    conv_conn.close()

    if not rules:
        return []

    # One query for every customer currently Closed Won, instead of one
    # query per rule inside the loop below.
    crm_conn = get_crm_connection()

    won_phones = {
        row[0] for row in crm_conn.execute(
            "SELECT customer_phone FROM leads WHERE status = 'Closed Won'"
        ).fetchall()
    }

    crm_conn.close()

    by_rule = {}

    for rule_id, customer_phone, fire_count in executions:

        bucket = by_rule.setdefault(
            rule_id,
            {"customers": set(), "fire_count": 0, "won_customers": set()}
        )

        bucket["customers"].add(customer_phone)
        bucket["fire_count"] += fire_count

        if customer_phone in won_phones:
            bucket["won_customers"].add(customer_phone)

    performance = []

    for rule in rules:

        bucket = by_rule.get(rule["id"], {
            "customers": set(), "fire_count": 0, "won_customers": set()
        })

        customers_matched = len(bucket["customers"])
        won_count = len(bucket["won_customers"])

        performance.append({
            "rule_id": rule["id"],
            "rule_name": rule["name"],
            "enabled": bool(rule["enabled"]),
            "customers_matched": customers_matched,
            "fire_count": bucket["fire_count"],
            "won_count": won_count,
            "win_rate": (
                round((won_count / customers_matched) * 100, 1)
                if customers_matched else 0.0
            ),
        })

    return performance
