"""
Regression tests for the CRITICAL architectural gap flagged during the
Round 5 audit: leads, opportunities, lead_history, reminders, ai_activity,
and ai_followups used to be scoped only through customer_mapping's
customer_phone -> business_phone lookup - a mapping that gets silently
overwritten (not preserved historically) every time
crm/customer_mapping.py's save_mapping() runs for that customer_phone.

That's fine as long as a given phone number only ever talks to one
WhatsPilot-hosted business. But nothing stopped the *same* phone number
from messaging two different businesses (e.g. it's someone's real
personal number, and they happen to be a customer of two unrelated
businesses that both run on WhatsPilot). Before this fix:

  - `leads` has customer_phone as its literal PRIMARY KEY, so Business
    B's very first INSERT for that phone wouldn't just be misattributed -
    it would silently overwrite Business A's entire row (status, notes,
    ai_paused, lead_score, all of it) via the ON CONFLICT(customer_phone)
    upsert every write path used.
  - opportunities/lead_history/reminders/ai_activity/ai_followups have no
    such PRIMARY KEY collision, but every read was still filtered by
    customer_phone alone - so a business asking "give me this customer's
    opportunities" would get *both* businesses' rows merged together, a
    real cross-tenant data leak, not just a theoretical one.

See migrations/add_business_id_to_crm_tables.py's module docstring for
the full writeup and the schema/migration side of the fix. These tests
prove the runtime side: every one of these tables now stamps and filters
by business_id (this deployment's own config.BUSINESS_ID, set once per
deployment - see config.py), so the same customer_phone can safely belong
to two different businesses' data without either colliding or leaking
into the other.
"""

import config
from crm.activity_manager import add_activity, get_activity, get_activity_timeline
from crm.followup_manager import save_followup, get_followups
from crm.lead_manager import (
    get_lead,
    update_lead,
    get_lead_timeline,
    pause_ai,
    resume_ai,
)
from crm.opportunity_manager import add_opportunity, get_opportunities
from reminder_manager import create_reminder, get_customer_reminders


SHARED_PHONE = "+91100000000"


def test_leads_do_not_collide_when_same_phone_contacts_two_businesses(isolated_db, monkeypatch):
    """
    The core PRIMARY KEY collision scenario: Business A and Business B
    both write a leads row for the exact same customer_phone. Before this
    fix, Business B's write would have overwritten Business A's row
    outright (both shared one row keyed by customer_phone alone). Now
    each business gets its own row, keyed by (customer_phone, business_id).
    """

    monkeypatch.setattr(config, "BUSINESS_ID", "bizA")
    update_lead(SHARED_PHONE, "Closed Won", "Great customer", confidence=90, updated_by="Manual")

    monkeypatch.setattr(config, "BUSINESS_ID", "bizB")
    update_lead(SHARED_PHONE, "New", "Just started talking", confidence=10, updated_by="Manual")

    # Business A's row must still say what Business A wrote - not
    # overwritten or merged with Business B's later write.
    monkeypatch.setattr(config, "BUSINESS_ID", "bizA")
    lead_a = get_lead(SHARED_PHONE)
    assert lead_a["status"] == "Closed Won"
    assert lead_a["notes"] == "Great customer"

    monkeypatch.setattr(config, "BUSINESS_ID", "bizB")
    lead_b = get_lead(SHARED_PHONE)
    assert lead_b["status"] == "New"
    assert lead_b["notes"] == "Just started talking"


def test_pause_ai_for_one_business_does_not_pause_the_other(isolated_db, monkeypatch):
    """
    Human handoff (pause_ai/resume_ai) is per (customer_phone, business_id)
    now too - Business A pausing AI for this shared phone number must not
    silently pause Business B's own conversation with the same person.
    """

    monkeypatch.setattr(config, "BUSINESS_ID", "bizA")
    update_lead(SHARED_PHONE, "New", "", confidence=0)
    pause_ai(SHARED_PHONE, "Customer asked for a human")

    monkeypatch.setattr(config, "BUSINESS_ID", "bizB")
    update_lead(SHARED_PHONE, "New", "", confidence=0)

    assert get_lead(SHARED_PHONE)["ai_paused"] in (0, False)

    monkeypatch.setattr(config, "BUSINESS_ID", "bizA")
    assert get_lead(SHARED_PHONE)["ai_paused"] in (1, True)

    resume_ai(SHARED_PHONE)
    assert get_lead(SHARED_PHONE)["ai_paused"] in (0, False)


def test_opportunities_scoped_per_business_for_same_phone(isolated_db, monkeypatch):

    monkeypatch.setattr(config, "BUSINESS_ID", "bizA")
    add_opportunity(SHARED_PHONE, "Consulting", 80, "Wants a proposal", estimated_value=5000)

    monkeypatch.setattr(config, "BUSINESS_ID", "bizB")
    add_opportunity(SHARED_PHONE, "Retail", 60, "Browsing", estimated_value=200)

    monkeypatch.setattr(config, "BUSINESS_ID", "bizA")
    opps_a = get_opportunities(SHARED_PHONE)
    assert [o["type"] for o in opps_a] == ["Consulting"]

    monkeypatch.setattr(config, "BUSINESS_ID", "bizB")
    opps_b = get_opportunities(SHARED_PHONE)
    assert [o["type"] for o in opps_b] == ["Retail"]


def test_activity_scoped_per_business_for_same_phone(isolated_db, monkeypatch):

    monkeypatch.setattr(config, "BUSINESS_ID", "bizA")
    add_activity(SHARED_PHONE, "Manual", "Note from Biz A", "Called them")

    monkeypatch.setattr(config, "BUSINESS_ID", "bizB")
    add_activity(SHARED_PHONE, "Manual", "Note from Biz B", "Emailed them")

    monkeypatch.setattr(config, "BUSINESS_ID", "bizA")
    activity_a = get_activity(SHARED_PHONE)
    assert [a["title"] for a in activity_a] == ["Note from Biz A"]

    timeline_a = get_activity_timeline(SHARED_PHONE)
    assert [a["title"] for a in timeline_a] == ["Note from Biz A"]

    monkeypatch.setattr(config, "BUSINESS_ID", "bizB")
    activity_b = get_activity(SHARED_PHONE)
    assert [a["title"] for a in activity_b] == ["Note from Biz B"]


def test_followups_scoped_per_business_for_same_phone(isolated_db, monkeypatch):

    monkeypatch.setattr(config, "BUSINESS_ID", "bizA")
    save_followup(SHARED_PHONE, "Biz A follow-up message")

    monkeypatch.setattr(config, "BUSINESS_ID", "bizB")
    save_followup(SHARED_PHONE, "Biz B follow-up message")

    monkeypatch.setattr(config, "BUSINESS_ID", "bizA")
    followups_a = get_followups(SHARED_PHONE)
    assert [f["message"] for f in followups_a] == ["Biz A follow-up message"]

    monkeypatch.setattr(config, "BUSINESS_ID", "bizB")
    followups_b = get_followups(SHARED_PHONE)
    assert [f["message"] for f in followups_b] == ["Biz B follow-up message"]


def test_reminders_scoped_per_business_for_same_phone(isolated_db, monkeypatch):

    monkeypatch.setattr(config, "BUSINESS_ID", "bizA")
    create_reminder(SHARED_PHONE, "Biz A reminder", due_in_days=1)

    monkeypatch.setattr(config, "BUSINESS_ID", "bizB")
    create_reminder(SHARED_PHONE, "Biz B reminder", due_in_days=1)

    monkeypatch.setattr(config, "BUSINESS_ID", "bizA")
    reminders_a = get_customer_reminders(SHARED_PHONE)
    assert [r["reminder_text"] for r in reminders_a] == ["Biz A reminder"]

    monkeypatch.setattr(config, "BUSINESS_ID", "bizB")
    reminders_b = get_customer_reminders(SHARED_PHONE)
    assert [r["reminder_text"] for r in reminders_b] == ["Biz B reminder"]


def test_lead_timeline_scoped_per_business_for_same_phone(isolated_db, monkeypatch):

    monkeypatch.setattr(config, "BUSINESS_ID", "bizA")
    update_lead(SHARED_PHONE, "Interested", "", confidence=50, reason="Biz A transition")

    monkeypatch.setattr(config, "BUSINESS_ID", "bizB")
    update_lead(SHARED_PHONE, "Qualified", "", confidence=70, reason="Biz B transition")

    monkeypatch.setattr(config, "BUSINESS_ID", "bizA")
    timeline_a = get_lead_timeline(SHARED_PHONE)
    assert [t["reason"] for t in timeline_a] == ["Biz A transition"]

    monkeypatch.setattr(config, "BUSINESS_ID", "bizB")
    timeline_b = get_lead_timeline(SHARED_PHONE)
    assert [t["reason"] for t in timeline_b] == ["Biz B transition"]
