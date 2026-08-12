import logging

from groq import Groq
import json

from config import GROQ_API_KEY

client = Groq(
    api_key=GROQ_API_KEY
)

logger = logging.getLogger(__name__)

LEAD_STATUSES = [
    "New",
    "Interested",
    "Qualified",
    "Proposal Sent",
    "Closed Won",
    "Closed Lost"
]


def detect_lead_status(message):

    prompt = f"""
You are a sales lead qualification assistant.

Classify the customer message into ONE of:

New
Interested
Qualified
Proposal Sent
Closed Won
Closed Lost

Rules:

- Asking general questions -> New
- Wants more information -> Interested
- Wants pricing, demo, quotation, meeting -> Qualified
- Proposal already sent -> Proposal Sent
- Customer confirmed purchase -> Closed Won
- Customer rejected or not interested -> Closed Lost

Also provide:

- confidence (0-100)
- reason

Customer message:
{message}

Return ONLY valid JSON.

Example:

{{
    "status":"Qualified",
    "confidence":92,
    "reason":"Customer requested pricing and training details"
}}
"""

    try:

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0
        )

        result = response.choices[0].message.content.strip()

        result = result.replace("```json", "")
        result = result.replace("```", "")
        result = result.strip()

        data = json.loads(result)

        status = data.get(
            "status",
            "New"
        )

        if status not in LEAD_STATUSES:
            status = "New"

        confidence = data.get(
            "confidence",
            50
        )

        try:
            confidence = int(confidence)
        except Exception:
            confidence = 50

        confidence = max(
            0,
            min(100, confidence)
        )

        reason = data.get(
            "reason",
            ""
        )

        return {
            "status": status,
            "confidence": confidence,
            "reason": reason
        }

    except Exception:

        logger.exception("Lead AI error")

        return {
            "status": "New",
            "confidence": 50,
            "reason": "Unable to determine lead intent"
        }


def calculate_lead_score(
    status,
    confidence
):

    base_scores = {
        "New": 10,
        "Interested": 40,
        "Qualified": 70,
        "Proposal Sent": 85,
        "Closed Won": 100,
        "Closed Lost": 0
    }

    base = base_scores.get(
        status,
        10
    )

    score = int(
        (base * 0.6)
        +
        (confidence * 0.4)
    )

    return min(
        score,
        100
    )