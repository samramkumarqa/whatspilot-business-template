"""
Tests for api/customer.py's manual reply route (POST
/conversation/{user_id}/{customer_phone}/reply) - the dashboard's reply
box, the "close the loop" complement to human handoff (see
tests/test_handoff.py). whatsapp.send_message() is monkeypatched to avoid
hitting the real Twilio API, the same approach test_lead_intelligence.py
uses for ask_llm().
"""

import asyncio

import pytest
from pydantic import ValidationError

from api.customer import send_manual_reply, ManualReplyRequest
from analytics.customer_stats import get_conversation
from crm.activity_manager import get_activity
from crm.customer_mapping import save_customer_number
from crm.lead_manager import get_lead, pause_ai
from tests.conftest import FakeRequest

_ADMIN = FakeRequest({"role": "business_owner", "user_id": "u1"})


def _mock_send(sent):

    async def _send(to, text):
        sent.append((to, text))

    return _send


def test_manual_reply_sends_via_whatsapp(isolated_db, monkeypatch):
    sent = []
    monkeypatch.setattr("api.customer.send_message", _mock_send(sent))

    save_customer_number("u1", "+10000000000", "biz1")

    result = asyncio.run(send_manual_reply(
        "u1",
        "+919962824442",
        ManualReplyRequest(message="Hi, following up on your question."),
        _ADMIN
    ))

    assert result["status"] == "success"
    assert sent == [("+919962824442", "Hi, following up on your question.")]


def test_manual_reply_saved_with_manual_sender(isolated_db, monkeypatch):
    sent = []
    monkeypatch.setattr("api.customer.send_message", _mock_send(sent))

    save_customer_number("u1", "+10000000000", "biz1")

    asyncio.run(send_manual_reply(
        "u1", "+919962824442", ManualReplyRequest(message="On it!"), _ADMIN
    ))

    messages = get_conversation("u1", "+919962824442")

    assert len(messages) == 1
    assert messages[0]["role"] == "assistant"
    assert messages[0]["content"] == "On it!"
    assert messages[0]["sender"] == "Manual"


def test_manual_reply_pauses_ai(isolated_db, monkeypatch):
    sent = []
    monkeypatch.setattr("api.customer.send_message", _mock_send(sent))

    save_customer_number("u1", "+10000000000", "biz1")

    asyncio.run(send_manual_reply(
        "u1", "+919962824442", ManualReplyRequest(message="I'll take it from here."), _ADMIN
    ))

    lead = get_lead("+919962824442")

    assert lead["ai_paused"] == 1
    assert lead["ai_paused_reason"] == "Team member sent a manual reply"


def test_manual_reply_repauses_even_if_already_paused_for_different_reason(isolated_db, monkeypatch):
    sent = []
    monkeypatch.setattr("api.customer.send_message", _mock_send(sent))

    save_customer_number("u1", "+10000000000", "biz1")

    pause_ai("+919962824442", "Customer asked for a human")

    asyncio.run(send_manual_reply(
        "u1", "+919962824442", ManualReplyRequest(message="Hi, this is Sam from support."), _ADMIN
    ))

    lead = get_lead("+919962824442")

    assert lead["ai_paused"] == 1
    assert lead["ai_paused_reason"] == "Team member sent a manual reply"


def test_manual_reply_logs_activity(isolated_db, monkeypatch):
    sent = []
    monkeypatch.setattr("api.customer.send_message", _mock_send(sent))

    save_customer_number("u1", "+10000000000", "biz1")

    asyncio.run(send_manual_reply(
        "u1", "+919962824442", ManualReplyRequest(message="Sending you the quote now."), _ADMIN
    ))

    activity = get_activity("+919962824442")

    assert any(
        a["activity_type"] == "Manual" and a["title"] == "Manual reply sent"
        for a in activity
    )


def test_manual_reply_does_not_save_if_send_fails(isolated_db, monkeypatch):

    async def _failing_send(to, text):
        raise RuntimeError("Twilio error")

    monkeypatch.setattr("api.customer.send_message", _failing_send)

    save_customer_number("u1", "+10000000000", "biz1")

    with pytest.raises(RuntimeError):
        asyncio.run(send_manual_reply(
            "u1", "+919962824442", ManualReplyRequest(message="This should not be saved."), _ADMIN
        ))

    messages = get_conversation("u1", "+919962824442")
    assert messages == []

    lead = get_lead("+919962824442")
    assert lead["ai_paused"] == 0


# ---------------------------------------------------------------------
# ManualReplyRequest validation
# ---------------------------------------------------------------------

def test_empty_message_rejected():
    with pytest.raises(ValidationError):
        ManualReplyRequest(message="")


def test_whitespace_only_message_rejected():
    with pytest.raises(ValidationError):
        ManualReplyRequest(message="   ")


def test_message_over_limit_rejected():
    with pytest.raises(ValidationError):
        ManualReplyRequest(message="x" * 4097)


def test_message_is_stripped():
    req = ManualReplyRequest(message="  Hello there  ")
    assert req.message == "Hello there"


def test_message_allows_angle_brackets():
    # Unlike LeadRequest/CustomerNameRequest, chat content isn't
    # restricted to a markup-safe character set.
    req = ManualReplyRequest(message="Check out our <Premium> plan!")
    assert req.message == "Check out our <Premium> plan!"
