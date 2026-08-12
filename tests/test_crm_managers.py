"""
Tests for the crm/ managers - each owns one or two tables in data/app.db
and is exercised here against a real (throwaway, per-test) copy of that
schema via the isolated_db fixture in conftest.py, rather than mocks.
"""

from crm.lead_manager import (
    get_lead,
    update_lead,
    update_lead_intelligence,
    get_lead_timeline,
    get_lead_categories,
    auto_update_lead,
)
from crm.opportunity_manager import add_opportunity, get_opportunities
from crm.tag_manager import save_tags, get_tags, add_tag, remove_tag, find_customers_by_tag
from crm.activity_manager import add_activity, get_activity, get_activity_timeline
from crm.followup_manager import save_followup, get_followups
from crm.customer_mapping import (
    save_customer_number,
    get_business_id,
    get_user_id_by_business_id,
    get_customer_by_number,
    get_business_phone_by_user,
    save_mapping,
    get_business_phone_by_customer,
    get_customers,
    delete_mapping,
    get_customer_name,
    set_customer_name,
    save_business_settings,
    get_business_settings,
)


# ---------------------------------------------------------------------------
# lead_manager
# ---------------------------------------------------------------------------

def test_get_lead_returns_default_for_unknown_customer(isolated_db):
    lead = get_lead("+19998887777")
    assert lead["customer_phone"] == "+19998887777"
    assert lead["status"] == "New"
    assert lead["lead_score"] == 0


def test_update_lead_persists_and_computes_score(isolated_db):
    update_lead(
        customer_phone="+19998887777",
        status="Qualified",
        notes="wants a demo",
        confidence=100,
        reason="asked for pricing",
        updated_by="Manual",
    )

    lead = get_lead("+19998887777")
    assert lead["status"] == "Qualified"
    assert lead["notes"] == "wants a demo"
    # int(70*0.6 + 100*0.4) == 82, per ai/lead_ai.calculate_lead_score
    assert lead["lead_score"] == 82


def test_update_lead_writes_history_entry(isolated_db):
    update_lead("+19998887777", "New", "", confidence=10, reason="first contact", updated_by="Manual")
    update_lead("+19998887777", "Interested", "", confidence=60, reason="asked a question", updated_by="Manual")

    timeline = get_lead_timeline("+19998887777")

    assert len(timeline) == 2
    # ORDER BY created_at DESC - most recent first. Both rows share the
    # same timestamp at test speed, so just confirm both reasons are present
    # rather than assuming a strict order.
    reasons = {row["reason"] for row in timeline}
    assert reasons == {"first contact", "asked a question"}


def test_auto_update_lead_respects_locked_statuses(isolated_db):
    update_lead("+19998887777", "Closed Won", "", confidence=100, reason="deal closed", updated_by="Manual")

    # auto_update_lead should refuse to override a locked terminal status.
    auto_update_lead("+19998887777", "New", confidence=10, reason="ai reset attempt")

    lead = get_lead("+19998887777")
    assert lead["status"] == "Closed Won"


def test_auto_update_lead_applies_when_not_locked(isolated_db):
    update_lead("+19998887777", "New", "", confidence=10, reason="first contact", updated_by="Manual")

    auto_update_lead("+19998887777", "Interested", confidence=60, reason="ai detected interest")

    lead = get_lead("+19998887777")
    assert lead["status"] == "Interested"
    assert lead["updated_by"] == "AI"


def test_get_lead_categories_buckets_by_score(isolated_db):
    update_lead("+1000000001", "Proposal Sent", "", confidence=100, reason="", updated_by="Manual")  # hot (91)
    update_lead("+1000000002", "Interested", "", confidence=80, reason="", updated_by="Manual")       # warm (56)
    update_lead("+1000000003", "New", "", confidence=0, reason="", updated_by="Manual")                # cold (6)

    categories = get_lead_categories()

    hot_phones = {lead["customer_phone"] for lead in categories["hot"]}
    warm_phones = {lead["customer_phone"] for lead in categories["warm"]}
    cold_phones = {lead["customer_phone"] for lead in categories["cold"]}

    assert "+1000000001" in hot_phones
    assert "+1000000002" in warm_phones
    assert "+1000000003" in cold_phones


def _full_analysis(**overrides):
    # A fully-populated ai/lead_intelligence.py analyse_conversation()
    # result - update_lead_intelligence() indexes into this dict directly
    # (no .get() defaults), so tests need every key it reads.
    analysis = {
        "status": "Qualified",
        "confidence": 75,
        "summary": "Customer asked about pricing.",
        "lead_score": 70,
        "intent": "Pricing Inquiry",
        "buying_stage": "Considering",
        "sentiment": "Positive",
        "objection": "None",
        "priority": "High",
        "probability": 60,
        "next_action": "Send pricing",
        "follow_up_days": 1,
        "tags": ["Warm Lead"],
    }
    analysis.update(overrides)
    return analysis


def test_update_lead_intelligence_writes_real_status_not_buying_stage(isolated_db):
    # Regression test: update_lead_intelligence() used to write
    # analysis["buying_stage"] (e.g. "Considering") into the "status"
    # column instead of analysis["status"] (e.g. "Qualified") - a
    # column/value mismatch that meant Lead Status conditions in
    # automation rules almost never matched a real pipeline status.
    update_lead_intelligence(
        "+19998887777",
        _full_analysis(status="Qualified", buying_stage="Considering"),
    )

    lead = get_lead("+19998887777")

    assert lead["status"] == "Qualified"
    assert lead["buying_stage"] == "Considering"


def test_update_lead_intelligence_respects_locked_status(isolated_db):
    # A deal that's already Closed Won should not be silently reopened by
    # an automatic per-message AI update - only a manual edit should move
    # it. auto_update_lead() already protected against this; this is the
    # same guard for the AI-intelligence write path.
    update_lead(
        "+19998887777", "Closed Won", "", confidence=100,
        reason="deal closed", updated_by="Manual",
    )

    update_lead_intelligence(
        "+19998887777",
        _full_analysis(status="Interested"),
    )

    lead = get_lead("+19998887777")
    assert lead["status"] == "Closed Won"


def test_update_lead_intelligence_updates_status_when_not_locked(isolated_db):
    update_lead_intelligence(
        "+19998887777",
        _full_analysis(status="Interested"),
    )

    assert get_lead("+19998887777")["status"] == "Interested"

    update_lead_intelligence(
        "+19998887777",
        _full_analysis(status="Qualified"),
    )

    assert get_lead("+19998887777")["status"] == "Qualified"


# ---------------------------------------------------------------------------
# opportunity_manager
# ---------------------------------------------------------------------------

def test_add_opportunity_creates_then_updates_open_one(isolated_db):
    add_opportunity("+19998887777", "Upsell", confidence=60, reason="asked about add-on", estimated_value=500)
    add_opportunity("+19998887777", "Upsell", confidence=90, reason="ready to buy", estimated_value=750)

    opportunities = get_opportunities("+19998887777")

    # Same customer + same type + still "Open" -> update in place, not a
    # second row.
    assert len(opportunities) == 1
    assert opportunities[0]["confidence"] == 90
    assert opportunities[0]["reason"] == "ready to buy"


def test_get_opportunities_returns_estimated_value_status_and_updated_at(isolated_db):
    # Regression test: get_opportunities() used to only SELECT type,
    # confidence, reason, created_at - estimated_value/status/updated_at
    # all exist on the table and are written correctly by add_opportunity(),
    # but were silently dropped here, so the dashboard's Revenue/Stage
    # always showed 0/blank no matter what the AI actually computed.
    add_opportunity("+19998887777", "Renewal", confidence=60, reason="first contact", estimated_value=800)
    # updated_at is only set by the UPDATE branch (a second detection of
    # the same still-open opportunity), not the initial INSERT.
    add_opportunity("+19998887777", "Renewal", confidence=80, reason="contract ending", estimated_value=1200)

    opportunities = get_opportunities("+19998887777")

    assert opportunities[0]["estimated_value"] == 1200
    assert opportunities[0]["status"] == "Open"
    assert opportunities[0]["updated_at"] is not None


def test_add_opportunity_different_types_create_separate_rows(isolated_db):
    add_opportunity("+19998887777", "Upsell", confidence=60, reason="a", estimated_value=100)
    add_opportunity("+19998887777", "Renewal", confidence=70, reason="b", estimated_value=200)

    opportunities = get_opportunities("+19998887777")

    assert {o["type"] for o in opportunities} == {"Upsell", "Renewal"}


# ---------------------------------------------------------------------------
# tag_manager
# ---------------------------------------------------------------------------

def test_tag_add_get_remove(isolated_db):
    add_tag("+19998887777", "vip")
    add_tag("+19998887777", "newsletter")

    assert get_tags("+19998887777") == ["newsletter", "vip"]  # ORDER BY tag

    remove_tag("+19998887777", "newsletter")
    assert get_tags("+19998887777") == ["vip"]


def test_save_tags_replaces_existing_set(isolated_db):
    add_tag("+19998887777", "old-tag")
    save_tags("+19998887777", ["a", "b"])

    assert get_tags("+19998887777") == ["a", "b"]


def test_find_customers_by_tag(isolated_db):
    add_tag("+1111111111", "vip")
    add_tag("+2222222222", "vip")
    add_tag("+3333333333", "not-vip")

    assert set(find_customers_by_tag("vip")) == {"+1111111111", "+2222222222"}


# ---------------------------------------------------------------------------
# activity_manager
# ---------------------------------------------------------------------------

def test_add_and_get_activity(isolated_db):
    add_activity("+19998887777", "Manual", "Lead Updated", "status changed to Qualified")

    activity = get_activity("+19998887777")

    assert len(activity) == 1
    assert activity[0]["activity_type"] == "Manual"
    assert activity[0]["title"] == "Lead Updated"


def test_get_activity_timeline_reads_same_table_as_get_activity(isolated_db):
    # Regression test: get_activity_timeline() previously queried a
    # "customer_activity" table that was never created anywhere (the real
    # table is "ai_activity", same one add_activity()/get_activity() use).
    # It would raise sqlite3.OperationalError on every call.
    add_activity("+19998887777", "Manual", "Lead Updated", "status changed to Qualified")

    timeline = get_activity_timeline("+19998887777")

    assert len(timeline) == 1
    assert timeline[0]["title"] == "Lead Updated"


def test_add_activity_skips_exact_repeat_of_most_recent_entry(isolated_db):
    # The automation runner re-evaluates every customer against every rule
    # every 1 minute - as long as a customer keeps matching, "Add CRM
    # Activity" would otherwise log an identical row on every single run
    # forever. add_activity() should collapse consecutive identical calls
    # into one row instead of flooding the log.
    logged_first = add_activity(
        "+19998887777", "Automation", "Lead Follow-up Triggered",
        "Automation executed successfully."
    )
    logged_second = add_activity(
        "+19998887777", "Automation", "Lead Follow-up Triggered",
        "Automation executed successfully."
    )
    logged_third = add_activity(
        "+19998887777", "Automation", "Lead Follow-up Triggered",
        "Automation executed successfully."
    )

    assert logged_first is True
    assert logged_second is False
    assert logged_third is False

    activity = get_activity("+19998887777")
    assert len(activity) == 1


def test_add_activity_logs_again_when_content_changes(isolated_db):
    add_activity("+19998887777", "Automation", "Lead Follow-up Triggered", "x")
    add_activity("+19998887777", "Automation", "Lead Follow-up Triggered", "x")

    # A genuinely different event (different title) is not a duplicate -
    # it should still get its own row.
    logged = add_activity("+19998887777", "Manual", "Lead Updated Manually", "Status : Qualified")

    assert logged is True

    activity = get_activity("+19998887777")
    assert len(activity) == 2


def test_add_activity_logs_again_after_repeat_of_earlier_entry(isolated_db):
    # Only the *most recent* entry is checked for a duplicate match - if
    # something else was logged in between, an otherwise-identical repeat
    # of an earlier event is a new, real occurrence and should be logged.
    add_activity("+19998887777", "Automation", "Lead Follow-up Triggered", "x")
    add_activity("+19998887777", "Manual", "Lead Updated Manually", "Status : Qualified")

    logged = add_activity("+19998887777", "Automation", "Lead Follow-up Triggered", "x")

    assert logged is True

    activity = get_activity("+19998887777")
    assert len(activity) == 3


def test_add_activity_dedup_is_scoped_per_customer(isolated_db):
    # Two different customers matching the same rule at the same moment
    # must not suppress each other's activity log entry.
    logged_a = add_activity("+19998887777", "Automation", "Lead Follow-up Triggered", "x")
    logged_b = add_activity("+11112223333", "Automation", "Lead Follow-up Triggered", "x")

    assert logged_a is True
    assert logged_b is True

    assert len(get_activity("+19998887777")) == 1
    assert len(get_activity("+11112223333")) == 1


# ---------------------------------------------------------------------------
# followup_manager
# ---------------------------------------------------------------------------

def test_save_and_get_followups(isolated_db):
    save_followup("+19998887777", "Hi, checking in on your interest!")

    followups = get_followups("+19998887777")

    assert len(followups) == 1
    assert followups[0]["message"] == "Hi, checking in on your interest!"
    assert followups[0]["approved"] == 0
    assert followups[0]["sent"] == 0


# ---------------------------------------------------------------------------
# customer_mapping
# ---------------------------------------------------------------------------

def test_business_registration_and_lookup(isolated_db):
    save_customer_number("biz1", "+10000000001", "biz1")

    assert get_business_id("biz1") == "biz1"
    assert get_user_id_by_business_id("biz1") == "biz1"
    assert get_customer_by_number("+10000000001") == "biz1"
    assert get_business_phone_by_user("biz1") == "+10000000001"


def test_customer_to_business_mapping(isolated_db):
    save_customer_number("biz1", "+10000000001", "biz1")
    save_mapping(customer_phone="+19998887777", business_phone="+10000000001")

    assert get_business_phone_by_customer("+19998887777") == "+10000000001"
    assert get_customers("biz1") == ["+19998887777"]


def test_get_customers_returns_its_connection_to_the_pool(isolated_db):
    """
    Regression test: get_customers() used to have `conn.close()` written
    after its `return` statement, making it unreachable - every call
    permanently checked a connection out of database/db.py's pooled
    connections (max 10, see _pg_pool in database/db.py) and never
    returned it. Calling it more times than the pool size used to
    deadlock once every connection was checked out and none were free -
    if this test hangs, the leak is back.
    """

    save_customer_number("biz1", "+10000000001", "biz1")

    for _ in range(20):
        get_customers("biz1")

    delete_mapping("+19998887777")
    assert get_business_phone_by_customer("+19998887777") is None


def test_save_mapping_captures_name_on_first_message(isolated_db):
    # Regression coverage for the "+9" avatar bug: customer.name was never
    # populated anywhere, because save_mapping() never stored a name at
    # all. Twilio's WhatsApp webhook sends the sender's ProfileName, which
    # api/webhook.py now passes through here as customer_name.
    save_mapping(
        customer_phone="+19998887777",
        business_phone="+10000000001",
        customer_name="Asha Rao"
    )

    assert get_customer_name("+19998887777") == "Asha Rao"


def test_save_mapping_does_not_overwrite_existing_name(isolated_db):
    # A later message without a ProfileName (or with a different one)
    # must not clobber a name that's already on file - whether that name
    # was auto-captured earlier or set manually via set_customer_name().
    save_mapping(
        customer_phone="+19998887777",
        business_phone="+10000000001",
        customer_name="Asha Rao"
    )

    save_mapping(
        customer_phone="+19998887777",
        business_phone="+10000000001",
        customer_name=None
    )

    assert get_customer_name("+19998887777") == "Asha Rao"

    save_mapping(
        customer_phone="+19998887777",
        business_phone="+10000000001",
        customer_name="Some Other Name"
    )

    assert get_customer_name("+19998887777") == "Asha Rao"


def test_save_mapping_fills_in_name_once_known_later(isolated_db):
    # First message has no ProfileName (name stays unset), a later one
    # does - it should get captured then, since nothing was set yet.
    save_mapping(
        customer_phone="+19998887777",
        business_phone="+10000000001",
        customer_name=None
    )

    assert get_customer_name("+19998887777") is None

    save_mapping(
        customer_phone="+19998887777",
        business_phone="+10000000001",
        customer_name="Asha Rao"
    )

    assert get_customer_name("+19998887777") == "Asha Rao"


def test_set_customer_name_manual_override(isolated_db):
    save_mapping(
        customer_phone="+19998887777",
        business_phone="+10000000001",
        customer_name="Auto Captured Name"
    )

    set_customer_name("+19998887777", "Corrected Name")

    assert get_customer_name("+19998887777") == "Corrected Name"

    # And an unknown customer_phone is simply a no-op, not an error.
    set_customer_name("+10000000000", "Nobody")
    assert get_customer_name("+10000000000") is None


def test_business_settings_round_trip(isolated_db):
    assert get_business_settings("biz1") is None

    save_business_settings(
        "biz1",
        "Ram's Shop",
        "Welcome!",
        "Be friendly",
        phone="+10000000001",
        email="ram@example.com",
        website="https://example.com",
    )

    settings = get_business_settings("biz1")
    assert settings["business_name"] == "Ram's Shop"
    assert settings["email"] == "ram@example.com"
