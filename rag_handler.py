from groq import AsyncGroq
import logging

from config import GROQ_API_KEY
from vector_store import get_retriever
from crm.customer_mapping import (
    get_business_settings,
)

logger = logging.getLogger(__name__)

client = AsyncGroq(api_key=GROQ_API_KEY)


def build_query(user_message: str, history=None) -> str:

    if not history:
        return user_message

    recent_history = history[-4:]

    conversation = "\n".join(
        f"{msg['role']}: {msg['content']}"
        for msg in recent_history
    )

    return f"""
Conversation:
{conversation}

Current Question:
{user_message}
""".strip()


async def handle_rag(
    user_message: str,
    history=None,
    user_id=None,
) -> str:

    try:

        if history and len(user_message.split()) <= 5:

            query = build_query(
                user_message,
                history,
            )

            logger.info(
                "Using conversation-aware retrieval"
            )

        else:

            query = user_message

            logger.info(
                "Using direct retrieval"
            )

        logger.info(f"RAG Query: {query}")

        retriever = get_retriever(user_id)

        if retriever is None:

            logger.error(
                "Retriever is None - vector store not initialized"
            )

            return (
                "No knowledge base found for this user."
            )

        docs = retriever.invoke(query)

        logger.info(
            f"Retrieved {len(docs)} documents"
        )

        if not docs:

            return (
                "I could not find relevant information "
                "in the uploaded documents."
            )

        context = "\n\n".join(
            doc.page_content
            for doc in docs
        )

        sources = []

        for doc in docs:

            src = doc.metadata.get(
                "source",
                "Unknown Source",
            )

            if src not in sources:
                sources.append(src)

        # ==========================
        # BUSINESS SETTINGS
        # ==========================

        settings = get_business_settings(
            user_id
        )

        business_name = settings.get(
            "business_name",
            "Business",
        )

        phone = settings.get(
            "phone",
            "",
        )

        email = settings.get(
            "email",
            "",
        )

        website = settings.get(
            "website",
            "",
        )

        welcome_message = settings.get(
            "welcome_message",
            "",
        )

        ai_instructions = settings.get(
            "ai_instructions",
            "",
        )

        # ==========================
        # GROQ CALL
        # ==========================

        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": f"""
You are the AI assistant for:

Business Name:
{business_name}

Business Contact Details:
Phone: {phone}
Email: {email}
Website: {website}

Welcome Message:
{welcome_message}

Business Instructions:
{ai_instructions}

Rules:
- Answer ONLY using the provided context.
- Follow the business instructions.
- Be helpful and concise.
- If information is not found, say:
  "I could not find that information in the knowledge base."
- Answer in under 500 words.
- Use bullet points.
- Avoid repeating information.

Context:
{context}
""",
                },
                {
                    "role": "user",
                    "content": user_message,
                },
            ],
            temperature=0,
        )

        answer = (
            response
            .choices[0]
            .message
            .content
        )

        if sources:

            answer += "\n\n📚 Source(s):\n"

            answer += "\n".join(
                f"• {s}"
                for s in sources
            )

        return answer

    except Exception as e:

        logger.exception(
            f"RAG failed: {e}"
        )

        return (
            "Sorry, I am unable to access "
            "the knowledge base right now."
        )