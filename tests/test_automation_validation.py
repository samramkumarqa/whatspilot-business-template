"""
Tests for the server-side field/shape validation on AutomationRuleRequest
(api/automation.py) - added as defense-in-depth alongside the client-side
sanitizers/validators in templates/dashboard.html, since this route can be
called directly, bypassing anything the rule editor UI enforces.

Covers: name/description character + length limits, and the
condition_json/action_json field_validators that mirror the frontend's
CONDITION_FIELD_CONFIG (unknown fields, wrong operator for a field's kind,
out-of-range/wrong-type values, unsupported actions, and Reminder
Text/Days limits).

See tests/test_automation_rules.py for the separate 5-rule cap behavior.
"""

import pytest
from pydantic import ValidationError

from api.automation import AutomationRuleRequest


def _base_kwargs(**overrides):
    kwargs = dict(
        name="High Value Lead",
        description="Flags hot leads",
        trigger_type="lead_score",
        condition_json=[{"field": "lead_score", "operator": ">=", "value": 80}],
        action_json=[{"name": "create_reminder", "params": {"text": "Follow up", "days": 1}}],
    )
    kwargs.update(overrides)
    return kwargs


def test_valid_rule_is_accepted():
    req = AutomationRuleRequest(**_base_kwargs())
    assert req.name == "High Value Lead"


def test_select_field_condition_is_accepted():
    req = AutomationRuleRequest(**_base_kwargs(
        trigger_type="status",
        condition_json=[{"field": "status", "operator": "=", "value": "Qualified"}],
    ))
    assert req.condition_json[0]["value"] == "Qualified"


@pytest.mark.parametrize("bad_name", [
    "",
    "x" * 101,
    "Rule <script>alert(1)</script>",
    "Rule; DROP TABLE rules;",
])
def test_invalid_rule_name_rejected(bad_name):
    with pytest.raises(ValidationError):
        AutomationRuleRequest(**_base_kwargs(name=bad_name))


def test_description_allows_normal_punctuation():
    req = AutomationRuleRequest(**_base_kwargs(
        description="Follows up with leads scoring 80+, fast!"
    ))
    assert "80+" in req.description


def test_description_rejects_angle_brackets():
    with pytest.raises(ValidationError):
        AutomationRuleRequest(**_base_kwargs(description="<b>bad</b>"))


def test_description_over_limit_rejected():
    with pytest.raises(ValidationError):
        AutomationRuleRequest(**_base_kwargs(description="x" * 301))


def test_empty_conditions_rejected():
    with pytest.raises(ValidationError):
        AutomationRuleRequest(**_base_kwargs(condition_json=[]))


def test_unknown_condition_field_rejected():
    with pytest.raises(ValidationError):
        AutomationRuleRequest(**_base_kwargs(
            condition_json=[{"field": "ssn", "operator": "=", "value": "x"}]
        ))


def test_wrong_operator_for_select_field_rejected():
    with pytest.raises(ValidationError):
        AutomationRuleRequest(**_base_kwargs(
            condition_json=[{"field": "status", "operator": ">=", "value": "New"}]
        ))


def test_out_of_range_numeric_value_rejected():
    with pytest.raises(ValidationError):
        AutomationRuleRequest(**_base_kwargs(
            condition_json=[{"field": "lead_score", "operator": ">=", "value": 500}]
        ))


def test_non_numeric_value_for_numeric_field_rejected():
    with pytest.raises(ValidationError):
        AutomationRuleRequest(**_base_kwargs(
            condition_json=[{"field": "lead_score", "operator": ">=", "value": "abc"}]
        ))


def test_invalid_select_option_rejected():
    with pytest.raises(ValidationError):
        AutomationRuleRequest(**_base_kwargs(
            condition_json=[{"field": "status", "operator": "=", "value": "Bogus"}]
        ))


def test_empty_actions_rejected():
    with pytest.raises(ValidationError):
        AutomationRuleRequest(**_base_kwargs(action_json=[]))


def test_unsupported_action_rejected():
    with pytest.raises(ValidationError):
        AutomationRuleRequest(**_base_kwargs(
            action_json=[{"name": "delete_everything", "params": {}}]
        ))


def test_reminder_text_with_angle_brackets_rejected():
    with pytest.raises(ValidationError):
        AutomationRuleRequest(**_base_kwargs(
            action_json=[{"name": "create_reminder", "params": {"text": "<b>hi</b>", "days": 1}}]
        ))


def test_reminder_text_over_limit_rejected():
    with pytest.raises(ValidationError):
        AutomationRuleRequest(**_base_kwargs(
            action_json=[{"name": "create_reminder", "params": {"text": "x" * 201, "days": 1}}]
        ))


@pytest.mark.parametrize("bad_days", [0, -5, 9999, "abc", None])
def test_days_out_of_range_or_wrong_type_rejected(bad_days):
    with pytest.raises(ValidationError):
        AutomationRuleRequest(**_base_kwargs(
            action_json=[{"name": "create_reminder", "params": {"text": "hi", "days": bad_days}}]
        ))
