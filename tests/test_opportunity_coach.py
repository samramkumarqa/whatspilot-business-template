"""
Regression coverage for the bug found while checking the product flow:
ai/opportunity_coach.py's LLM schema never included a "confidence" field,
while ai/lead_intelligence.py read opportunity["confidence"] directly -
every genuine opportunity detection raised a KeyError, silently aborting
the rest of refresh_customer_intelligence() (saving the opportunity,
logging its activity, logging intelligence changes, saving tags).

ask_llm() is monkeypatched here rather than calling the real Groq API -
these tests are about the parsing/defaulting/validation logic in
analyse_opportunity(), not the LLM itself.
"""

import json

import ai.opportunity_coach as opportunity_coach


def test_confidence_key_is_always_present(monkeypatch):
    # Simulates the LLM following its own documented schema faithfully.
    monkeypatch.setattr(
        opportunity_coach,
        "ask_llm",
        lambda system_prompt, user_prompt: json.dumps({
            "has_opportunity": True,
            "type": "Upsell",
            "confidence": 85,
            "estimated_value": 500,
            "priority": "High",
            "reason": "asked about a bigger package",
            "recommended_action": "send upsell quote",
        }),
    )

    result = opportunity_coach.analyse_opportunity("some conversation")

    assert result["has_opportunity"] is True
    assert result["confidence"] == 85


def test_missing_confidence_from_llm_defaults_instead_of_crashing(monkeypatch):
    # Simulates an LLM response that omits "confidence" entirely - this is
    # exactly what used to raise KeyError at the add_opportunity() call
    # site in ai/lead_intelligence.py.
    monkeypatch.setattr(
        opportunity_coach,
        "ask_llm",
        lambda system_prompt, user_prompt: json.dumps({
            "has_opportunity": True,
            "type": "Renewal",
            "estimated_value": 200,
            "priority": "Medium",
            "reason": "contract expiring soon",
            "recommended_action": "send renewal offer",
        }),
    )

    result = opportunity_coach.analyse_opportunity("some conversation")

    assert result["has_opportunity"] is True
    assert result["confidence"] == 0  # falls back to the documented default
    assert result["type"] == "Renewal"


def test_invalid_type_and_priority_fall_back_to_defaults(monkeypatch):
    monkeypatch.setattr(
        opportunity_coach,
        "ask_llm",
        lambda system_prompt, user_prompt: json.dumps({
            "has_opportunity": True,
            "type": "Something Made Up",
            "confidence": 150,  # out of range - should clamp to 100
            "priority": "Super Urgent",
            "reason": "x",
        }),
    )

    result = opportunity_coach.analyse_opportunity("some conversation")

    assert result["type"] == "None"
    assert result["priority"] == "Low"
    assert result["confidence"] == 100


def test_unparseable_llm_response_falls_back_to_no_opportunity(monkeypatch):
    monkeypatch.setattr(
        opportunity_coach,
        "ask_llm",
        lambda system_prompt, user_prompt: "not valid json at all",
    )

    result = opportunity_coach.analyse_opportunity("some conversation")

    assert result == opportunity_coach.DEFAULT_RESPONSE


def test_llm_call_raising_falls_back_to_no_opportunity(monkeypatch):
    def _raise(system_prompt, user_prompt):
        raise RuntimeError("groq is down")

    monkeypatch.setattr(opportunity_coach, "ask_llm", _raise)

    result = opportunity_coach.analyse_opportunity("some conversation")

    assert result == opportunity_coach.DEFAULT_RESPONSE
