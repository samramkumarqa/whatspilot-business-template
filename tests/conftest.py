import os
import sys
import uuid

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest

import database.db as db
import rate_limit


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """
    rate_limit._attempts is process-wide module state (see rate_limit.py),
    not per-test-app state - without this, login/OTP tests in different
    files would share counters across the whole pytest run just because
    they all hit the same rate-limited routes under the TestClient's
    fixed default host, and could trip the limit purely from test count/
    order rather than anything the test itself does.
    """

    rate_limit.clear_all()
    yield
    rate_limit.clear_all()


@pytest.fixture
def isolated_db(monkeypatch):
    """
    Gives each test its own throwaway Postgres schema, created fresh and
    dropped afterward, so tests don't see each other's rows - the Postgres
    equivalent of the old "fresh SQLite file per test" approach (before
    the Postgres migration, this chdir'd into a tmp_path and pointed
    database/db.py's SQLite connection pools at it instead).

    Requires DATABASE_URL to point at a real Postgres instance before
    running pytest (see database/db.py) - e.g.:

        DATABASE_URL=postgresql://user:pass@host/db pytest

    Isolation works via Postgres's per-session search_path rather than a
    second connection pool or a schema-qualifying every query: database/db.py's
    get_crm_connection()/get_conversation_connection() check a
    module-level `_test_schema` hook (unset in normal operation) and, when
    set, run `SET search_path TO "<schema>", public` on every connection
    they hand out - so every unqualified table name in the ~22 CRM/
    automation modules transparently resolves inside the test's own
    schema without any of those modules needing to know tests exist.
    """

    schema = f"test_{uuid.uuid4().hex[:16]}"

    conn = db.get_crm_connection()
    conn.execute(f'CREATE SCHEMA "{schema}"')
    conn.commit()
    conn.close()

    monkeypatch.setattr(db, "_test_schema", schema)

    from crm.customer_mapping import (
        init_customer_mapping,
        init_business_settings,
    )
    from crm.lead_manager import init_leads
    from crm.opportunity_manager import init_opportunities
    from crm.tag_manager import init_tags
    from crm.activity_manager import init_activity
    from crm.followup_manager import init_followups
    from reminder_manager import init_reminders
    from conversations import init_db as init_conversations
    from unread_manager import init_unread
    from automation.database import init_automation_db
    from automation.rule_stats import init_rule_executions

    init_customer_mapping()
    init_business_settings()
    init_leads()
    init_opportunities()
    init_tags()
    init_activity()
    init_followups()
    init_reminders()
    init_conversations()
    init_unread()
    init_automation_db()
    init_rule_executions()

    yield

    # Drop the throwaway schema so test schemas don't accumulate in the
    # shared Postgres instance across a whole pytest run. _test_schema is
    # cleared first so this cleanup connection itself isn't pointed at
    # the schema it's about to drop.
    monkeypatch.setattr(db, "_test_schema", None)
    conn = db.get_crm_connection()
    conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    conn.commit()
    conn.close()


class FakeRequest:
    """
    Minimal stand-in for a Starlette Request. auth.enforce_tenant_access()
    and enforce_tenant_access_for_customer() only ever read
    request.session, so tests that call route handler functions directly
    (bypassing the real ASGI app/middleware) can pass one of these
    instead of spinning up a real request with a signed session cookie.
    """

    def __init__(self, session=None):
        self.session = session or {}


@pytest.fixture
def admin_request():
    """
    A FakeRequest with an admin session - admin bypasses
    enforce_tenant_access()'s business-ownership check entirely, so this
    is the right stand-in for tests that aren't specifically about
    tenant isolation (see tests/test_tenant_isolation.py for those).
    """
    return FakeRequest({"role": "admin"})


def business_owner_request(user_id):
    """
    A FakeRequest for a business_owner session scoped to `user_id` - for
    tests that specifically exercise the business-owner access path
    (e.g. confirming a business owner can reach their own data but not
    another business's).
    """
    return FakeRequest({"role": "business_owner", "user_id": user_id})
