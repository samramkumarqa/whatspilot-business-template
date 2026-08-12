from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, field_validator

from auth import enforce_tenant_access
from automation.manager import (
    get_rules,
    get_rule,
    get_rule_count,
    create_rule,
    update_rule,
    delete_rule,
    set_enabled,
    MAX_AUTOMATION_RULES,
)
from crm.customer_mapping import get_business_id

router = APIRouter(tags=["Automation"])


async def _resolve_business_id(request: Request, user_id: str) -> str:
    """
    Every route below is scoped to one business's rules. Two checks
    happen here, both required: enforce_tenant_access() confirms the
    *session* is allowed to act as user_id at all (admin, or a
    business_owner whose own login resolved to this exact user_id) -
    without it, a logged-in business owner could edit another
    business's rules just by changing the user_id in the URL. Then
    resolving business_id server-side (rather than trusting a
    client-supplied one) is what the rule CRUD functions actually filter
    by. A user_id that isn't registered in customer_numbers (see
    crm/customer_mapping.py) has no rules to manage, so it's a 404 here
    rather than silently falling back to the old global/unscoped
    behavior.
    """

    enforce_tenant_access(request, user_id)

    business_id = await run_in_threadpool(get_business_id, user_id)

    if business_id is None:

        raise HTTPException(
            status_code=404,
            detail="Unknown business for this user_id"
        )

    return business_id


# --------------------------------------------------------
# Request Models
# --------------------------------------------------------

from typing import List, Dict, Any

# Mirrors templates/dashboard.html's CONDITION_FIELD_CONFIG - the single
# source of truth the frontend's condition-row builder uses for which
# fields/operators/value ranges are valid. Kept here too so a direct API
# call can't smuggle in a condition the UI would never have produced (an
# unknown field, an operator that field doesn't support, or a value of
# the wrong shape/range).
CONDITION_FIELD_CONFIG = {
    "lead_score": {"kind": "number", "min": 0, "max": 100},
    "last_seen_days": {"kind": "number", "min": 0, "max": None},
    "confidence": {"kind": "number", "min": 0, "max": 100},
    "status": {
        "kind": "select",
        "options": [
            "New", "Interested", "Qualified",
            "Proposal Sent", "Closed Won", "Closed Lost",
        ],
    },
    "sentiment": {
        "kind": "select",
        "options": ["Positive", "Neutral", "Negative"],
    },
}

NUMERIC_OPERATORS = {">=", ">", "<=", "<", "=", "!="}
SELECT_OPERATORS = {"=", "!="}

ACTION_TEXT_MAX_LENGTH = 200
ACTION_DAYS_MIN = 1
ACTION_DAYS_MAX = 365


class AutomationRuleRequest(BaseModel):

    # Letters, numbers, spaces, and common punctuation (& - ' . ,) - same
    # allowlist as Rule Name's sanitizeNameInput() on the dashboard.
    name: str = Field(
        min_length=1, max_length=100,
        pattern=r"^[a-zA-Z0-9À-ÿ &'\-.,]+$"
    )

    # Free text - only angle brackets are disallowed.
    description: str = Field(default="", max_length=300, pattern=r"^[^<>]*$")

    enabled: bool = True

    trigger_type: str

    condition_json: List[Dict[str, Any]]

    action_json: List[Dict[str, Any]]

    @field_validator("condition_json")
    @classmethod
    def validate_conditions(cls, conditions):

        if not conditions:
            raise ValueError("At least one condition is required.")

        for condition in conditions:

            field = condition.get("field")
            operator = condition.get("operator")
            value = condition.get("value")

            config = CONDITION_FIELD_CONFIG.get(field)

            if config is None:
                raise ValueError(f"Unknown condition field: {field!r}")

            if config["kind"] == "number":

                if operator not in NUMERIC_OPERATORS:
                    raise ValueError(
                        f"Invalid operator {operator!r} for field {field!r}."
                    )

                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise ValueError(
                        f"Value for {field!r} must be a number."
                    )

                if value < config["min"]:
                    raise ValueError(
                        f"Value for {field!r} must be >= {config['min']}."
                    )

                if config["max"] is not None and value > config["max"]:
                    raise ValueError(
                        f"Value for {field!r} must be <= {config['max']}."
                    )

            else:  # select

                if operator not in SELECT_OPERATORS:
                    raise ValueError(
                        f"Invalid operator {operator!r} for field {field!r}."
                    )

                if value not in config["options"]:
                    raise ValueError(
                        f"Value for {field!r} must be one of {config['options']}."
                    )

        return conditions

    @field_validator("action_json")
    @classmethod
    def validate_actions(cls, actions):

        if not actions:
            raise ValueError("At least one action is required.")

        for action in actions:

            # Create Reminder is the only action type (see
            # automation/actions/registry.py) - anything else has no
            # executor to run it.
            if action.get("name") != "create_reminder":
                raise ValueError(
                    f"Unsupported action: {action.get('name')!r}"
                )

            params = action.get("params") or {}
            text = params.get("text") or params.get("title") or ""
            days = params.get("days")

            if not text or not text.strip():
                raise ValueError("Reminder Text is required.")

            if len(text) > ACTION_TEXT_MAX_LENGTH:
                raise ValueError(
                    f"Reminder Text must be {ACTION_TEXT_MAX_LENGTH} "
                    f"characters or fewer."
                )

            if "<" in text or ">" in text:
                raise ValueError("Reminder Text can't contain < or >.")

            if (
                not isinstance(days, (int, float))
                or isinstance(days, bool)
                or not (ACTION_DAYS_MIN <= days <= ACTION_DAYS_MAX)
            ):
                raise ValueError(
                    f"Days must be a number between {ACTION_DAYS_MIN} "
                    f"and {ACTION_DAYS_MAX}."
                )

        return actions


class EnableRuleRequest(BaseModel):

    enabled: bool


# --------------------------------------------------------
# List Rules
# --------------------------------------------------------

@router.get("/automation/rules/{user_id}")
async def list_rules(user_id: str, request: Request):

    business_id = await _resolve_business_id(request, user_id)

    return {

        "status": "success",

        "rules": await run_in_threadpool(get_rules, False, business_id)

    }


# --------------------------------------------------------
# Get Single Rule
# --------------------------------------------------------

@router.get("/automation/rules/{user_id}/{rule_id}")
async def get_automation_rule(user_id: str, rule_id: int, request: Request):

    business_id = await _resolve_business_id(request, user_id)

    rule = await run_in_threadpool(get_rule, rule_id, business_id)

    if rule is None:

        raise HTTPException(
            status_code=404,
            detail="Rule not found"
        )

    return {

        "status": "success",

        "rule": rule

    }


# --------------------------------------------------------
# Create Rule
# --------------------------------------------------------

@router.post("/automation/rules/{user_id}")
async def create_automation_rule(
    user_id: str,
    request: AutomationRuleRequest,
    http_request: Request
):

    business_id = await _resolve_business_id(http_request, user_id)

    existing_count = await run_in_threadpool(get_rule_count, business_id)

    if existing_count >= MAX_AUTOMATION_RULES:

        return {

            "status": "limit_reached",

            "message": (
                f"Only {MAX_AUTOMATION_RULES} automation rules are "
                f"allowed. Delete an existing rule before creating a "
                f"new one."
            )

        }

    rule_id = await run_in_threadpool(
        create_rule, request.model_dump(), business_id
    )

    return {

        "status": "success",

        "id": rule_id

    }


# --------------------------------------------------------
# Update Rule
# --------------------------------------------------------

@router.put("/automation/rules/{user_id}/{rule_id}")
async def update_automation_rule(
    user_id: str,
    rule_id: int,
    request: AutomationRuleRequest,
    http_request: Request
):

    business_id = await _resolve_business_id(http_request, user_id)

    if await run_in_threadpool(get_rule, rule_id, business_id) is None:

        raise HTTPException(
            status_code=404,
            detail="Rule not found"
        )

    await run_in_threadpool(
        update_rule,
        rule_id,
        request.model_dump(),
        business_id
    )

    return {

        "status": "success"

    }


# --------------------------------------------------------
# Enable / Disable Rule
# --------------------------------------------------------
#
# NOTE: this used to be two separate routes - a validated PATCH
# .../enabled (with a 404 check) that nothing called, and this PUT
# .../enabled (the one templates/dashboard.html's toggleRule() actually
# calls) which took a raw, unvalidated dict body and had no 404 check -
# a missing "enabled" key would raise an unhandled KeyError -> 500, and
# toggling a deleted/nonexistent rule_id would silently no-op instead of
# reporting an error. Consolidated into the one route that's actually
# used, with the same validation + 404 check the dead PATCH route had.

@router.put("/automation/rules/{user_id}/{rule_id}/enabled")
async def toggle_rule_enabled(
    user_id: str,
    rule_id: int,
    request: EnableRuleRequest,
    http_request: Request
):

    business_id = await _resolve_business_id(http_request, user_id)

    if await run_in_threadpool(get_rule, rule_id, business_id) is None:

        raise HTTPException(
            status_code=404,
            detail="Rule not found"
        )

    await run_in_threadpool(
        set_enabled,
        rule_id,
        request.enabled,
        business_id
    )

    return {

        "status": "success"

    }


# --------------------------------------------------------
# Delete Rule
# --------------------------------------------------------

@router.delete("/automation/rules/{user_id}/{rule_id}")
async def delete_automation_rule(user_id: str, rule_id: int, request: Request):

    business_id = await _resolve_business_id(request, user_id)

    if await run_in_threadpool(get_rule, rule_id, business_id) is None:

        raise HTTPException(
            status_code=404,
            detail="Rule not found"
        )

    await run_in_threadpool(delete_rule, rule_id, business_id)

    return {

        "status": "success"

    }