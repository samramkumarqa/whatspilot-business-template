from groq import Groq

from config import GROQ_API_KEY

client = Groq(
    api_key=GROQ_API_KEY
)

MODEL = "llama-3.3-70b-versatile"


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