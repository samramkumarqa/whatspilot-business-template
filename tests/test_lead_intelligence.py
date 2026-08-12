"""
Regression coverage for ai/lead_intelligence.py's analyse_conversation() -
specifically the "status" field added alongside intent/buying_stage/etc.

Before this fix, the LLM schema never asked for a real CRM pipeline status
(New/Interested/Qualified/Proposal Sent/Closed Won/Closed Lost) at all - only
"buying_stage" (a different vocabulary describing funnel position, not
pipeline stage). crm/lead_manager.py's update_lead_intelligence() was then
writing buying_stage into the "status" column, so Lead Status conditions in
automation rules almost never matched anything real.

ask_llm() is monkeypatched here rather than calling the real Groq API - same
pattern as tests/test_opportunity_coach.py.
"""

import json

import ai.lead_intelligence as lead_intelligence


def _llm_response(**overrides):
    response = {
        "status": "Qualified",
        "intent": "Pricing Inquiry",
        "buying_stage": "Considering",
        "sentiment": "Positive",
        "objection": "None",
        "lead_score": 70,
        "priority": "High",
        "confidence": 80,
        "probability": 60,
        "next_action": "Send pricing",
        "follow_up_days": 1,
        "summary": "Customer asked about pricing.",
        "tags": ["Warm Lead", "Pricing Inquiry"],
    }
    response.update(overrides)
    return json.dumps(response)


def test_valid_status_from_llm_is_kept(monkeypatch):
    monkeypatch.setattr(
        lead_intelligence, "ask_llm",
        lambda system_prompt, user_prompt: _llm_response(status="Proposal Sent"),
    )

    result = lead_intelligence.analyse_conversation("some conversation")

    assert result["status"] == "Proposal Sent"


def test_invalid_status_falls_back_to_default(monkeypatch):
    # Simulates the LLM ignoring the enum and inventing something else -
    # should fall back to the documented default rather than storing junk
    # in a column automation rules filter on.
    monkeypatch.setattr(
        lead_intelligence, "ask_llm",
        lambda system_prompt, user_prompt: _llm_response(status="Super Interested"),
    )

    result = lead_intelligence.analyse_conversation("some conversation")

    assert result["status"] == lead_intelligence.DEFAULT_RESPONSE["status"]


def test_missing_status_from_llm_defaults_instead_of_crashing(monkeypatch):
    # Simulates an LLM response that omits "status" entirely.
    response = json.loads(_llm_response())
    del response["status"]

    monkeypatch.setattr(
        lead_intelligence, "ask_llm",
        lambda system_prompt, user_prompt: json.dumps(response),
    )

    result = lead_intelligence.analyse_conversation("some conversation")

    assert result["status"] == lead_intelligence.DEFAULT_RESPONSE["status"]


def test_status_is_independent_of_buying_stage(monkeypatch):
    # The core bug: status and buying_stage are different vocabularies and
    # must be tracked independently, not conflated.
    monkeypatch.setattr(
        lead_intelligence, "ask_llm",
        lambda system_prompt, user_prompt: _llm_response(
            status="Qualified", buying_stage="Ready to Buy",
        ),
    )

    result = lead_intelligence.analyse_conversation("some conversation")

    assert result["status"] == "Qualified"
    assert result["buying_stage"] == "Ready to Buy"


def test_unparseable_llm_response_falls_back_to_default_response(monkeypatch):
    monkeypatch.setattr(
        lead_intelligence, "ask_llm",
        lambda system_prompt, user_prompt: "not valid json at all",
    )

    result = lead_intelligence.analyse_conversation("some conversation")

    assert result == lead_intelligence.DEFAULT_RESPONSE
