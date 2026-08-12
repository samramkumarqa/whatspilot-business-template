import logging

from llm import ask_llm
from ai.utils import parse_ai_json

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are an experienced Sales Manager.

Analyse the customer conversation.

Identify possible business opportunities.

Return ONLY valid JSON.

Schema

{
    "has_opportunity": true,
    "type":"",
    "confidence":0,
    "estimated_value":0,
    "priority":"",
    "reason":"",
    "recommended_action":""
}

Rules

type must be one of

Upsell
Cross Sell
Renewal
New Sale
None

confidence

0-100 integer. How confident you are that this is a genuine sales
opportunity.

priority

Low
Medium
High
Critical

estimated_value

Integer only.

If no opportunity exists:

{
    "has_opportunity": false,
    "type":"None",
    "confidence":0,
    "estimated_value":0,
    "priority":"Low",
    "reason":"",
    "recommended_action":""
}
"""

DEFAULT_RESPONSE = {
    "has_opportunity": False,
    "type": "None",
    "confidence": 0,
    "estimated_value": 0,
    "priority": "Low",
    "reason": "",
    "recommended_action": "",
}

VALID_TYPES = {"Upsell", "Cross Sell", "Renewal", "New Sale", "None"}
VALID_PRIORITIES = {"Low", "Medium", "High", "Critical"}


def analyse_opportunity(conversation):

    prompt = f"""
Customer Conversation

--------------------

{conversation}

Identify business opportunities.

Return JSON only.
"""

    try:

        response = ask_llm(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=prompt
        )

        result = parse_ai_json(response, DEFAULT_RESPONSE.copy())

        # Fill any keys the LLM omitted rather than crashing the caller.
        # NOTE: this schema previously had no "confidence" key at all, while
        # ai/lead_intelligence.py's refresh_customer_intelligence() reads
        # opportunity["confidence"] directly - every genuine detection
        # raised a KeyError there, silently aborting the rest of that
        # function (saving the opportunity, logging its activity, logging
        # intelligence changes, saving tags).
        for key, value in DEFAULT_RESPONSE.items():
            result.setdefault(key, value)

        if result["type"] not in VALID_TYPES:
            result["type"] = DEFAULT_RESPONSE["type"]

        if result["priority"] not in VALID_PRIORITIES:
            result["priority"] = DEFAULT_RESPONSE["priority"]

        try:
            result["confidence"] = max(0, min(100, int(result["confidence"])))
        except (TypeError, ValueError):
            result["confidence"] = DEFAULT_RESPONSE["confidence"]

        try:
            result["estimated_value"] = int(result["estimated_value"])
        except (TypeError, ValueError):
            result["estimated_value"] = DEFAULT_RESPONSE["estimated_value"]

        return result

    except Exception:

        logger.exception("Opportunity analysis failed")

        return DEFAULT_RESPONSE.copy()
