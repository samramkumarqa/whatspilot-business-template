from llm import ask_llm


def generate_executive_summary(user_id, dashboard):

    prompt = f"""
You are a CRM sales director.

Using the dashboard below, write a concise executive summary.

Requirements:
- Maximum 120 words
- Professional tone
- Highlight strengths
- Highlight risks
- Recommend top priorities
- No markdown
- Plain text only

Dashboard:
{dashboard}
"""

    try:
        summary = ask_llm(
            system_prompt="You are an experienced Sales Director.",
            user_prompt=prompt
        )

        return summary.strip()

    except Exception:
        return "Executive summary unavailable."