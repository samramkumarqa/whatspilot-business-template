from groq import Groq

from config import GROQ_API_KEY

client = Groq(
    api_key=GROQ_API_KEY
)

# llama-3.3-70b-versatile was shut down by Groq on 08/16/26 (see
# https://console.groq.com/docs/deprecations) - every call through this
# model started returning "404 model_not_found", which is what silently
# broke lead intelligence, opportunity detection, and the sales coach
# (all three go through ask_llm() below). openai/gpt-oss-120b is Groq's
# own listed replacement and is still a Production-tier model (not
# Preview), matching this app's production usage.
MODEL = "openai/gpt-oss-120b"


def ask_llm(system_prompt: str, user_prompt: str) -> str:
    """
    Generic wrapper for Groq LLM.
    Returns plain text response.
    """

    response = client.chat.completions.create(
        model=MODEL,
        temperature=0.2,
        messages=[
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ]
    )

    return response.choices[0].message.content.strip()