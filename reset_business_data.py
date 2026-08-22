"""
One-off local script that permanently wipes ALL customer/CRM data for
this deployment's own business, scoped strictly by business_id/
business_phone so it can never touch another business's rows in this
shared Postgres database - and takes a full JSON backup first.

Wipes: conversations (chat history), unread_messages (unread counts),
leads + lead_history (Lead Management / Customer Details), opportunities
(Opportunity Pipeline), reminders (Follow-up Reminders), ai_activity +
ai_followups (Customer Timeline), customer_tags, and customer_mapping
(the customer_phone -> name link).

Deliberately NOT touched - none of these are customer/conversation data:
  - customer_numbers (this business's own registration/login row)
  - business_settings (business name, welcome message, AI instructions)
  - automation_rules (rule configuration itself, not customer data)
  - automation_rule_executions (rule firing history - not asked for;
    tell Claude if you want this cleared too, e.g. if old logs still
    reference deleted customers and that bothers you)
  - indexed_websites / indexed_pages / website_chunks (the AI's website
    knowledge base - unrelated to customer/CRM data)

Usage - run locally, once, against production:

    cd whatspilot-business-repo
    DATABASE_URL="<your production Database URL>" \\
    BUSINESS_ID="<this deployment's business_id>" \\
    python reset_business_data.py

Find BUSINESS_ID in the Render dashboard: whatspilot-business service ->
Environment -> BUSINESS_ID.

The script always writes a full backup JSON file before deleting
anything, prints exactly what it's about to delete, and requires typing
DELETE to proceed. There's no undo beyond that backup file - keep it
somewhere safe until you're sure you don't need it.
"""

import os
import sys
import json
from datetime import datetime, date

import psycopg2
import psycopg2.extras

DATABASE_URL = os.getenv("DATABASE_URL")
BUSINESS_ID = os.getenv("BUSINESS_ID")

if not DATABASE_URL:
    print("Set DATABASE_URL first, e.g.:")
    print('  DATABASE_URL="postgresql://..." BUSINESS_ID="..." python reset_business_data.py')
    sys.exit(1)

if not BUSINESS_ID:
    print("Set BUSINESS_ID first (Render dashboard -> whatspilot-business -> Environment -> BUSINESS_ID), e.g.:")
    print('  DATABASE_URL="postgresql://..." BUSINESS_ID="..." python reset_business_data.py')
    sys.exit(1)


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def main():

    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.DictCursor)

    try:

        cur = conn.cursor()

        # ------------------------------------------------------------
        # Resolve this business's own WhatsApp number - customer_mapping
        # and customer_tags aren't keyed by business_id directly (see
        # module docstring), only by phone numbers, so everything below
        # keys off this instead.
        # ------------------------------------------------------------

        cur.execute(
            "SELECT whatsapp_number FROM customer_numbers WHERE business_id = %s",
            (BUSINESS_ID,)
        )
        row = cur.fetchone()

        if not row:
            print(f"No business found with BUSINESS_ID={BUSINESS_ID!r} in customer_numbers.")
            print("Double check the value against Render's Environment tab.")
            sys.exit(1)

        business_phone = row["whatsapp_number"]

        cur.execute(
            "SELECT customer_phone FROM customer_mapping WHERE business_phone = %s",
            (business_phone,)
        )
        customer_phones = [r["customer_phone"] for r in cur.fetchall()]

        print(f"Business: {BUSINESS_ID} ({business_phone})")
        print(f"Customers on file: {len(customer_phones)}")
        print()

        # ------------------------------------------------------------
        # Every table/query this script touches, in delete order -
        # queried once here (for both the backup and the row counts
        # shown below), reused for the actual DELETE later.
        # ------------------------------------------------------------

        tables = [
            ("conversations", "phone LIKE %s", (f"{BUSINESS_ID}:%",)),
            ("unread_messages", "conversation_id LIKE %s", (f"{BUSINESS_ID}:%",)),
            ("leads", "business_id = %s", (BUSINESS_ID,)),
            ("lead_history", "business_id = %s", (BUSINESS_ID,)),
            ("opportunities", "business_id = %s", (BUSINESS_ID,)),
            ("reminders", "business_id = %s", (BUSINESS_ID,)),
            ("ai_activity", "business_id = %s", (BUSINESS_ID,)),
            ("ai_followups", "business_id = %s", (BUSINESS_ID,)),
        ]

        if customer_phones:
            tables.append((
                "customer_tags", "customer_phone = ANY(%s)", (customer_phones,)
            ))

        tables.append((
            "customer_mapping", "business_phone = %s", (business_phone,)
        ))

        # ------------------------------------------------------------
        # Backup - every row this script is about to delete, fetched
        # before anything is touched.
        # ------------------------------------------------------------

        backup = {"business_id": BUSINESS_ID, "business_phone": business_phone, "tables": {}}

        print("Rows that will be deleted:")

        for table, where_sql, params in tables:

            cur.execute(f"SELECT * FROM {table} WHERE {where_sql}", params)
            rows = [dict(r) for r in cur.fetchall()]

            backup["tables"][table] = rows

            print(f"  {table}: {len(rows)}")

        total = sum(len(v) for v in backup["tables"].values())

        if total == 0:
            print()
            print("Nothing to delete - this business has no CRM data on file.")
            sys.exit(0)

        backup_filename = (
            f"whatspilot_crm_backup_{BUSINESS_ID}_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )

        with open(backup_filename, "w") as f:
            json.dump(backup, f, indent=2, default=_json_default)

        print()
        print(f"Backup written to: {backup_filename}")
        print()

        # ------------------------------------------------------------
        # Confirm
        # ------------------------------------------------------------

        answer = input(
            f'Type DELETE to permanently remove these {total} rows for '
            f'{BUSINESS_ID}, or anything else to cancel: '
        )

        if answer != "DELETE":
            print("Cancelled - nothing was deleted.")
            sys.exit(0)

        # ------------------------------------------------------------
        # Delete - one transaction, all or nothing.
        # ------------------------------------------------------------

        for table, where_sql, params in tables:
            cur.execute(f"DELETE FROM {table} WHERE {where_sql}", params)
            print(f"  Deleted from {table}: {cur.rowcount}")

        conn.commit()

        print()
        print("Done. This business now has a clean slate.")
        print(f"Backup kept at: {backup_filename}")

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    main()
