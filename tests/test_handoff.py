"""
Tests for the human handoff feature - ai/handoff.py's detection logic,
crm/lead_manager.py's pause_ai()/resume_ai(), and the pieces that surface
a pause in the rest of the app (analytics/customer_stats.py's ai_paused
field, api/customer.py's resume-ai route). See api/webhook.py for where
detection actually plugs into the incoming-message pipeline - that route
needs a real Twilio signature/Form request to exercise directly, so it's
not covered here; the pieces it calls are.
"""

import asyncio

import pytest

from ai.handoff import detect_explicit_handoff_request, is_negative_complaint
from crm.lead_manager import get_lead, pause_ai, resume_ai, update_lead


# ---------------------------------------------------------------------
# detect_explicit_handoff_request()
# ---------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Can I talk to a human please",
    "I want to speak with a real person",
    "connect me to an agent",
    "get me a manager",
    "is there a human i can talk to",
    "I want customer service representative",
    "stop talking to a bot",
    "not a bot, get me an actual person",
    "this is a bot",
])
def test_detects_explicit_requests(text):
    assert detect_explicit_handoff_request(text) is not None


@pytest.mark.parametrize("text", [
    "What is the price of this product",
    "I am the only person handling this order",
    "which agent do you recommend for insurance",
    "my human resources department needs an invoice",
    "thanks that was helpful",
    "",
])
def test_does_not_false_positive_on_normal_messages(text):
    assert detect_explicit_handoff_request(text) is None


def test_detect_explicit_handoff_request_handles_none():
    assert detect_explicit_handoff_request(None) is None


# ---------------------------------------------------------------------
# is_negative_complaint()
# ---------------------------------------------------------------------

def test_negative_sentiment_and_complaint_intent_triggers():
    assert is_negative_complaint({"sentiment": "Negative", "intent": "Complaint"}) is True


def test_negative_sentiment_alone_does_not_trigger():
    # A customer can be mildly unhappy about pricing without wanting a
    # human - sentiment alone is too noisy.
    assert is_negative_complaint({"sentiment": "Negative", "intent": "Pricing Inquiry"}) is False


def test_complaint_intent_alone_does_not_trigger():
    assert is_negative_complaint({"sentiment": "Neutral", "intent": "Complaint"}) is False


def test_is_negative_complaint_handles_missing_analysis():
    assert is_negative_complaint(None) is False
    assert is_negative_complaint({}) is False


# ---------------------------------------------------------------------
# pause_ai() / resume_ai()
# ---------------------------------------------------------------------

def test_pause_ai_on_brand_new_customer(isolated_db):
    # No leads row exists yet for this customer at all - pause_ai() must
    # still work (their very first message can be the one that triggers
    # an explicit handoff request).
    pause_ai("+919900000001", "Customer asked for a human")

    lead = get_lead("+919900000001")

    assert lead["ai_paused"] == 1
    assert lead["ai_paused_reason"] == "Customer asked for a human"
    assert lead["ai_paused_at"] is not None


def test_pause_ai_does_not_clobber_existing_lead_fields(isolated_db):
    update_lead("+919900000002", "Interested", "Some notes", confidence=70)

    pause_ai("+919900000002", "Complaint detected")

    lead = get_lead("+919900000002")

    assert lead["status"] == "Interested"
    assert lead["notes"] == "Some notes"
    assert lead["ai_paused"] == 1
    assert lead["ai_paused_reason"] == "Complaint detected"


def test_resume_ai_clears_pause(isolated_db):
    pause_ai("+919900000003", "Customer asked for a human")
    assert get_lead("+919900000003")["ai_paused"] == 1

    resume_ai("+919900000003")

    lead = get_lead("+919900000003")

    assert lead["ai_paused"] == 0
    assert lead["ai_paused_reason"] == ""
    assert lead["ai_paused_at"] is None


def test_new_lead_defaults_to_not_paused(isolated_db):
    lead = get_lead("+919900000004")
    assert lead["ai_paused"] == 0


# ---------------------------------------------------------------------
# analytics/customer_stats.py surfaces ai_paused
# ---------------------------------------------------------------------

def test_customer_stats_reflects_ai_paused_flag(isolated_db, monkeypatch):
    import config
    from crm.customer_mapping import save_customer_number, save_mapping
    from conversations import add_message
    from analytics.customer_stats import get_customer_stats

    save_customer_number("u1", "+10000000000", "biz1")
    save_mapping(customer_phone="+919962824442", business_phone="+10000000000", customer_name="Test")
    add_message("biz1:+919962824442", "user", "hi")

    # pause_ai() stamps whichever business_id config.BUSINESS_ID currently
    # points at, while get_customer_stats() resolves business_id via the
    # registered get_business_id("u1") - "biz1" above. These have to match,
    # same as they always do in a real deployment.
    monkeypatch.setattr(config, "BUSINESS_ID", "biz1")
    pause_ai("+919962824442", "Customer asked for a human")

    customers = get_customer_stats("u1")

    assert len(customers) == 1
    assert customers[0]["ai_paused"] is True


def test_customer_stats_defaults_ai_paused_false(isolated_db):
    from crm.customer_mapping import save_customer_number, save_mapping
    from conversations import add_message
    from analytics.customer_stats import get_customer_stats

    save_customer_number("u1", "+10000000000", "biz1")
    save_mapping(customer_phone="+919962824442", business_phone="+10000000000", customer_name="Test")
    add_message("biz1:+919962824442", "user", "hi")

    customers = get_customer_stats("u1")

    assert customers[0]["ai_paused"] is False


# ---------------------------------------------------------------------
# api/customer.py's resume-ai route
# ---------------------------------------------------------------------

def test_resume_ai_route(isolated_db):
    from api.customer import resume_ai_route
    from crm.customer_mapping import register_business, save_mapping
    from tests.conftest import FakeRequest

    # enforce_tenant_access_for_customer() resolves the owning business
    # from customer_mapping - needs a real mapping (not just a bare lead
    # row) for the tenant check to have something to resolve against.
    register_business("u1", "+10000000001")
    save_mapping("+919900000005", "+10000000001")

    pause_ai("+919900000005", "Customer asked for a human")
    assert get_lead("+919900000005")["ai_paused"] == 1

    result = asyncio.run(
        resume_ai_route(
            "+919900000005",
            FakeRequest({"role": "business_owner", "user_id": "u1"})
        )
    )

    assert result["status"] == "success"
    assert get_lead("+919900000005")["ai_paused"] == 0
