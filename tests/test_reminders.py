"""
Tests for reminder_manager.py's rule-traceability and stale-reminder
cleanup: a reminder created by an automation rule's "Create Reminder"
action now snapshots which rule (id + name) produced it, so the dashboard
can show "Triggered by: X" and so reminders whose originating rule has
since been deleted or edited to say something different can be detected
and cleared out.

automation_rules lives in conversations.db, reminders lives in
data/app.db (see database/db.py) - the isolated_db fixture initializes
both, matching the real app.
"""

from automation.database import create_rule, update_rule, delete_rule
from automation.actions.create_reminder import execute as create_reminder_action
from reminder_manager import (
    upsert_reminder,
    get_customer_reminders,
    find_stale_reminders,
    delete_stale_reminders,
)


def _rule(name, text, **overrides):
    data = {
        "name": name,
        "description": "",
        "enabled": True,
        "trigger_type": "lead_score",
        "condition_json": [{"field": "lead_score", "operator": ">=", "value": 80}],
        "action_json": [{"name": "create_reminder", "params": {"text": text, "days": 1}}],
    }
    data.update(overrides)
    return create_rule(data)


# ---------------------------------------------------------------------------
# upsert_reminder() snapshotting the source rule
# ---------------------------------------------------------------------------

def test_upsert_reminder_stores_source_rule(isolated_db):
    rule_id = _rule("High Value Lead", "VIP Customer Follow-up")

    upsert_reminder(
        "+19998887777", "VIP Customer Follow-up", 3,
        source_rule_id=rule_id, source_rule_name="High Value Lead",
    )

    reminders = get_customer_reminders("+19998887777")
    assert len(reminders) == 1
    assert reminders[0]["source_rule_id"] == rule_id
    assert reminders[0]["source_rule_name"] == "High Value Lead"


def test_upsert_reminder_without_rule_context_leaves_source_null(isolated_db):
    # Manual/legacy calls with no rule context (e.g. pre-existing rows from
    # before this feature existed) should not blow up.
    upsert_reminder("+19998887777", "Follow up", 1)

    reminders = get_customer_reminders("+19998887777")
    assert reminders[0]["source_rule_id"] is None
    assert reminders[0]["source_rule_name"] is None


def test_create_reminder_action_passes_rule_through(isolated_db):
    # automation/actions/create_reminder.py is what automation/executor.py
    # actually calls - exercise it directly the way executor.py does,
    # rule included.
    rule = {"id": 42, "name": "High Value Lead"}
    customer = {"phone": "+19998887777"}

    create_reminder_action(customer, {"text": "Call them", "days": 2}, rule)

    reminders = get_customer_reminders("+19998887777")
    assert reminders[0]["source_rule_id"] == 42
    assert reminders[0]["source_rule_name"] == "High Value Lead"


def test_create_reminder_action_without_rule_still_works(isolated_db):
    # executor.py always passes a rule now, but the parameter defaults to
    # None so the action stays callable on its own.
    customer = {"phone": "+19998887777"}

    create_reminder_action(customer, {"text": "Call them", "days": 2})

    reminders = get_customer_reminders("+19998887777")
    assert reminders[0]["source_rule_id"] is None


# ---------------------------------------------------------------------------
# find_stale_reminders() / delete_stale_reminders()
# ---------------------------------------------------------------------------

def test_reminder_without_source_rule_id_is_never_stale(isolated_db):
    upsert_reminder("+19998887777", "Old reminder", 1)  # no rule context

    assert find_stale_reminders() == []


def test_reminder_is_fresh_when_rule_still_says_the_same_thing(isolated_db):
    rule_id = _rule("High Value Lead", "VIP Customer Follow-up")

    upsert_reminder(
        "+19998887777", "VIP Customer Follow-up", 3,
        source_rule_id=rule_id, source_rule_name="High Value Lead",
    )

    assert find_stale_reminders() == []


def test_reminder_is_stale_when_rule_text_has_changed(isolated_db):
    rule_id = _rule("High Value Lead", "VIP Customer Follow-up")

    upsert_reminder(
        "+19998887777", "High value lead - Follow up", 3,
        source_rule_id=rule_id, source_rule_name="High Value Lead",
    )

    # The rule gets edited later to say something else - matches exactly
    # what happened in production (the rule's action text moved on, but
    # the already-created reminder kept its original wording).
    update_rule(rule_id, {
        "name": "High Value Lead",
        "description": "",
        "enabled": True,
        "trigger_type": "lead_score",
        "condition_json": [{"field": "lead_score", "operator": ">=", "value": 80}],
        "action_json": [{"name": "create_reminder", "params": {"text": "VIP Customer Follow-up", "days": 3}}],
    })

    stale = find_stale_reminders()
    assert len(stale) == 1
    assert stale[0]["customer_phone"] == "+19998887777"
    assert "says something different" in stale[0]["reason"]


def test_reminder_is_stale_when_rule_deleted(isolated_db):
    rule_id = _rule("High Value Lead", "VIP Customer Follow-up")

    upsert_reminder(
        "+19998887777", "VIP Customer Follow-up", 3,
        source_rule_id=rule_id, source_rule_name="High Value Lead",
    )

    delete_rule(rule_id)

    stale = find_stale_reminders()
    assert len(stale) == 1
    assert "no longer exists" in stale[0]["reason"]


def test_reminder_is_stale_when_rule_no_longer_has_create_reminder_action(isolated_db):
    rule_id = _rule("High Value Lead", "VIP Customer Follow-up")

    upsert_reminder(
        "+19998887777", "VIP Customer Follow-up", 3,
        source_rule_id=rule_id, source_rule_name="High Value Lead",
    )

    # Rule edited to no longer include a Create Reminder action at all
    # ("add_activity" used to be a real second action type here, but it's
    # been removed - any non-"create_reminder" action name demonstrates
    # the same "no reminder action configured" scenario).
    update_rule(rule_id, {
        "name": "High Value Lead",
        "description": "",
        "enabled": True,
        "trigger_type": "lead_score",
        "condition_json": [{"field": "lead_score", "operator": ">=", "value": 80}],
        "action_json": [{"name": "log_note", "params": {"title": "Logged"}}],
    })

    stale = find_stale_reminders()
    assert len(stale) == 1
    assert "no longer has a Create Reminder action" in stale[0]["reason"]


def test_delete_stale_reminders_removes_only_stale_ones(isolated_db):
    fresh_rule_id = _rule("Fresh Rule", "Still current text")
    stale_rule_id = _rule("Stale Rule", "Original text")

    upsert_reminder(
        "+11111111111", "Still current text", 1,
        source_rule_id=fresh_rule_id, source_rule_name="Fresh Rule",
    )
    upsert_reminder(
        "+22222222222", "Original text", 1,
        source_rule_id=stale_rule_id, source_rule_name="Stale Rule",
    )

    delete_rule(stale_rule_id)

    deleted_count = delete_stale_reminders()
    assert deleted_count == 1

    assert len(get_customer_reminders("+11111111111")) == 1
    assert len(get_customer_reminders("+22222222222")) == 0

    # Calling again is a no-op, nothing left to clear.
    assert delete_stale_reminders() == 0
