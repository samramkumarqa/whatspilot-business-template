import asyncio

from groq import AsyncGroq
import logging

from config import GROQ_API_KEY
from vector_store import similarity_search, get_user_lock
from crm.customer_mapping import (
    get_business_settings,
)
from website_manager import get_websites

logger = logging.getLogger(__name__)

client = AsyncGroq(api_key=GROQ_API_KEY)


def _retrieve_docs(user_id, query):
    """
    Synchronous Postgres read, run off the event loop via asyncio.to_thread
    below - both because it's a blocking DB call that would otherwise
    stall every other concurrent request on this deployment, and so the
    per-user lock (see vector_store.py) can safely block this worker
    thread without freezing the whole app if it lands while a
    background reindex is mid-write.
    """

    with get_user_lock(user_id):

        return similarity_search(user_id, query, k=5, fetch_k=20)


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

        docs = await asyncio.to_thread(
            _retrieve_docs,
            user_id,
            query,
        )

        logger.info(
            f"Retrieved {len(docs)} documents"
        )

        if not docs:

            # Distinguishes "nothing indexed at all" from "indexed, but
            # nothing relevant matched this question" - the same two
            # messages this branch always returned, just now driven by
            # a real check instead of a retriever-is-None sentinel that
            # doesn't exist anymore now that website_chunks is a
            # regular Postgres table (it always "exists", even empty).
            has_website = await asyncio.to_thread(
                get_websites,
                user_id,
            )

            if not has_website:

                return (
                    "No knowledge base found for this user."
                )

            return (
                "I could not find relevant information "
                "in the uploaded documents."
            )

        context = "\n\n".join(
            doc["content"]
            for doc in docs
        )

        sources = []

        for doc in docs:

            src = doc.get(
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
            # llama-3.3-70b-versatile was shut down by Groq on 08/16/26 -
            # see llm.py's MODEL constant for the full explanation.
            model="openai/gpt-oss-120b",
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