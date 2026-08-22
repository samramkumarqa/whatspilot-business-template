"""
One-off local script that enables the `vector` Postgres extension
(pgvector) on this app's database, once.

Why this exists: website indexing (Settings page's Website URL field,
the "Indexed Websites" list, and the AI's knowledge base for answering
product questions) used to store everything on the web service's local
disk - which Render's free tier wipes on every restart/redeploy/idle
spin-down. vector_store.py now stores that data in Postgres instead
(the same shared database everything else already uses), using
pgvector to store and search embeddings. That requires the `vector`
extension to exist in the database before vector_store.py's own
init_website_index() can create its tables - CREATE EXTENSION is a
privileged, database-level operation that (unlike CREATE TABLE) an
app's normal runtime connection may not be allowed to run, especially
if it's ever switched to a restricted role in the future (see
whatspilot-admin-repo/provisioning/setup_business_portal_role.py for
that same limitation, documented there for ALTER TABLE). So this is a
manual, one-time step - not something the app tries to do itself on
every boot.

Usage - run locally, once, against production:

    cd whatspilot-business-repo
    DATABASE_URL="<your production Internal/External Database URL>" python enable_pgvector.py

Render Postgres supports pgvector as a "trusted" extension - any role
with CREATE privilege on the public schema can install it, no
superuser needed. Safe to re-run (CREATE EXTENSION IF NOT EXISTS).

After this succeeds, restart (or just wait for the next natural
restart of) whatspilot-business - main.py's init_website_index() will
create the actual tables on that next boot.
"""

import os
import sys

import psycopg2

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("Set DATABASE_URL first, e.g.:")
    print(
        '  DATABASE_URL="postgresql://..." python enable_pgvector.py'
    )
    sys.exit(1)


def main():

    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True

    with conn.cursor() as cur:

        print("Enabling the vector extension...")

        try:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")

        except psycopg2.Error as e:

            print()
            print("Failed to enable the vector extension:")
            print(f"  {e}")
            print()
            print(
                "If this says permission denied, run this script again "
                "using the database's original/owner connection string "
                "(not a restricted role's), or enable it manually from "
                "the Render dashboard: your Postgres -> Extensions -> "
                "pgvector -> Enable."
            )
            sys.exit(1)

        cur.execute(
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
        )
        version = cur.fetchone()

    conn.close()

    print(f"Done - pgvector {version[0] if version else ''} is enabled.")
    print(
        "Restart whatspilot-business (or wait for its next natural "
        "restart) so init_website_index() can create its tables."
    )


if __name__ == "__main__":
    main()
