"""
Tests for the 5-rule cap on automation rules (see automation/manager.py's
MAX_AUTOMATION_RULES and api/automation.py's create_automation_rule()).

The limit is enforced in the API route rather than in
automation.manager.create_rule() itself (that function stays a plain
insert), so these tests call the route function directly - asyncio.run()
gives it a real event loop without needing pytest-asyncio as a dependency.

Multi-tenancy: every route now takes user_id and resolves business_id
server-side (see api/automation.py's _resolve_business_id()), so a
business has to be registered via save_customer_number() before these
routes will resolve anything - an unregistered user_id 404s instead of
falling back to the old global/unscoped behavior.
"""

import asyncio

from api.automation import (
    create_automation_rule,
    update_automation_rule,
    AutomationRuleRequest,
)
from automation.manager import get_rule_count, delete_rule, MAX_AUTOMATION_RULES
from crm.customer_mapping import save_customer_number
from tests.conftest import FakeRequest

# These tests call the route functions directly, bypassing the real
# ASGI app/session middleware - a business_owner FakeRequest scoped to
# the same user_id being operated on passes enforce_tenant_access()'s
# business-ownership check the same way a real logged-in session would,
# so it's not what these tests are about (see
# test_business_cannot_edit_another_businesss_rule/
# test_business_cannot_delete_another_businesss_rule below, which are
# specifically about the business_id 404 check, not session auth - u2's
# own legitimate session is used there too, since the point is that u2
# still can't touch u1's rule even with valid credentials for u2's own
# business).
def _as(user_id):
    return FakeRequest({"role": "business_owner", "user_id": user_id})


def _rule_payload(name="Rule", value=80):
    return AutomationRuleRequest(
        name=name,
        description="",
        enabled=True,
        trigger_type="lead_score",
        condition_json=[{"field": "lead_score", "operator": ">=", "value": value}],
        action_json=[{"name": "create_reminder", "params": {"text": "Follow up", "days": 1}}],
    )


def _create(user_id="u1", name="Rule", value=80):
    return asyncio.run(
        create_automation_rule(user_id, _rule_payload(name, value), _as(user_id))
    )


def _register(user_id="u1", business_id="biz1"):
    save_customer_number(user_id, f"+1{user_id}", business_id)


def test_get_rule_count_reflects_created_rules(isolated_db):
    _register()

    assert get_rule_count("biz1") == 0

    _create()

    assert get_rule_count("biz1") == 1


def test_create_automation_rule_blocks_sixth_rule(isolated_db):
    _register()

    for i in range(MAX_AUTOMATION_RULES):
        result = _create(name=f"Rule {i}")
        assert result["status"] == "success"

    assert get_rule_count("biz1") == MAX_AUTOMATION_RULES

    result = _create(name="One too many")

    assert result["status"] == "limit_reached"
    assert str(MAX_AUTOMATION_RULES) in result["message"]

    # The 6th attempt must not have actually inserted a row.
    assert get_rule_count("biz1") == MAX_AUTOMATION_RULES


def test_deleting_a_rule_frees_a_slot(isolated_db):
    _register()

    ids = [_create(name=f"Rule {i}")["id"] for i in range(MAX_AUTOMATION_RULES)]

    assert _create(name="Blocked while full")["status"] == "limit_reached"

    delete_rule(ids[0], "biz1")

    result = _create(name="Replacement")

    assert result["status"] == "success"
    assert get_rule_count("biz1") == MAX_AUTOMATION_RULES


def test_editing_an_existing_rule_is_unaffected_by_the_cap(isolated_db):
    # PUT (edit) doesn't add a new row, so it must keep working even when
    # the business is already sitting right at the 5-rule cap.
    _register()

    ids = [_create(name=f"Rule {i}")["id"] for i in range(MAX_AUTOMATION_RULES)]

    result = asyncio.run(
        update_automation_rule(
            "u1", ids[0], _rule_payload("Rule 0 - renamed"), _as("u1")
        )
    )

    assert result["status"] == "success"
    assert get_rule_count("biz1") == MAX_AUTOMATION_RULES


def test_unregistered_user_id_404s(isolated_db):
    from fastapi import HTTPException
    import pytest

    with pytest.raises(HTTPException) as exc_info:
        _create(user_id="ghost")

    assert exc_info.value.status_code == 404


def test_rule_cap_is_per_business_not_global(isolated_db):
    # A second business's rules must not count against the first
    # business's 5-rule cap - this is the whole point of scoping
    # get_rule_count() by business_id (see automation/manager.py).
    _register("u1", "biz1")
    _register("u2", "biz2")

    for i in range(MAX_AUTOMATION_RULES):
        assert _create(user_id="u1", name=f"Biz1 Rule {i}")["status"] == "success"

    # biz1 is now full, but biz2 hasn't created anything yet.
    assert _create(user_id="u2", name="Biz2 Rule")["status"] == "success"
    assert get_rule_count("biz2") == 1
    assert get_rule_count("biz1") == MAX_AUTOMATION_RULES


def test_business_cannot_edit_another_businesss_rule(isolated_db):
    from fastapi import HTTPException
    import pytest

    _register("u1", "biz1")
    _register("u2", "biz2")

    rule_id = _create(user_id="u1", name="Biz1 Rule")["id"]

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            update_automation_rule("u2", rule_id, _rule_payload("Hijacked"), _as("u2"))
        )

    assert exc_info.value.status_code == 404


def test_business_cannot_delete_another_businesss_rule(isolated_db):
    from fastapi import HTTPException
    from api.automation import delete_automation_rule
    import pytest

    _register("u1", "biz1")
    _register("u2", "biz2")

    rule_id = _create(user_id="u1", name="Biz1 Rule")["id"]

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(delete_automation_rule("u2", rule_id, _as("u2")))

    assert exc_info.value.status_code == 404
    assert get_rule_count("biz1") == 1
