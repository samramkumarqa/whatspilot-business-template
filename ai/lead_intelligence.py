

from llm import ask_llm
from crm.tag_manager import (
    save_tags,
    get_tags,
)
import logging
logger = logging.getLogger(__name__)
from analytics.analytics import get_conversation
from crm.lead_manager import (
    update_lead_intelligence,
    get_lead,
)
from crm.activity_manager import add_activity
from ai.opportunity_coach import analyse_opportunity
from crm.opportunity_manager import add_opportunity
from ai.sales_coach import get_next_best_action
from ai.utils import parse_ai_json
from ai.lead_ai import LEAD_STATUSES



AI_VERSION = "v1"

SYSTEM_PROMPT = """
You are an expert CRM Sales Assistant.

Analyse the customer's conversation.

Return ONLY valid JSON.

Schema

{
    "status":"",
    "intent":"",
    "buying_stage":"",
    "sentiment":"",
    "objection":"",
    "lead_score":0,
    "priority":"",
    "confidence":0,
    "probability":0,
    "next_action":"",
    "follow_up_days":0,
    "summary":"",
    "tags":[],
    "ai_version":""
}

Rules

Status is the CRM pipeline stage (different from Buying Stage below -
Buying Stage describes funnel position, Status is the deal's own
lifecycle). Status MUST be one of

- New
- Interested
- Qualified
- Proposal Sent
- Closed Won
- Closed Lost

Only choose Closed Won/Closed Lost if the conversation explicitly says
the deal was won, purchased, rejected, or cancelled - otherwise prefer
New/Interested/Qualified/Proposal Sent based on how far along the
conversation is.

Intent MUST be one of

- Pricing Inquiry
- Product Inquiry
- Complaint
- Support
- Purchase Ready
- Returning Customer
- General Inquiry

Buying Stage MUST be one of

- Awareness
- Interested
- Considering
- Ready to Buy
- Customer

Sentiment MUST be one of

- Positive
- Neutral
- Negative

Objection MUST be one of

- Price
- Competitor
- Timing
- Need Approval
- None

Priority MUST be one of

- Low
- Medium
- High
- Critical

Lead Score
0-100

Confidence
0-100

Probability
0-100

follow_up_days
Integer only.

tags

Return between 3 and 6 useful CRM tags.

Prefer choosing from the following standard CRM tags whenever possible:

Lead Status
- Hot Lead
- Warm Lead
- Cold Lead

Intent
- Pricing Inquiry
- Product Inquiry
- Purchase Ready
- General Inquiry
- Support
- Complaint

Buying Behaviour
- Returning Customer
- New Customer
- Decision Maker
- Needs Approval
- Budget Concern
- Competitor Mentioned
- Timing Concern

Sales
- Proposal Sent
- Demo Requested
- Follow-up Required
- Upsell Opportunity
- Cross Sell Opportunity

Relationship
- VIP Customer
- High Value Customer

Rules

- Return ONLY a JSON array.
- Use short CRM-friendly tags.
- Do not invent similar words if one of the standard tags fits.
- Maximum 6 tags.
- Minimum 3 tags.

Return JSON only.

Do NOT explain.

Do NOT use markdown.

Do NOT wrap JSON inside ``` blocks.
"""


DEFAULT_RESPONSE = {

    "status": "New",

    "intent": "General Inquiry",

    "buying_stage": "Interested",

    "sentiment": "Neutral",

    "objection": "None",

    "lead_score": 40,

    "priority": "Medium",

    "confidence": 20,

    "probability": 20,

    "next_action": "Manual Review",

    "follow_up_days": 1,

    "summary": "AI analysis failed.",

    "tags": [
        "Manual Review"
    ],

    "ai_version": AI_VERSION
}

def analyse_conversation(conversation_text):

    prompt = f"""
Customer Conversation

---------------------

{conversation_text}

Analyse the entire conversation.

Estimate missing information using context.

Choose 3 to 6 meaningful CRM tags.

Avoid creating new tag names when a standard CRM tag already applies.

Return VALID JSON ONLY.

Do not include markdown.

Do not explain your reasoning.
"""

    # Same enum detect_lead_status()/update_lead() use for a manually-set
    # status, so an AI-detected status and a manually-set one are always
    # directly comparable (and automation rule conditions on "status" work
    # against both).
    VALID_STATUSES = set(LEAD_STATUSES)

    VALID_INTENTS = {
        "Pricing Inquiry",
        "Product Inquiry",
        "Complaint",
        "Support",
        "Purchase Ready",
        "Returning Customer",
        "General Inquiry"
    }

    VALID_BUYING_STAGES = {
        "Awareness",
        "Interested",
        "Considering",
        "Ready to Buy",
        "Customer"
    }

    VALID_SENTIMENTS = {
        "Positive",
        "Neutral",
        "Negative"
    }

    VALID_OBJECTIONS = {
        "Price",
        "Competitor",
        "Timing",
        "Need Approval",
        "None"
    }

    VALID_PRIORITIES = {
        "Low",
        "Medium",
        "High",
        "Critical"
    }

    try:

        response = ask_llm(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=prompt
        )

        if isinstance(response, dict):
            result = response

        else:

            result = parse_ai_json(response, DEFAULT_RESPONSE.copy())

        # Fill missing keys
        for key, value in DEFAULT_RESPONSE.items():
            result.setdefault(key, value)

        # Ensure AI version always exists
        result.setdefault("ai_version", AI_VERSION)

        # Normalize string fields
        result["status"] = str(result["status"]).strip()
        result["intent"] = str(result["intent"]).strip()
        result["buying_stage"] = str(result["buying_stage"]).strip()
        result["sentiment"] = str(result["sentiment"]).strip()
        result["objection"] = str(result["objection"]).strip()
        result["priority"] = str(result["priority"]).strip()
        result["summary"] = str(result["summary"]).strip()
        result["next_action"] = str(result["next_action"]).strip()

        # Validate enum values
        if result["status"] not in VALID_STATUSES:
            result["status"] = DEFAULT_RESPONSE["status"]

        if result["intent"] not in VALID_INTENTS:
            result["intent"] = DEFAULT_RESPONSE["intent"]

        if result["buying_stage"] not in VALID_BUYING_STAGES:
            result["buying_stage"] = DEFAULT_RESPONSE["buying_stage"]

        if result["sentiment"] not in VALID_SENTIMENTS:
            result["sentiment"] = DEFAULT_RESPONSE["sentiment"]

        if result["objection"] not in VALID_OBJECTIONS:
            result["objection"] = DEFAULT_RESPONSE["objection"]

        if result["priority"] not in VALID_PRIORITIES:
            result["priority"] = DEFAULT_RESPONSE["priority"]

        # Numeric safety
        result["lead_score"] = max(
            0,
            min(100, int(result["lead_score"]))
        )

        result["confidence"] = max(
            0,
            min(100, int(result["confidence"]))
        )

        result["probability"] = max(
            0,
            min(100, int(result["probability"]))
        )

        result["follow_up_days"] = max(
            0,
            int(result["follow_up_days"])
        )

        # Normalize tags
        if not isinstance(result["tags"], list):
            result["tags"] = [str(result["tags"])]

        result["tags"] = sorted(
            {
                tag.strip()
                for tag in result["tags"]
                if tag and tag.strip()
            }
        )

        return result

    except Exception:

        logger.exception("Lead Intelligence Error")

        return DEFAULT_RESPONSE.copy()



async def refresh_customer_intelligence(
    user_id,
    customer_phone
):
    """
    Analyse the full conversation and update CRM.
    """

    messages = get_conversation(
        user_id,
        customer_phone
    )

    if not messages:
        logger.info(
            f"No conversation found for {customer_phone}"
        )
        return DEFAULT_RESPONSE.copy()

    conversation_text = ""

    for msg in messages:

        role = (
            "Customer"
            if msg["role"] == "user"
            else "Assistant"
        )

        conversation_text += (
            f"{role}: {msg['content']}\n"
        )

    #
    # Lead Intelligence
    #

    analysis = analyse_conversation(
        conversation_text
    )

    #
    # Stop if AI failed
    #

    if analysis.get("summary") == "AI analysis failed.":

        logger.warning(
            f"AI analysis failed for {customer_phone}. Skipping CRM update."
        )

        return analysis
    
    #
    # Opportunity Detection
    #

    # analyse_opportunity() always returns a fully-populated, validated
    # dict now (it parses/defaults/validates internally and never raises),
    # but keep this as a defensive fallback in case that ever changes.
    opportunity = analyse_opportunity(conversation_text)

    if isinstance(opportunity, str):
        opportunity = parse_ai_json(
            opportunity,
            {"has_opportunity": False}
        )

    #
    # Existing Lead
    #

    old_lead = get_lead(
        customer_phone
    )

    #
    # Update CRM Lead
    #

    update_lead_intelligence(
        customer_phone,
        analysis
    )

    #
    # AI Sales Coach
    #

    recommendation = get_next_best_action(
        analysis
    )

    add_activity(
        customer_phone,
        "Sales Coach",
        recommendation["action"],
        (
            f"Priority: {recommendation['priority']}\n"
            f"Reason: {recommendation['reason']}"
        )
    )

    #
    # Save Opportunity
    #

    if opportunity.get("has_opportunity"):

        add_opportunity(

            customer_phone,

            opportunity.get("type", "None"),

            opportunity.get("confidence", 0),

            opportunity.get("reason", ""),

            opportunity.get(
                "estimated_value",
                0
            )
        )

        add_activity(

            customer_phone,

            "AI",

            "Opportunity Detected",

            (
                f"Type: {opportunity.get('type', 'None')}\n"
                f"Priority: {opportunity.get('priority', 'Low')}\n"
                f"Estimated Value: ₹{opportunity.get('estimated_value', 0)}\n"
                f"Reason: {opportunity.get('reason', '')}\n"
                f"Recommended Action: {opportunity.get('recommended_action', '')}"
            )
        )

    #
    # Log Intelligence Changes
    #

    changed = (

        old_lead.get("status") != analysis["status"]

        or old_lead.get("lead_score") != analysis["lead_score"]

        or old_lead.get("intent") != analysis["intent"]

        or old_lead.get("buying_stage") != analysis["buying_stage"]

        or old_lead.get("sentiment") != analysis["sentiment"]

        or old_lead.get("next_action") != analysis["next_action"]

        or old_lead.get("summary") != analysis["summary"]
    )

    if changed:

        details = "\n".join([

            f"AI Version: {analysis.get('ai_version', AI_VERSION)}",

            f"Status: {analysis['status']}",

            f"Lead Score: {analysis['lead_score']}",

            f"Intent: {analysis['intent']}",

            f"Buying Stage: {analysis['buying_stage']}",

            f"Sentiment: {analysis['sentiment']}",

            f"Next Action: {analysis['next_action']}",

            f"Summary: {analysis['summary']}"
        ])

        add_activity(

            customer_phone,

            "AI",

            "Customer Intelligence Updated",

            details
        )

    #
    # Save Tags only if changed
    #

    old_tags = get_tags(
        customer_phone
    )

    new_tags = analysis.get(
        "tags",
        []
    )

    if sorted(old_tags) != sorted(new_tags):

        save_tags(
            customer_phone,
            new_tags
        )

        add_activity(

            customer_phone,

            "Tags",

            "Customer Tags Updated",

            ", ".join(new_tags)
        )

    logger.info(

        f"Updated AI tags for {customer_phone}: "

        f"{new_tags}"
    )


    return analysis