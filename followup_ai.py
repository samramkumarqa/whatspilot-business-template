from llm import ask_llm


SYSTEM_PROMPT = """
You are an experienced Sales Executive.

Write a short WhatsApp follow-up message.

Rules:

- Friendly
- Professional
- Under 80 words
- No markdown
- No bullet points
- No emojis
- Personalised
- Mention previous conversation naturally.
- End with a simple call-to-action.
"""


def generate_followup(conversation, lead):

    prompt = f"""
Conversation

----------------

{conversation}

Lead Information

----------------

Intent: {lead.get("intent")}

Buying Stage: {lead.get("buying_stage")}

Sentiment: {lead.get("sentiment")}

Objection: {lead.get("objection")}

Lead Score: {lead.get("lead_score")}

Next Action: {lead.get("next_action")}

Write the follow-up message only.
"""

    return ask_llm(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=prompt
    )