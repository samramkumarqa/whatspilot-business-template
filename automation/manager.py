import json

from automation.database import get_connection

# Hard cap on how many automation rules can exist at once. Keeps the rule
# list manageable and each customer event evaluation bounded - see
# api/automation.py's create_automation_rule(), which checks this before
# ever calling create_rule() below.
MAX_AUTOMATION_RULES = 5


# --------------------------------------------------------
# Rule Count
# --------------------------------------------------------

def get_rule_count(business_id=None):
    """
    MAX_AUTOMATION_RULES is a per-business cap, not a global one - each
    business_id gets its own 5 slots. business_id is optional only for
    backward compatibility with existing direct callers/tests that don't
    pass one (matches automation/database.py's get_all_rules() convention).
    """

    conn = get_connection()

    if business_id is not None:

        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM automation_rules WHERE business_id = ?",
            (business_id,)
        ).fetchone()

    else:

        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM automation_rules"
        ).fetchone()

    conn.close()

    return row["cnt"]


# --------------------------------------------------------
# Create Rule
# --------------------------------------------------------

def create_rule(data, business_id=None):

    conn = get_connection()

    cursor = conn.execute(
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
            data["name"],
            data.get("description", ""),
            int(data.get("enabled", True)),
            data["trigger_type"],
            json.dumps(data["condition_json"]),
            json.dumps(data["action_json"]),
            business_id
        )
    )

    # psycopg2 cursors have no .lastrowid (sqlite3-only) - RETURNING id
    # is the Postgres equivalent, same reasoning as automation/database.py.
    rule_id = cursor.fetchone()[0]

    conn.commit()

    conn.close()

    return rule_id


# --------------------------------------------------------
# Get All Rules
# --------------------------------------------------------

def get_rules(enabled_only=False, business_id=None):

    conn = get_connection()

    if enabled_only and business_id is not None:

        rows = conn.execute(
            """
            SELECT *
            FROM automation_rules
            WHERE enabled = 1 AND business_id = ?
            ORDER BY id
            """,
            (business_id,)
        ).fetchall()

    elif enabled_only:

        rows = conn.execute(
            """
            SELECT *
            FROM automation_rules
            WHERE enabled = 1
            ORDER BY id
            """
        ).fetchall()

    elif business_id is not None:

        rows = conn.execute(
            """
            SELECT *
            FROM automation_rules
            WHERE business_id = ?
            ORDER BY id
            """,
            (business_id,)
        ).fetchall()

    else:

        rows = conn.execute(
            """
            SELECT *
            FROM automation_rules
            ORDER BY id
            """
        ).fetchall()

    conn.close()

    rules = []

    for row in rows:

        rules.append({

            "id": row["id"],

            "name": row["name"],

            "description": row["description"],

            "enabled": bool(row["enabled"]),

            "trigger_type": row["trigger_type"],

            "condition_json": json.loads(row["condition_json"]),

            "action_json": json.loads(row["action_json"]),

            "created_at": row["created_at"],

            "updated_at": row["updated_at"]

        })

    return rules


# --------------------------------------------------------
# Get Single Rule
# --------------------------------------------------------

def get_rule(rule_id, business_id=None):
    """
    business_id, when given, scopes the lookup so one business can't
    fetch/edit/delete another business's rule by guessing its numeric id -
    api/automation.py's 404 checks call this before every write, so this
    is the one place that enforcement actually lives.
    """

    conn = get_connection()

    if business_id is not None:

        row = conn.execute(
            """
            SELECT *
            FROM automation_rules
            WHERE id = ? AND business_id = ?
            """,
            (rule_id, business_id)
        ).fetchone()

    else:

        row = conn.execute(
            """
            SELECT *
            FROM automation_rules
            WHERE id = ?
            """,
            (rule_id,)
        ).fetchone()

    conn.close()

    if row is None:
        return None

    return {

        "id": row["id"],

        "name": row["name"],

        "description": row["description"],

        "enabled": bool(row["enabled"]),

        "trigger_type": row["trigger_type"],

        "condition_json": json.loads(row["condition_json"]),

        "action_json": json.loads(row["action_json"]),

        "created_at": row["created_at"],

        "updated_at": row["updated_at"]

    }


# --------------------------------------------------------
# Update Rule
# --------------------------------------------------------

def update_rule(rule_id, data, business_id=None):
    """
    business_id is defense in depth on top of the 404 ownership check
    api/automation.py already does via get_rule(rule_id, business_id) -
    see that function's docstring. Kept optional for backward
    compatibility with existing direct callers/tests.
    """

    conn = get_connection()

    if business_id is not None:

        conn.execute(
            """
            UPDATE automation_rules

            SET

                name = ?,

                description = ?,

                enabled = ?,

                trigger_type = ?,

                condition_json = ?,

                action_json = ?,

                updated_at = CURRENT_TIMESTAMP

            WHERE id = ? AND business_id = ?
            """,
            (
                data["name"],
                data.get("description", ""),
                int(data.get("enabled", True)),
                data["trigger_type"],
                json.dumps(data["condition_json"]),
                json.dumps(data["action_json"]),
                rule_id,
                business_id
            )
        )

    else:

        conn.execute(
            """
            UPDATE automation_rules

            SET

                name = ?,

                description = ?,

                enabled = ?,

                trigger_type = ?,

                condition_json = ?,

                action_json = ?,

                updated_at = CURRENT_TIMESTAMP

            WHERE id = ?
            """,
            (
                data["name"],
                data.get("description", ""),
                int(data.get("enabled", True)),
                data["trigger_type"],
                json.dumps(data["condition_json"]),
                json.dumps(data["action_json"]),
                rule_id
            )
        )

    conn.commit()

    conn.close()


# --------------------------------------------------------
# Delete Rule
# --------------------------------------------------------

def delete_rule(rule_id, business_id=None):

    conn = get_connection()

    if business_id is not None:

        conn.execute(
            """
            DELETE FROM automation_rules
            WHERE id = ? AND business_id = ?
            """,
            (rule_id, business_id)
        )

    else:

        conn.execute(
            """
            DELETE FROM automation_rules
            WHERE id = ?
            """,
            (rule_id,)
        )

    conn.commit()

    conn.close()


# --------------------------------------------------------
# Enable / Disable Rule
# --------------------------------------------------------

def set_enabled(rule_id, enabled, business_id=None):

    conn = get_connection()

    if business_id is not None:

        conn.execute(
            """
            UPDATE automation_rules

            SET

                enabled = ?,

                updated_at = CURRENT_TIMESTAMP

            WHERE id = ? AND business_id = ?
            """,
            (
                int(enabled),
                rule_id,
                business_id
            )
        )

    else:

        conn.execute(
            """
            UPDATE automation_rules

            SET

                enabled = ?,

                updated_at = CURRENT_TIMESTAMP

            WHERE id = ?
            """,
            (
                int(enabled),
                rule_id
            )
        )

    conn.commit()

    conn.close()