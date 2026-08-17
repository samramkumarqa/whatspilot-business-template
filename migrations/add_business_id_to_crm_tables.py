"""
One-off migration: adds a `business_id` column to every CRM table that was
previously scoped only through customer_mapping's customer_phone ->
business_phone lookup (leads, opportunities, lead_history, reminders,
ai_activity, ai_followups), backfills it for existing rows, and - for
`leads` specifically - tightens its PRIMARY KEY from customer_phone alone
to (customer_phone, business_id).

WHY THIS EXISTS
----------------
This app runs one deployment per business, all sharing the same Postgres
database (see config.py's BUSINESS_ID and database/db.py). Every one of
the tables above only ever stored customer_phone, not which business the
row belonged to - "which business owns this row" was inferred entirely
from customer_mapping, a table that maps customer_phone -> business_phone
and gets overwritten (not preserved historically) every time
crm/customer_mapping.py's save_mapping() runs.

That's fine as long as a given customer_phone only ever talks to one
business, which is true today. But if the same phone number were ever to
message two different WhatsPilot-hosted businesses, save_mapping()'s
upsert would silently repoint that phone's row in customer_mapping at the
second business - and every query that resolved "whose data is this"
via that mapping (get_reminders(), get_lead_categories(), the customer
health/revenue/forecast dashboards, etc.) would then attribute the FIRST
business's historical leads/opportunities/reminders/activity to the
SECOND business. Worse, `leads` has customer_phone as its literal PRIMARY
KEY - a second business's very first INSERT for that phone doesn't just
get misattributed, it overwrites the first business's row outright
(status, notes, ai_paused, lead_score - gone).

business_id (this deployment's own config.BUSINESS_ID, stamped at write
time rather than re-derived later from a mutable mapping) closes this:
every write from here on stamps which business it actually belongs to,
and every read filters by it, so two businesses sharing a phone number
can no longer collide or leak into each other even if customer_mapping's
"current owner" pointer moves later.

WHEN TO RUN THIS - READ BEFORE DEPLOYING THE APP CODE THAT USES business_id
-----------------------------------------------------------------------------
Business-portal deployments run against a *restricted* Postgres role
(whatspilot_business_portal - see whatspilot-admin-repo/provisioning/
setup_business_portal_role.py) that does NOT own these tables, only has
DML (SELECT/INSERT/UPDATE/DELETE) granted on them. Postgres requires
table *ownership* to run ALTER TABLE ADD COLUMN, CREATE INDEX, or ALTER
... PRIMARY KEY - the restricted role cannot do any of that (this is the
exact same ownership restriction that caused the CREATE INDEX production
crash-loop fixed in database/db.py's create_index_if_missing() - see its
docstring for the full story). The app's own init_*() functions guard
their ALTER TABLE ADD COLUMN calls with an information_schema check and
skip them once the column already exists, so they're safe to leave in
place for fresh/local databases - but that guard only helps if this
script has ALREADY added the column in production, under the real owner
credential, before the new app code boots under the restricted role.

Run this ONCE, by hand, using the admin app's own full-access
DATABASE_URL (NOT BUSINESS_PORTAL_DATABASE_URL), BEFORE redeploying any
business-portal instance running code that expects business_id to exist:

    cd whatspilot-business-repo
    DATABASE_URL="<production Internal/External Database URL>" python migrations/add_business_id_to_crm_tables.py

Safe to re-run: every step checks what's already there first and skips
it if so. If it's run again after the column/index/constraint already
exist, it just backfills any newly-NULL rows (there shouldn't be any)
and exits.
"""

import os
import sys

import psycopg2

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("Set DATABASE_URL first, e.g.:")
    print(
        '  DATABASE_URL="postgresql://..." python '
        "migrations/add_business_id_to_crm_tables.py"
    )
    sys.exit(1)

# Every table that used to be scoped only via customer_mapping's
# customer_phone -> business_phone lookup. `leads` is handled separately
# below (extra step: tightening its PRIMARY KEY) - it's deliberately not
# in this list.
TABLES = [
    "opportunities",
    "lead_history",
    "reminders",
    "ai_activity",
    "ai_followups",
]


def _column_exists(cur, table, column):
    cur.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s AND column_name = %s",
        (table, column),
    )
    return cur.fetchone() is not None


def _index_exists(cur, index_name):
    cur.execute(
        "SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = %s",
        (index_name,),
    )
    return cur.fetchone() is not None


def _table_exists(cur, table):
    cur.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = %s",
        (table,),
    )
    return cur.fetchone() is not None


def _add_and_backfill(cur, table):

    if not _table_exists(cur, table):
        print(f"  (skipping '{table}' - table doesn't exist yet)")
        return

    if not _column_exists(cur, table, "business_id"):
        print(f"  [{table}] adding business_id column...")
        cur.execute(f'ALTER TABLE "{table}" ADD COLUMN business_id TEXT')
    else:
        print(f"  [{table}] business_id column already exists.")

    # Backfill: for every row still missing business_id, resolve it via
    # customer_mapping's *current* business_phone for that customer_phone,
    # then customer_numbers' business_id for that business_phone. This is
    # a best-effort backfill using the same mutable mapping this migration
    # exists to stop relying on going forward - it's correct for every
    # customer_phone that has only ever belonged to one business (true for
    # 100% of today's real data), and is a no-op improvement (not a
    # regression) for any row it can't confidently resolve, which is just
    # left NULL for manual follow-up rather than guessed at.
    cur.execute(
        f"""
        UPDATE "{table}" t
        SET business_id = cn.business_id
        FROM customer_mapping cmap
        JOIN customer_numbers cn ON cn.whatsapp_number = cmap.business_phone
        WHERE cmap.customer_phone = t.customer_phone
        AND t.business_id IS NULL
        AND cn.business_id IS NOT NULL
        """
    )
    backfilled = cur.rowcount
    print(f"  [{table}] backfilled {backfilled} row(s).")

    cur.execute(f'SELECT COUNT(*) FROM "{table}" WHERE business_id IS NULL')
    remaining = cur.fetchone()[0]
    if remaining:
        print(
            f"  [{table}] WARNING: {remaining} row(s) still have no "
            f"business_id (customer_phone not found in customer_mapping, "
            f"or that mapping's business has no business_id itself). "
            f"These rows won't be scoped to any business until resolved "
            f"manually."
        )

    index_name = f"idx_{table}_business_id"
    if not _index_exists(cur, index_name):
        print(f"  [{table}] creating index {index_name}...")
        cur.execute(
            f'CREATE INDEX "{index_name}" ON "{table}"(business_id)'
        )
    else:
        print(f"  [{table}] index {index_name} already exists.")


def _migrate_leads(cur):

    table = "leads"

    if not _table_exists(cur, table):
        print(f"  (skipping '{table}' - table doesn't exist yet)")
        return

    if not _column_exists(cur, table, "business_id"):
        print(f"  [{table}] adding business_id column...")
        cur.execute(f'ALTER TABLE "{table}" ADD COLUMN business_id TEXT')
    else:
        print(f"  [{table}] business_id column already exists.")

    cur.execute(
        """
        UPDATE leads t
        SET business_id = cn.business_id
        FROM customer_mapping cmap
        JOIN customer_numbers cn ON cn.whatsapp_number = cmap.business_phone
        WHERE cmap.customer_phone = t.customer_phone
        AND t.business_id IS NULL
        AND cn.business_id IS NOT NULL
        """
    )
    print(f"  [{table}] backfilled {cur.rowcount} row(s).")

    cur.execute("SELECT COUNT(*) FROM leads WHERE business_id IS NULL")
    remaining = cur.fetchone()[0]

    if remaining:
        print(
            f"  [{table}] WARNING: {remaining} row(s) still have no "
            f"business_id - skipping the PRIMARY KEY change below until "
            f"these are resolved (either backfill them by hand with the "
            f"right business_id, or delete them if they're orphaned test "
            f"data). Re-run this script once they're fixed."
        )
        return

    index_name = "idx_leads_business_id"
    if not _index_exists(cur, index_name):
        print(f"  [{table}] creating index {index_name}...")
        cur.execute(f'CREATE INDEX "{index_name}" ON leads(business_id)')
    else:
        print(f"  [{table}] index {index_name} already exists.")

    # Tighten the PRIMARY KEY from (customer_phone) to
    # (customer_phone, business_id). Without this, a second business's
    # very first write for a customer_phone the first business already
    # has a leads row for wouldn't just be *readable* by the wrong
    # business (the scoping fix above prevents that) - it would silently
    # overwrite the first business's entire row on INSERT ... ON CONFLICT
    # (status, notes, ai_paused, lead_score, all of it), since
    # customer_phone alone is still the uniqueness constraint every
    # ON CONFLICT clause in crm/lead_manager.py targets. Only proceeds
    # once every row has a real business_id (checked above) - a composite
    # PRIMARY KEY requires every key column to be NOT NULL.
    cur.execute(
        """
        SELECT tc.constraint_name
        FROM information_schema.table_constraints tc
        WHERE tc.table_name = 'leads'
        AND tc.constraint_type = 'PRIMARY KEY'
        """
    )
    pk_row = cur.fetchone()

    cur.execute(
        """
        SELECT kcu.column_name
        FROM information_schema.key_column_usage kcu
        JOIN information_schema.table_constraints tc
            ON tc.constraint_name = kcu.constraint_name
        WHERE tc.table_name = 'leads'
        AND tc.constraint_type = 'PRIMARY KEY'
        ORDER BY kcu.ordinal_position
        """
    )
    pk_columns = [row[0] for row in cur.fetchall()]

    if pk_columns == ["customer_phone", "business_id"]:
        print(f"  [{table}] PRIMARY KEY is already (customer_phone, business_id).")
        return

    if not pk_row:
        print(
            f"  [{table}] WARNING: no PRIMARY KEY constraint found at all - "
            f"not touching this by hand, please check the table manually."
        )
        return

    print(f"  [{table}] setting business_id NOT NULL...")
    cur.execute("ALTER TABLE leads ALTER COLUMN business_id SET NOT NULL")

    print(
        f"  [{table}] dropping old PRIMARY KEY ({', '.join(pk_columns)}) "
        f"and adding (customer_phone, business_id)..."
    )
    cur.execute(f'ALTER TABLE leads DROP CONSTRAINT "{pk_row[0]}"')
    cur.execute(
        "ALTER TABLE leads ADD PRIMARY KEY (customer_phone, business_id)"
    )
    print(f"  [{table}] done.")


def main():

    conn = psycopg2.connect(DATABASE_URL)

    try:
        with conn.cursor() as cur:

            print("Migrating opportunities / lead_history / reminders / "
                  "ai_activity / ai_followups...")
            for table in TABLES:
                _add_and_backfill(cur, table)

            print()
            print("Migrating leads (business_id + composite PRIMARY KEY)...")
            _migrate_leads(cur)

        conn.commit()
        print()
        print("Done. Safe to deploy app code that relies on business_id now.")

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
